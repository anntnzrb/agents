use std::collections::{BTreeMap, BTreeSet, HashSet};
use std::fmt::Write as _;
use std::fs::{self, File};
use std::io::{self, Write};
use std::path::{Path, PathBuf};
use thiserror::Error;

use crate::harness::{Harness, SyncEnv};
use crate::tool_launchers::{tool_launcher_default_args, tool_launchers};

pub const UNIX_WRAPPER_DIR: &[&str] = &[".local", "bin"];
pub const WRAPPER_STATE_FILE: &str = "wrappers.json";
pub const WRAPPER_MARKER: &str = "agents-managed-wrapper:v1";

#[derive(Debug, Error)]
pub enum WrapperError {
    #[error("I/O error at {path}: {source}")]
    Io {
        path: PathBuf,
        #[source]
        source: io::Error,
    },
    #[error("failed to serialize wrapper state: {0}")]
    Serialization(#[from] serde_json::Error),
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct WrapperState {
    pub version: u32,
    pub entries: Vec<PathBuf>,
}

impl Default for WrapperState {
    fn default() -> Self {
        Self {
            version: 1,
            entries: Vec::new(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WrapperDestination {
    pub path: PathBuf,
    pub content: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct WrapperReconcileResult {
    pub owned: Vec<PathBuf>,
    pub conflicts: Vec<PathBuf>,
    pub removed: Vec<PathBuf>,
}

/// Returns the wrapper binary directory for a given user home directory (`~/.local/bin`).
#[must_use]
pub fn wrapper_directory(home: &Path) -> PathBuf {
    let mut dir = PathBuf::from(home);
    for segment in UNIX_WRAPPER_DIR {
        dir.push(segment);
    }
    dir
}

/// Quotes a string for POSIX `/bin/sh` single-quoted literals.
/// Replaces `'` with `'"'"'` and surrounds the whole string with single quotes.
#[must_use]
pub fn shell_quote(value: &str) -> String {
    let escaped = value.replace('\'', "'\"'\"'");
    format!("'{escaped}'")
}

/// Default relative path for the agentium executable under `$HOME`.
pub const DEFAULT_AGENTIUM_HOME_BIN: &[&str] = &[".local", "share", "agentium", "bin", "agentium"];

/// Renders a POSIX shell wrapper script that invokes the sync engine runner via native agentium binary.
#[must_use]
pub fn render_launch_wrapper(
    source_name: &str,
    default_args: &[String],
    env: Option<&BTreeMap<String, String>>,
) -> String {
    render_launch_wrapper_with_engine(source_name, default_args, env, None)
}

/// Renders a POSIX shell wrapper script that invokes the sync engine runner, allowing an explicit engine binary path.
#[must_use]
pub fn render_launch_wrapper_with_engine(
    source_name: &str,
    default_args: &[String],
    env: Option<&BTreeMap<String, String>>,
    engine_binary: Option<&Path>,
) -> String {
    let mut script = String::new();
    script.push_str("#!/bin/sh\n");
    let _ = writeln!(script, "# {WRAPPER_MARKER}");
    script.push_str("set -eu\n");

    let default_bin_expr = engine_binary.map_or_else(
        || String::from("\"${HOME}/.local/share/agentium/bin/agentium\""),
        |bin| shell_quote(&bin.to_string_lossy()),
    );

    let _ = writeln!(
        script,
        "AGENTIUM_BIN=\"${{AGENTIUM_BIN:-{default_bin_expr}}}\""
    );
    script.push_str("if [ ! -x \"$AGENTIUM_BIN\" ] && command -v agentium >/dev/null 2>&1; then\n");
    script.push_str("  AGENTIUM_BIN=\"$(command -v agentium)\"\n");
    script.push_str("fi\n");
    script.push_str("if [ ! -x \"$AGENTIUM_BIN\" ]; then\n");
    script.push_str("  echo 'agents: agentium executable not found' >&2\n");
    script.push_str("  exit 127\n");
    script.push_str("fi\n");

    if let Some(env_vars) = env {
        for (key, value) in env_vars {
            let _ = writeln!(script, "export {key}={}", shell_quote(value));
        }
    }

    let quoted_source = shell_quote(source_name);

    if default_args.is_empty() {
        let _ = writeln!(
            script,
            "exec \"$AGENTIUM_BIN\" launch {quoted_source} -- \"$@\""
        );
    } else {
        let args_str: Vec<String> = default_args.iter().map(|arg| shell_quote(arg)).collect();
        let joined_args = args_str.join(" ");
        let _ = writeln!(
            script,
            "exec \"$AGENTIUM_BIN\" launch {quoted_source} -- {joined_args} \"$@\""
        );
    }
    script
}

/// Renders a POSIX shell wrapper script for a managed binary tool.
#[must_use]
pub fn render_managed_tool_wrapper(executable: &Path, config_path: &Path) -> String {
    let mut script = String::new();
    script.push_str("#!/bin/sh\n");
    let _ = writeln!(script, "# {WRAPPER_MARKER}");
    script.push_str("set -eu\n");
    let quoted_exec = shell_quote(&executable.to_string_lossy());
    let quoted_config = shell_quote(&config_path.to_string_lossy());
    let _ = writeln!(script, "exec {quoted_exec} --config {quoted_config} \"$@\"");
    script
}

/// Builds a `WrapperDestination` for a managed tool.
#[must_use]
pub fn managed_tool_wrapper_destination(
    home: &Path,
    command: &str,
    executable: &Path,
    config_path: &Path,
) -> WrapperDestination {
    WrapperDestination {
        path: wrapper_directory(home).join(command),
        content: render_managed_tool_wrapper(executable, config_path),
    }
}

/// Builds `WrapperDestination`s for all registered static tool launchers.
#[must_use]
pub fn tool_launcher_wrapper_destinations(home: &Path) -> Vec<WrapperDestination> {
    let mut destinations = Vec::new();
    for tool in tool_launchers() {
        let path = wrapper_directory(home).join(tool.bin);
        let default_args = tool_launcher_default_args(home, tool);
        let content = render_launch_wrapper(tool.id, &default_args, None);
        destinations.push(WrapperDestination { path, content });
    }
    destinations
}

/// Builds a `WrapperDestination` for a harness.
#[must_use]
pub fn harness_wrapper_destination(home: &Path, harness: &Harness) -> WrapperDestination {
    let path = wrapper_directory(home).join(&harness.launcher.bin);
    let env_btree: Option<BTreeMap<String, String>> = if harness.launcher.env.is_empty() {
        None
    } else {
        Some(harness.launcher.env.clone().into_iter().collect())
    };
    let content = render_launch_wrapper(
        &harness.source_name,
        &harness.launcher.default_args,
        env_btree.as_ref(),
    );
    WrapperDestination { path, content }
}

/// Builds all standard wrapper destinations (harnesses + static tools) for a `SyncEnv`.
#[must_use]
pub fn wrapper_destinations(sync_env: &SyncEnv) -> Vec<WrapperDestination> {
    let mut destinations = Vec::new();
    for harness in &sync_env.harnesses {
        destinations.push(harness_wrapper_destination(&sync_env.home, harness));
    }
    for tool_dest in tool_launcher_wrapper_destinations(&sync_env.home) {
        destinations.push(tool_dest);
    }
    destinations
}

/// High-level wrapper reconciliation for a `SyncEnv` with optional additional managed tool destinations.
#[must_use]
pub fn reconcile_wrappers(
    sync_env: &SyncEnv,
    additional_destinations: &[WrapperDestination],
) -> bool {
    let mut desired = wrapper_destinations(sync_env);
    desired.extend_from_slice(additional_destinations);
    match reconcile_wrapper_files(&sync_env.managed_state_home, Some(&sync_env.home), &desired) {
        Ok(result) => {
            for conflict in &result.conflicts {
                eprintln!(
                    "sync: warning: preserving unmanaged wrapper conflict: {}",
                    conflict.display()
                );
            }
            true
        }
        Err(e) => {
            eprintln!("sync: error: wrapper reconciliation failed: {e}");
            false
        }
    }
}

/// Checks whether a given path is a regular, non-symlink file containing the managed wrapper marker.
#[must_use]
pub fn is_managed_wrapper(target_path: &Path) -> bool {
    let Ok(metadata) = fs::symlink_metadata(target_path) else {
        return false;
    };
    if !metadata.is_file() || metadata.file_type().is_symlink() {
        return false;
    }
    let Ok(content) = fs::read_to_string(target_path) else {
        return false;
    };
    content.contains(WRAPPER_MARKER)
}

/// Reads the persistent wrapper state JSON file.
#[must_use]
pub fn read_wrapper_state(state_path: &Path) -> WrapperState {
    let Ok(content) = fs::read_to_string(state_path) else {
        return WrapperState::default();
    };

    let parsed: Result<WrapperState, _> = serde_json::from_str(&content);
    let Ok(state) = parsed else {
        return WrapperState::default();
    };

    let entries: BTreeSet<PathBuf> = state
        .entries
        .into_iter()
        .filter(|p| p.is_absolute())
        .collect();

    WrapperState {
        version: 1,
        entries: entries.into_iter().collect(),
    }
}

/// Atomically persists the wrapper state file.
pub fn write_wrapper_state(state_path: &Path, state: &WrapperState) -> Result<(), WrapperError> {
    let content = format!("{}\n", serde_json::to_string_pretty(state)?);

    if fs::read_to_string(state_path).is_ok_and(|existing| existing == content) {
        return Ok(());
    }

    if let Some(parent) = state_path.parent() {
        fs::create_dir_all(parent).map_err(|e| WrapperError::Io {
            path: parent.to_path_buf(),
            source: e,
        })?;
    }

    let temp_path = state_path.with_extension(format!("{}.tmp", std::process::id()));
    {
        let mut file = File::create(&temp_path).map_err(|e| WrapperError::Io {
            path: temp_path.clone(),
            source: e,
        })?;
        file.write_all(content.as_bytes())
            .map_err(|e| WrapperError::Io {
                path: temp_path.clone(),
                source: e,
            })?;
        file.flush().map_err(|e| WrapperError::Io {
            path: temp_path.clone(),
            source: e,
        })?;
    }

    if let Err(err) = fs::rename(&temp_path, state_path) {
        let _ = fs::remove_file(&temp_path);
        return Err(WrapperError::Io {
            path: state_path.to_path_buf(),
            source: err,
        });
    }

    Ok(())
}

#[derive(Debug, PartialEq, Eq)]
enum WriteWrapperStatus {
    Owned,
    Conflict,
}

fn write_managed_wrapper(
    target_path: &Path,
    content: &str,
) -> Result<WriteWrapperStatus, WrapperError> {
    if let Ok(metadata) = fs::symlink_metadata(target_path) {
        if !metadata.is_file() || metadata.file_type().is_symlink() {
            return Ok(WriteWrapperStatus::Conflict);
        }
        if !is_managed_wrapper(target_path) {
            return Ok(WriteWrapperStatus::Conflict);
        }
        if fs::read_to_string(target_path).is_ok_and(|existing| existing == content) {
            return Ok(WriteWrapperStatus::Owned);
        }
    }

    if let Some(parent) = target_path.parent() {
        fs::create_dir_all(parent).map_err(|e| WrapperError::Io {
            path: parent.to_path_buf(),
            source: e,
        })?;
    }

    let temp_path = target_path.with_extension(format!("{}.tmp", std::process::id()));
    {
        let mut file = File::create(&temp_path).map_err(|e| WrapperError::Io {
            path: temp_path.clone(),
            source: e,
        })?;
        file.write_all(content.as_bytes())
            .map_err(|e| WrapperError::Io {
                path: temp_path.clone(),
                source: e,
            })?;
        file.flush().map_err(|e| WrapperError::Io {
            path: temp_path.clone(),
            source: e,
        })?;

        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let _ = file.set_permissions(fs::Permissions::from_mode(0o755));
        }
    }

    if let Err(err) = fs::rename(&temp_path, target_path) {
        let _ = fs::remove_file(&temp_path);
        return Err(WrapperError::Io {
            path: target_path.to_path_buf(),
            source: err,
        });
    }

    Ok(WriteWrapperStatus::Owned)
}

/// Reconciles wrapper files against desired specifications, persisting state and protecting unmanaged files.
pub fn reconcile_wrapper_files(
    managed_state_home: &Path,
    home: Option<&Path>,
    desired: &[WrapperDestination],
) -> Result<WrapperReconcileResult, WrapperError> {
    let state_path = managed_state_home.join(WRAPPER_STATE_FILE);
    let previous = read_wrapper_state(&state_path);

    let desired_paths: HashSet<&Path> = desired.iter().map(|d| d.path.as_path()).collect();

    let mut allowed_directories: HashSet<PathBuf> = HashSet::new();
    for entry in desired {
        if let Some(parent) = entry.path.parent() {
            if let Ok(canonical) = parent.canonicalize() {
                allowed_directories.insert(canonical);
            } else {
                allowed_directories.insert(parent.to_path_buf());
            }
        }
    }
    if let Some(home_path) = home {
        let wrapper_dir = wrapper_directory(home_path);
        if let Ok(canonical) = wrapper_dir.canonicalize() {
            allowed_directories.insert(canonical);
        } else {
            allowed_directories.insert(wrapper_dir);
        }
    }

    let mut owned = Vec::new();
    let mut conflicts = BTreeSet::new();
    let mut removed = Vec::new();

    for old_path in &previous.entries {
        if desired_paths.contains(old_path.as_path()) {
            continue;
        }

        let is_allowed_dir = old_path.parent().is_some_and(|parent| {
            parent.canonicalize().map_or_else(
                |_| allowed_directories.contains(parent),
                |canonical| allowed_directories.contains(&canonical),
            )
        });

        if !is_allowed_dir {
            conflicts.insert(old_path.clone());
            continue;
        }

        if is_managed_wrapper(old_path) {
            match fs::remove_file(old_path) {
                Ok(()) => {}
                Err(err) if err.kind() == io::ErrorKind::NotFound => {}
                Err(err) => {
                    return Err(WrapperError::Io {
                        path: old_path.clone(),
                        source: err,
                    });
                }
            }
            removed.push(old_path.clone());
        } else {
            conflicts.insert(old_path.clone());
        }
    }

    for entry in desired {
        match write_managed_wrapper(&entry.path, &entry.content)? {
            WriteWrapperStatus::Owned => {
                owned.push(entry.path.clone());
            }
            WriteWrapperStatus::Conflict => {
                conflicts.insert(entry.path.clone());
            }
        }
    }

    let sorted_owned: BTreeSet<PathBuf> = owned.into_iter().collect();
    let updated_state = WrapperState {
        version: 1,
        entries: sorted_owned.clone().into_iter().collect(),
    };
    write_wrapper_state(&state_path, &updated_state)?;

    Ok(WrapperReconcileResult {
        owned: sorted_owned.into_iter().collect(),
        conflicts: conflicts.into_iter().collect(),
        removed,
    })
}

#[cfg(test)]
#[allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::indexing_slicing,
    clippy::panic
)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn test_shell_quote() {
        assert_eq!(shell_quote("simple"), "'simple'");
        assert_eq!(shell_quote("hello world"), "'hello world'");
        assert_eq!(shell_quote("it's cool"), "'it'\"'\"'s cool'");
        assert_eq!(shell_quote(""), "''");
    }

    #[test]
    fn test_render_launch_wrapper_basic() {
        let wrapper = render_launch_wrapper("codex", &[], None);
        assert!(wrapper.starts_with("#!/bin/sh\n"));
        assert!(wrapper.contains(WRAPPER_MARKER));
        assert!(wrapper.contains(
            "AGENTIUM_BIN=\"${AGENTIUM_BIN:-\"${HOME}/.local/share/agentium/bin/agentium\"}\""
        ));
        assert!(wrapper.contains("exec \"$AGENTIUM_BIN\" launch 'codex' -- \"$@\""));
        assert!(!wrapper.contains("bun"));
    }

    #[test]
    fn test_render_launch_wrapper_with_args_and_env() {
        let mut env = BTreeMap::new();
        env.insert(
            String::from("MY_KEY"),
            String::from("my 'value' with spaces"),
        );
        let args = vec![
            String::from("--force-summary"),
            String::from("--format"),
            String::from("md"),
        ];

        let wrapper = render_launch_wrapper("summarize", &args, Some(&env));
        assert!(wrapper.contains("export MY_KEY='my '\"'\"'value'\"'\"' with spaces'\n"));
        assert!(wrapper.contains(
            "exec \"$AGENTIUM_BIN\" launch 'summarize' -- '--force-summary' '--format' 'md' \"$@\"\n"
        ));
        assert!(!wrapper.contains("bun"));
    }

    #[test]
    fn test_render_managed_tool_wrapper() {
        let exec = Path::new("/usr/local/bin/cli-proxy-api");
        let config = Path::new("/home/user/.cli-proxy-api/config.yaml");
        let wrapper = render_managed_tool_wrapper(exec, config);
        assert!(wrapper.starts_with("#!/bin/sh\n"));
        assert!(wrapper.contains(WRAPPER_MARKER));
        assert!(wrapper.contains(
            "exec '/usr/local/bin/cli-proxy-api' --config '/home/user/.cli-proxy-api/config.yaml' \"$@\"\n"
        ));
    }

    #[test]
    fn test_wrapper_directory() {
        let home = Path::new("/Users/testuser");
        assert_eq!(
            wrapper_directory(home),
            PathBuf::from("/Users/testuser/.local/bin")
        );
    }

    #[test]
    fn test_reconcile_wrapper_files_idempotent_and_removes_stale() {
        let tmp = tempdir().unwrap();
        let home = tmp.path().join("home");
        let managed_state = tmp.path().join("state");
        fs::create_dir_all(&home).unwrap();
        fs::create_dir_all(&managed_state).unwrap();

        let codex_path = wrapper_directory(&home).join("codex");
        let summarize_path = wrapper_directory(&home).join("summarize");

        let desired = vec![
            WrapperDestination {
                path: codex_path.clone(),
                content: render_launch_wrapper("codex", &[], None),
            },
            WrapperDestination {
                path: summarize_path.clone(),
                content: render_launch_wrapper("summarize", &[], None),
            },
        ];

        let result1 = reconcile_wrapper_files(&managed_state, Some(&home), &desired).unwrap();
        assert_eq!(result1.owned.len(), 2);
        assert_eq!(result1.conflicts.len(), 0);
        assert_eq!(result1.removed.len(), 0);
        assert!(is_managed_wrapper(&codex_path));
        assert!(is_managed_wrapper(&summarize_path));

        // Second reconcile is idempotent
        let result2 = reconcile_wrapper_files(&managed_state, Some(&home), &desired).unwrap();
        assert_eq!(result2.owned.len(), 2);
        assert_eq!(result2.conflicts.len(), 0);
        assert_eq!(result2.removed.len(), 0);

        // Remove summarize from desired list
        let desired_only_codex = vec![WrapperDestination {
            path: codex_path.clone(),
            content: render_launch_wrapper("codex", &[], None),
        }];
        let result3 =
            reconcile_wrapper_files(&managed_state, Some(&home), &desired_only_codex).unwrap();
        assert_eq!(result3.owned, vec![codex_path.clone()]);
        assert_eq!(result3.removed, vec![summarize_path.clone()]);
        assert!(!summarize_path.exists());
        assert!(codex_path.exists());
    }

    #[test]
    fn test_reconcile_wrapper_files_preserves_unmanaged_conflicts() {
        let tmp = tempdir().unwrap();
        let home = tmp.path().join("home");
        let managed_state = tmp.path().join("state");
        fs::create_dir_all(wrapper_directory(&home)).unwrap();
        fs::create_dir_all(&managed_state).unwrap();

        let unmanaged_path = wrapper_directory(&home).join("custom-tool");
        fs::write(&unmanaged_path, "#!/bin/sh\necho custom\n").unwrap();

        let desired = vec![WrapperDestination {
            path: unmanaged_path.clone(),
            content: render_launch_wrapper("custom-tool", &[], None),
        }];

        let result = reconcile_wrapper_files(&managed_state, Some(&home), &desired).unwrap();
        assert_eq!(result.owned.len(), 0);
        assert_eq!(result.conflicts, vec![unmanaged_path.clone()]);
        assert_eq!(
            fs::read_to_string(&unmanaged_path).unwrap(),
            "#!/bin/sh\necho custom\n"
        );
    }

    #[test]
    fn test_stale_file_outside_allowed_directory_is_preserved_as_conflict() {
        let tmp = tempdir().unwrap();
        let home = tmp.path().join("home");
        let managed_state = tmp.path().join("state");
        fs::create_dir_all(&home).unwrap();
        fs::create_dir_all(&managed_state).unwrap();

        let outside_path = tmp.path().join("outside").join("stale-wrapper");
        fs::create_dir_all(outside_path.parent().unwrap()).unwrap();
        fs::write(
            &outside_path,
            format!("#!/bin/sh\n# {WRAPPER_MARKER}\nexit 0\n"),
        )
        .unwrap();

        // Put outside_path into previous state
        let state_path = managed_state.join(WRAPPER_STATE_FILE);
        write_wrapper_state(
            &state_path,
            &WrapperState {
                version: 1,
                entries: vec![outside_path.clone()],
            },
        )
        .unwrap();

        let result = reconcile_wrapper_files(&managed_state, Some(&home), &[]).unwrap();
        assert_eq!(result.conflicts, vec![outside_path.clone()]);
        assert!(outside_path.exists());
    }
}
