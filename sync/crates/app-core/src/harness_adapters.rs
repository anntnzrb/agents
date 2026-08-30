use std::collections::HashMap;
use std::fmt;
use std::str::FromStr;

use serde::{Deserialize, Serialize};

/// Supported host platform operating systems.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum HostPlatform {
    Darwin,
    Linux,
}

impl HostPlatform {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Darwin => "darwin",
            Self::Linux => "linux",
        }
    }

    /// Detect the current host platform from compile-time OS.
    #[must_use]
    pub const fn current() -> Option<Self> {
        if cfg!(target_os = "macos") {
            Some(Self::Darwin)
        } else if cfg!(target_os = "linux") {
            Some(Self::Linux)
        } else {
            None
        }
    }
}

impl fmt::Display for HostPlatform {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

impl FromStr for HostPlatform {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s {
            "darwin" | "macos" => Ok(Self::Darwin),
            "linux" => Ok(Self::Linux),
            other => Err(format!("unsupported platform: {other}")),
        }
    }
}

/// Specification for launching a harness binary.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct HarnessLauncherSpec {
    pub package: String,
    pub bin: String,
    pub dist_tag: Option<String>,
    pub smoke_check: Option<String>,
    pub default_args: Option<Vec<String>>,
    pub env: Option<HashMap<String, String>>,
}

/// Lifecycle hook specification on a harness adapter.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind")]
pub enum HarnessHookSpec {
    PackageBootstrap {
        manifest_file: Option<String>,
        settings_file: Option<String>,
        cache_subdir: Option<String>,
    },
    ExtensionDeps {
        root_dir: String,
    },
}

/// Definition for an adapter supported by sync.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HarnessAdapter {
    pub id: &'static str,
    pub home_segments: &'static [&'static str],
    pub platforms: &'static [HostPlatform],
    pub launcher: HarnessLauncherSpec,
    pub instruction_file: Option<&'static str>,
    pub runtime_subdir: Option<&'static str>,
    pub compat_managed_entries: &'static [&'static str],
    pub hooks: Vec<HarnessHookSpec>,
}

/// Returns all predefined static harness adapters with complete launcher definitions.
#[must_use]
#[allow(clippy::too_many_lines)]
pub fn predefined_adapters() -> Vec<HarnessAdapter> {
    vec![
        HarnessAdapter {
            id: "codex",
            home_segments: &[".codex"],
            platforms: &[HostPlatform::Darwin, HostPlatform::Linux],
            launcher: HarnessLauncherSpec {
                package: "@openai/codex".to_string(),
                bin: "codex".to_string(),
                dist_tag: None,
                smoke_check: None,
                default_args: None,
                env: None,
            },
            instruction_file: None,
            runtime_subdir: None,
            compat_managed_entries: &[],
            hooks: Vec::new(),
        },
        HarnessAdapter {
            id: "deepseek",
            home_segments: &[".dsh"],
            platforms: &[HostPlatform::Darwin, HostPlatform::Linux],
            launcher: HarnessLauncherSpec {
                package: "@deepseek-ai/dsh".to_string(),
                bin: "dsh".to_string(),
                dist_tag: None,
                smoke_check: None,
                default_args: None,
                env: None,
            },
            instruction_file: None,
            runtime_subdir: None,
            compat_managed_entries: &[],
            hooks: Vec::new(),
        },
        HarnessAdapter {
            id: "grok",
            home_segments: &[".grok"],
            platforms: &[HostPlatform::Darwin, HostPlatform::Linux],
            launcher: HarnessLauncherSpec {
                package: "@xai-official/grok".to_string(),
                bin: "grok".to_string(),
                dist_tag: None,
                smoke_check: None,
                default_args: None,
                env: None,
            },
            instruction_file: None,
            runtime_subdir: None,
            compat_managed_entries: &[],
            hooks: Vec::new(),
        },
        HarnessAdapter {
            id: "opencode",
            home_segments: &[".config", "opencode"],
            platforms: &[HostPlatform::Darwin, HostPlatform::Linux],
            launcher: HarnessLauncherSpec {
                package: "opencode-ai".to_string(),
                bin: "opencode".to_string(),
                dist_tag: None,
                smoke_check: None,
                default_args: None,
                env: None,
            },
            instruction_file: None,
            runtime_subdir: None,
            compat_managed_entries: &[],
            hooks: vec![HarnessHookSpec::ExtensionDeps {
                root_dir: ".".to_string(),
            }],
        },
        HarnessAdapter {
            id: "pi",
            home_segments: &[".pi"],
            platforms: &[HostPlatform::Darwin, HostPlatform::Linux],
            launcher: HarnessLauncherSpec {
                package: "@earendil-works/pi-coding-agent".to_string(),
                bin: "pi".to_string(),
                dist_tag: None,
                smoke_check: None,
                default_args: None,
                env: None,
            },
            instruction_file: None,
            runtime_subdir: Some("agent"),
            compat_managed_entries: &["legacy"],
            hooks: vec![
                HarnessHookSpec::PackageBootstrap {
                    manifest_file: Some("packages.json".to_string()),
                    settings_file: Some("settings.json".to_string()),
                    cache_subdir: Some(".local/share/agentium/pi-packages".to_string()),
                },
                HarnessHookSpec::ExtensionDeps {
                    root_dir: "extensions".to_string(),
                },
            ],
        },
        HarnessAdapter {
            id: "omp",
            home_segments: &[".omp"],
            platforms: &[HostPlatform::Darwin, HostPlatform::Linux],
            launcher: HarnessLauncherSpec {
                package: "@oh-my-pi/pi-coding-agent".to_string(),
                bin: "omp".to_string(),
                dist_tag: None,
                smoke_check: None,
                default_args: None,
                env: None,
            },
            instruction_file: None,
            runtime_subdir: Some("agent"),
            compat_managed_entries: &[],
            hooks: vec![HarnessHookSpec::ExtensionDeps {
                root_dir: ".".to_string(),
            }],
        },
    ]
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_platform_parsing() {
        assert_eq!(
            HostPlatform::from_str("darwin").ok(),
            Some(HostPlatform::Darwin)
        );
        assert_eq!(
            HostPlatform::from_str("linux").ok(),
            Some(HostPlatform::Linux)
        );
        assert!(HostPlatform::from_str("windows").is_err());
    }

    #[test]
    fn test_predefined_adapters_have_unique_ids() {
        let adapters = predefined_adapters();
        let mut ids = std::collections::HashSet::new();
        for adapter in &adapters {
            assert!(ids.insert(adapter.id));
            assert_ne!(adapter.home_segments.first(), None);
            assert_ne!(adapter.launcher.package, "");
            assert_ne!(adapter.launcher.bin, "");
        }
        assert_eq!(adapters.len(), 6);
    }
}
