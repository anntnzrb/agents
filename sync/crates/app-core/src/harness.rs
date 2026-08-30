use std::collections::{BTreeMap, HashMap};
use std::fs;
use std::io;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};
use thiserror::Error;

use crate::harness_adapters::{HarnessAdapter, HarnessHookSpec, HostPlatform, predefined_adapters};

pub const SOURCE_AGENT_FILE: &str = "HARNESS.md";
pub const DEFAULT_INSTRUCTION_FILE: &str = "AGENTS.md";
pub const INSTALL_TIMEOUT_SECONDS: u64 = 120;
pub const MANAGED_STATE_SUBDIR: &str = ".local/share/agentium/sync-managed";
pub const DEFAULT_PACKAGE_CACHE_SUBDIR: &str = ".local/share/agentium/pi-packages";
pub const SKILLS_DST_DIR: &str = "skills";
pub const SKILLS_SOURCE_SUBDIR: &str = "current";

#[derive(Debug, Error)]
pub enum HarnessError {
    #[error("missing HOME environment variable")]
    MissingHome,
    #[error("unsupported platform: {0}")]
    UnsupportedPlatform(String),
    #[error("invalid {label}: {value}")]
    InvalidPathComponent { label: String, value: String },
    #[error("failed to read root environment file {path}: {source}")]
    RootEnvRead {
        path: PathBuf,
        #[source]
        source: io::Error,
    },
    #[error("io error: {0}")]
    Io(#[from] io::Error),
}

/// Normalized lifecycle hook on a harness.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind")]
pub enum HarnessHook {
    PackageBootstrap {
        manifest_file: String,
        settings_file: String,
        cache_subdir: String,
    },
    ExtensionDeps {
        root_dir: String,
    },
}

/// Fully resolved harness launcher configuration.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct HarnessLauncher {
    pub package: String,
    pub bin: String,
    pub dist_tag: String,
    pub smoke_check: String,
    pub default_args: Vec<String>,
    pub env: HashMap<String, String>,
}

/// A fully resolved harness instance.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Harness {
    pub id: String,
    pub source_name: String,
    pub home: PathBuf,
    pub launcher: HarnessLauncher,
    pub instruction_file: String,
    pub runtime_subdir: Option<String>,
    pub compat_managed_entries: Vec<String>,
    pub hooks: Vec<HarnessHook>,
}

/// Fully discovered sync environment paths and options.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SyncEnv {
    pub home: PathBuf,
    pub ssot_home: PathBuf,
    pub data_home: PathBuf,
    pub skills_home: PathBuf,
    pub harnesses_home: PathBuf,
    pub mcporter_home: PathBuf,
    pub summarize_home: PathBuf,
    pub managed_state_home: PathBuf,
    pub install_timeout_ms: u64,
    pub harnesses: Vec<Harness>,
    pub platform: HostPlatform,
    pub root_env: BTreeMap<String, String>,
}

impl SyncEnv {
    /// Constructs `SyncEnv` from system environment and default locations.
    pub fn from_system() -> Result<Self, HarnessError> {
        let home_str = std::env::var("HOME").map_err(|_| HarnessError::MissingHome)?;
        if home_str.trim().is_empty() {
            return Err(HarnessError::MissingHome);
        }
        let timeout_ms = INSTALL_TIMEOUT_SECONDS.saturating_mul(1000);
        Self::from_home(PathBuf::from(home_str), timeout_ms, None)
    }

    /// Constructs `SyncEnv` from a specified home root.
    pub fn from_home(
        home: PathBuf,
        install_timeout_ms: u64,
        platform_opt: Option<HostPlatform>,
    ) -> Result<Self, HarnessError> {
        let platform = match platform_opt {
            Some(p) => p,
            None => HostPlatform::current().ok_or_else(|| {
                HarnessError::UnsupportedPlatform(std::env::consts::OS.to_string())
            })?,
        };

        let ssot_home = home.join(".config").join("agents");
        let data_home = home.join(".local").join("share").join("agentium");
        let skills_home = ssot_home.join("skills");
        let harnesses_home = ssot_home.join("harnesses");
        let mcporter_home = home.join(".mcporter");
        let summarize_home = home.join(".summarize");
        let managed_state_home = home.join(MANAGED_STATE_SUBDIR);

        let root_env = load_root_env(&ssot_home.join(".env"))?;
        let harnesses = discover_harnesses(&home, &harnesses_home, platform)?;

        Ok(Self {
            home,
            ssot_home,
            data_home,
            skills_home,
            harnesses_home,
            mcporter_home,
            summarize_home,
            managed_state_home,
            install_timeout_ms,
            harnesses,
            platform,
            root_env,
        })
    }

    /// Find a discovered harness by its identifier.
    #[must_use]
    pub fn harness(&self, id: &str) -> Option<&Harness> {
        self.harnesses.iter().find(|h| h.id == id)
    }
}

/// Check that a path segment contains only valid characters.
pub fn assert_path_component(value: &str, label: &str) -> Result<(), HarnessError> {
    if value == "." || value == ".." || value.is_empty() {
        return Err(HarnessError::InvalidPathComponent {
            label: label.to_string(),
            value: value.to_string(),
        });
    }

    let is_valid = value
        .chars()
        .all(|c| c.is_ascii_alphanumeric() || c == '.' || c == '_' || c == '-');
    if !is_valid {
        return Err(HarnessError::InvalidPathComponent {
            label: label.to_string(),
            value: value.to_string(),
        });
    }

    Ok(())
}

/// Resolves the effective root directory of a harness in user home.
#[must_use]
pub fn harness_root(harness: &Harness) -> PathBuf {
    harness
        .runtime_subdir
        .as_deref()
        .map_or_else(|| harness.home.clone(), |subdir| harness.home.join(subdir))
}

/// Resolves the SSOT source directory for a harness.
#[must_use]
pub fn harness_source_root(harness: &Harness, harnesses_home: &Path) -> PathBuf {
    let base = harnesses_home.join(&harness.source_name);
    match &harness.runtime_subdir {
        Some(subdir) => base.join(subdir),
        None => base,
    }
}

/// Resolves the destination path for the instruction file in a harness.
#[must_use]
pub fn harness_instruction_target(harness: &Harness) -> PathBuf {
    harness_root(harness).join(&harness.instruction_file)
}

/// Returns the instruction file name for a harness.
#[must_use]
pub fn harness_instruction_file_name(harness: &Harness) -> &str {
    &harness.instruction_file
}

/// Resolves the managed state JSON path for a harness.
#[must_use]
pub fn harness_managed_state_path(harness: &Harness, managed_state_home: &Path) -> PathBuf {
    managed_state_home.join(format!("{}.json", harness.source_name))
}

/// Builds a `Harness` from an adapter definition and user home.
pub fn build_harness(
    adapter: &HarnessAdapter,
    home: &Path,
    source_name: &str,
) -> Result<Harness, HarnessError> {
    assert_path_component(source_name, "harness id")?;

    for segment in adapter.home_segments {
        assert_path_component(segment, &format!("{} home segment", adapter.id))?;
    }

    let mut harness_home = home.to_path_buf();
    for segment in adapter.home_segments {
        harness_home.push(segment);
    }

    let launcher = HarnessLauncher {
        package: adapter.launcher.package.clone(),
        bin: adapter.launcher.bin.clone(),
        dist_tag: adapter
            .launcher
            .dist_tag
            .clone()
            .unwrap_or_else(|| "latest".to_string()),
        smoke_check: adapter
            .launcher
            .smoke_check
            .clone()
            .unwrap_or_else(|| "--version".to_string()),
        default_args: adapter.launcher.default_args.clone().unwrap_or_default(),
        env: adapter.launcher.env.clone().unwrap_or_default(),
    };

    let instruction_file = adapter
        .instruction_file
        .unwrap_or(DEFAULT_INSTRUCTION_FILE)
        .to_string();
    let runtime_subdir = adapter.runtime_subdir.map(ToString::to_string);
    let compat_managed_entries = adapter
        .compat_managed_entries
        .iter()
        .map(|&s| s.to_string())
        .collect();

    let hooks = adapter
        .hooks
        .iter()
        .map(|hook| match hook {
            HarnessHookSpec::PackageBootstrap {
                manifest_file,
                settings_file,
                cache_subdir,
            } => HarnessHook::PackageBootstrap {
                manifest_file: manifest_file
                    .clone()
                    .unwrap_or_else(|| "packages.json".to_string()),
                settings_file: settings_file
                    .clone()
                    .unwrap_or_else(|| "settings.json".to_string()),
                cache_subdir: cache_subdir
                    .clone()
                    .unwrap_or_else(|| DEFAULT_PACKAGE_CACHE_SUBDIR.to_string()),
            },
            HarnessHookSpec::ExtensionDeps { root_dir } => HarnessHook::ExtensionDeps {
                root_dir: root_dir.clone(),
            },
        })
        .collect();

    Ok(Harness {
        id: adapter.id.to_string(),
        source_name: source_name.to_string(),
        home: harness_home,
        launcher,
        instruction_file,
        runtime_subdir,
        compat_managed_entries,
        hooks,
    })
}

/// Discovers active harnesses based on directory existence in `harnesses_home`.
pub fn discover_harnesses(
    home: &Path,
    harnesses_home: &Path,
    platform: HostPlatform,
) -> Result<Vec<Harness>, HarnessError> {
    let adapters = predefined_adapters();
    let mut results = Vec::new();

    for adapter in &adapters {
        if adapter.platforms.contains(&platform) && harnesses_home.join(adapter.id).is_dir() {
            let harness = build_harness(adapter, home, adapter.id)?;
            results.push(harness);
        }
    }

    Ok(results)
}

/// Finds a supported harness configuration if supported on this platform.
#[must_use]
pub fn supported_harness(
    home: &Path,
    source_name: &str,
    platform: HostPlatform,
) -> Option<Harness> {
    let adapters = predefined_adapters();
    let adapter = adapters
        .iter()
        .find(|a| a.id == source_name && a.platforms.contains(&platform))?;
    build_harness(adapter, home, source_name).ok()
}

/// Loads and decodes a `.env` file into key-value pairs, returning an empty map if missing.
pub fn load_root_env(path: &Path) -> Result<BTreeMap<String, String>, HarnessError> {
    match fs::read_to_string(path) {
        Ok(content) => Ok(decode_root_env(&content)),
        Err(err) if err.kind() == io::ErrorKind::NotFound => Ok(BTreeMap::new()),
        Err(err) => Err(HarnessError::RootEnvRead {
            path: path.to_path_buf(),
            source: err,
        }),
    }
}

/// Decodes `.env` format contents, preserving quotes and non-empty literals.
#[must_use]
pub fn decode_root_env(content: &str) -> BTreeMap<String, String> {
    let mut map = BTreeMap::new();

    for line in content.lines() {
        let trimmed = line.trim();
        if trimmed.is_empty() || trimmed.starts_with('#') {
            continue;
        }

        let Some((key_raw, val_raw)) = trimmed.split_once('=') else {
            continue;
        };

        let key = key_raw.trim();
        if key.is_empty() {
            continue;
        }

        let val_trimmed = val_raw.trim();
        let value = parse_dotenv_value(val_trimmed);

        if !value.is_empty() {
            map.insert(key.to_string(), value);
        }
    }

    map
}

fn parse_dotenv_value(raw: &str) -> String {
    if raw.is_empty() {
        return String::new();
    }

    if raw.starts_with('"') && raw.ends_with('"') && raw.len() >= 2 {
        let inner = raw.get(1..raw.len().saturating_sub(1)).unwrap_or_default();
        unescape_double_quotes(inner)
    } else if raw.starts_with('\'') && raw.ends_with('\'') && raw.len() >= 2 {
        raw.get(1..raw.len().saturating_sub(1))
            .unwrap_or_default()
            .to_string()
    } else {
        // Strip comments for unquoted values
        let unquoted = match raw.split_once('#') {
            Some((before, _)) => before.trim_end(),
            None => raw,
        };
        unquoted.to_string()
    }
}

fn unescape_double_quotes(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    let mut chars = s.chars();

    while let Some(c) = chars.next() {
        if c == '\\' {
            match chars.next() {
                Some('n') => out.push('\n'),
                Some('r') => out.push('\r'),
                Some('t') => out.push('\t'),
                Some(quote @ ('"' | '\\')) => out.push(quote),
                Some(other) => {
                    out.push('\\');
                    out.push(other);
                }
                None => out.push('\\'),
            }
        } else {
            out.push(c);
        }
    }

    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn test_root_env_returns_empty_when_missing() {
        let temp = match tempdir() {
            Ok(t) => t,
            Err(e) => panic!("tempdir: {e}"),
        };
        let env = match load_root_env(&temp.path().join(".env")) {
            Ok(e) => e,
            Err(e) => panic!("load: {e}"),
        };
        assert!(env.is_empty());
    }

    #[test]
    fn test_root_env_parses_dotenv_contents() {
        let content = r#"
# Shared test env
QUOTED_VAL="secret_value # not a comment"
SINGLE_QUOTED='single'
EMPTY_KEY=
EMPTY_QUOTED=""
VARIABLE_REF=${UNEXPANDED_VAR}
DOLLAR_PREFIX=$LITERAL_VAR
NESTED_PREFIX_A=foo
NESTED_PREFIX_B=bar
COMMAND_CODE_API_KEY=
API_KEY=12345
"#;
        let map = decode_root_env(content);
        assert_eq!(
            map.get("QUOTED_VAL").map(String::as_str),
            Some("secret_value # not a comment")
        );
        assert_eq!(map.get("SINGLE_QUOTED").map(String::as_str), Some("single"));
        assert_eq!(map.get("EMPTY_KEY"), None);
        assert_eq!(map.get("EMPTY_QUOTED"), None);
        assert_eq!(
            map.get("VARIABLE_REF").map(String::as_str),
            Some("${UNEXPANDED_VAR}")
        );
        assert_eq!(
            map.get("DOLLAR_PREFIX").map(String::as_str),
            Some("$LITERAL_VAR")
        );
        assert_eq!(map.get("NESTED_PREFIX_A").map(String::as_str), Some("foo"));
        assert_eq!(map.get("NESTED_PREFIX_B").map(String::as_str), Some("bar"));
        assert_eq!(map.get("COMMAND_CODE_API_KEY"), None);
        assert_eq!(map.get("API_KEY").map(String::as_str), Some("12345"));
    }

    #[test]
    fn test_root_env_fails_on_dir_read() {
        let temp = match tempdir() {
            Ok(t) => t,
            Err(e) => panic!("tempdir: {e}"),
        };
        let bad_env = temp.path().join(".env");
        if let Err(e) = fs::create_dir(&bad_env) {
            panic!("create_dir: {e}");
        }

        let res = load_root_env(&bad_env);
        assert!(res.is_err());
    }

    #[test]
    fn test_discover_harnesses_filters_by_existing_dir() {
        let temp = match tempdir() {
            Ok(t) => t,
            Err(e) => panic!("tempdir: {e}"),
        };
        let harnesses_home = temp.path().join(".config").join("agents").join("harnesses");
        if let Err(e) = fs::create_dir_all(harnesses_home.join("codex")) {
            panic!("create codex dir: {e}");
        }
        if let Err(e) = fs::create_dir_all(harnesses_home.join("omp")) {
            panic!("create omp dir: {e}");
        }

        let discovered = match discover_harnesses(temp.path(), &harnesses_home, HostPlatform::Linux)
        {
            Ok(d) => d,
            Err(e) => panic!("discover: {e}"),
        };
        let ids: Vec<_> = discovered.iter().map(|h| h.id.as_str()).collect();
        assert_eq!(ids, vec!["codex", "omp"]);
    }
}
