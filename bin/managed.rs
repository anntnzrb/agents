use std::collections::BTreeSet;
use std::fs;
use std::io::{ErrorKind, Write};
use std::path::{Component, Path, PathBuf};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use super::harness::{Harness, SyncEnv};
use super::{err, rm_entry};

#[derive(Clone, Debug)]
pub(super) struct ManagedSyncPlan {
    harnesses: Vec<ManagedHarnessPlan>,
}

#[derive(Clone, Debug)]
struct ManagedHarnessPlan {
    state_path: PathBuf,
    cleanup_paths: Vec<PathBuf>,
    current_entry_names: Vec<String>,
}

pub(super) fn plan_managed_entries(sync_env: &SyncEnv) -> Result<ManagedSyncPlan, String> {
    let harnesses = sync_env
        .harnesses
        .iter()
        .map(|harness| plan_harness(sync_env, harness))
        .collect::<Result<Vec<_>, _>>()?;
    Ok(ManagedSyncPlan { harnesses })
}

pub(super) fn clean_managed_entries(plan: &ManagedSyncPlan) -> bool {
    let mut success = true;
    for harness in &plan.harnesses {
        for path in &harness.cleanup_paths {
            if let Err(error) = rm_entry(path) {
                err(&format!("cleanup failed: {} ({error})", path.display()));
                success = false;
            }
        }
    }
    success
}

pub(super) fn record_managed_entries(plan: &ManagedSyncPlan) -> bool {
    let mut success = true;
    for harness in &plan.harnesses {
        if let Err(message) =
            write_recorded_entry_names(&harness.state_path, &harness.current_entry_names)
        {
            err(&format!("managed state write failed: {message}"));
            success = false;
        }
    }
    success
}

pub(super) fn asset_dir_names(path: &Path) -> Result<Vec<String>, String> {
    dir_entry_names(path, true)
}

pub(super) fn top_level_entry_names(path: &Path) -> Result<Vec<String>, String> {
    dir_entry_names(path, false)
}

fn dir_entry_names(path: &Path, dirs_only: bool) -> Result<Vec<String>, String> {
    if !path.is_dir() {
        return Ok(Vec::new());
    }

    let entries =
        fs::read_dir(path).map_err(|error| format!("read {} ({error})", path.display()))?;
    let mut names = Vec::new();
    for entry_result in entries {
        let entry = entry_result.map_err(|error| format!("read {} ({error})", path.display()))?;
        let file_type = entry
            .file_type()
            .map_err(|error| format!("stat {} ({error})", entry.path().display()))?;
        if dirs_only && !file_type.is_dir() {
            continue;
        }

        let name = entry.file_name();
        let name = name
            .to_str()
            .ok_or_else(|| format!("invalid UTF-8 path: {}", entry.path().display()))?;
        names.push(name.to_string());
    }
    names.sort();
    Ok(names)
}

fn plan_harness(sync_env: &SyncEnv, harness: &Harness) -> Result<ManagedHarnessPlan, String> {
    let current_entry_names = current_managed_entry_names(sync_env, harness)?;
    let state_path = harness.managed_state_path(&sync_env.managed_state_home);
    let mut cleanup_entry_names = BTreeSet::new();
    cleanup_entry_names.extend(current_entry_names.iter().cloned());
    cleanup_entry_names.extend(
        harness
            .compat_managed_entries
            .iter()
            .map(|entry| (*entry).to_string()),
    );
    cleanup_entry_names.extend(load_recorded_entry_names(&state_path)?);

    let harness_root = harness.root();
    Ok(ManagedHarnessPlan {
        state_path,
        cleanup_paths: cleanup_entry_names
            .into_iter()
            .filter_map(|entry| cleanup_path(&harness_root, &entry))
            .collect(),
        current_entry_names,
    })
}

fn current_managed_entry_names(
    sync_env: &SyncEnv,
    harness: &Harness,
) -> Result<Vec<String>, String> {
    let mut names = BTreeSet::new();
    names.insert(harness.instruction_file_name().to_string());

    for entry_name in top_level_entry_names(&harness.source_root(&sync_env.tools_home))? {
        names.insert(entry_name);
    }

    for asset_name in asset_dir_names(&sync_env.assets_home)? {
        names.insert(harness.rename_asset(&asset_name));
    }

    Ok(names.into_iter().collect())
}

fn load_recorded_entry_names(path: &Path) -> Result<Vec<String>, String> {
    let content = match fs::read_to_string(path) {
        Ok(content) => content,
        Err(error) if error.kind() == ErrorKind::NotFound => return Ok(Vec::new()),
        Err(error) => return Err(format!("read {} ({error})", path.display())),
    };

    let recorded: Vec<String> = match serde_json::from_str(&content) {
        Ok(recorded) => recorded,
        Err(error) => {
            warn(&format!(
                "managed state parse failed, ignoring {} ({error})",
                path.display()
            ));
            return Ok(Vec::new());
        }
    };

    let mut safe_names = BTreeSet::new();
    for entry_name in recorded {
        match safe_top_level_entry_name(&entry_name) {
            Some(name) => {
                safe_names.insert(name);
            }
            None => warn(&format!(
                "ignoring unsafe managed entry {:?} in {}",
                entry_name,
                path.display()
            )),
        }
    }
    Ok(safe_names.into_iter().collect())
}

fn write_recorded_entry_names(path: &Path, entry_names: &[String]) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)
            .map_err(|error| format!("create {} ({error})", parent.display()))?;
    }

    let content = format!(
        "{}\n",
        serde_json::to_string_pretty(entry_names)
            .map_err(|error| format!("serialize {} ({error})", path.display()))?
    );
    let (temp_path, mut temp_file) = create_temp_state_file(path)?;

    let result = (|| {
        temp_file
            .write_all(content.as_bytes())
            .map_err(|error| format!("write {} ({error})", temp_path.display()))?;
        temp_file
            .sync_all()
            .map_err(|error| format!("sync {} ({error})", temp_path.display()))?;
        drop(temp_file);
        fs::rename(&temp_path, path)
            .map_err(|error| format!("replace {} ({error})", path.display()))
    })();

    if result.is_err() {
        let _ = fs::remove_file(&temp_path);
    }

    result
}

fn cleanup_path(root: &Path, entry_name: &str) -> Option<PathBuf> {
    safe_top_level_entry_name(entry_name).map(|name| root.join(name))
}

fn safe_top_level_entry_name(entry_name: &str) -> Option<String> {
    let mut components = Path::new(entry_name).components();
    match (components.next(), components.next()) {
        (Some(Component::Normal(name)), None) => name.to_str().map(ToOwned::to_owned),
        _ => None,
    }
}

fn create_temp_state_file(path: &Path) -> Result<(PathBuf, fs::File), String> {
    let file_name = path
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or("managed-state.json");
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or(Duration::ZERO)
        .as_nanos();

    for attempt in 0..16_u32 {
        let temp_path = path.with_file_name(format!(
            ".{file_name}.{}.{}.tmp",
            std::process::id(),
            nonce + u128::from(attempt)
        ));
        match fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temp_path)
        {
            Ok(file) => return Ok((temp_path, file)),
            Err(error) if error.kind() == ErrorKind::AlreadyExists => continue,
            Err(error) => return Err(format!("create {} ({error})", temp_path.display())),
        }
    }

    Err(format!(
        "create temporary managed state near {} (name collision)",
        path.display()
    ))
}

fn warn(message: &str) {
    eprintln!("sync: warning: {message}");
}

#[cfg(test)]
mod tests {
    use std::fs;
    use std::path::Path;

    use super::super::harness::HarnessId;
    use tempfile::TempDir;

    use super::*;

    fn write_file(path: &Path, content: &str) {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).expect("create parent dirs");
        }
        fs::write(path, content).expect("write file")
    }

    #[test]
    fn invalid_recorded_entries_are_ignored_and_do_not_escape_harness_root() {
        let temp = TempDir::new().expect("tempdir");
        let sync_env = SyncEnv::from_home(temp.path().to_path_buf(), Duration::from_secs(1));
        let harness = sync_env.harness(HarnessId::Codex).expect("codex harness");
        let state_path = harness.managed_state_path(&sync_env.managed_state_home);
        write_file(
            &state_path,
            r#"[
  "good.txt",
  "..",
  "/tmp/escape",
  "nested/path",
  "../outside",
  "good.txt"
]"#,
        );

        let plan = plan_harness(&sync_env, harness).expect("plan harness");

        assert_eq!(
            plan.cleanup_paths,
            vec![
                harness.root().join("AGENTS.md"),
                harness.root().join("good.txt")
            ]
        );
    }

    #[test]
    fn malformed_recorded_state_is_recoverable() {
        let temp = TempDir::new().expect("tempdir");
        let sync_env = SyncEnv::from_home(temp.path().to_path_buf(), Duration::from_secs(1));
        let harness = sync_env.harness(HarnessId::Codex).expect("codex harness");
        let state_path = harness.managed_state_path(&sync_env.managed_state_home);
        write_file(&state_path, "{not valid json");

        assert_eq!(
            load_recorded_entry_names(&state_path).expect("recover load"),
            Vec::<String>::new()
        );
        let plan = plan_harness(&sync_env, harness).expect("recover plan");
        assert_eq!(plan.cleanup_paths, vec![harness.root().join("AGENTS.md")]);
    }

    #[test]
    fn recorded_state_write_persists_expected_json() {
        let temp = TempDir::new().expect("tempdir");
        let path = temp.path().join("state").join("codex.json");

        write_recorded_entry_names(&path, &["alpha".to_string(), "beta".to_string()])
            .expect("write state");

        assert_eq!(
            fs::read_to_string(&path).expect("read state"),
            "[\n  \"alpha\",\n  \"beta\"\n]\n"
        );
    }
}
