use std::collections::HashSet;
use std::fs;
use std::io;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};
use thiserror::Error;

use crate::cliproxy::deployment::{
    CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER, CLI_PROXY_SOURCE_DIR, CliProxyDeployment,
    CliProxyEndpointTarget, CliProxyError, is_cli_proxy_gateway_host, read_cli_proxy_deployment,
};
use crate::harness::{
    Harness, HarnessHook, SKILLS_DST_DIR, SKILLS_SOURCE_SUBDIR, SOURCE_AGENT_FILE, SyncEnv,
    harness_instruction_file_name, harness_instruction_target, harness_managed_state_path,
    harness_root, harness_source_root,
};

#[derive(Debug, Error)]
pub enum PlanError {
    #[error("failed to read deployment: {0}")]
    Deployment(#[from] CliProxyError),
    #[error("io error: {0}")]
    Io(#[from] io::Error),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum DirScope {
    Tree,
    Children,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind")]
pub enum Job {
    File {
        src: PathBuf,
        dst: PathBuf,
    },
    Dir {
        src: PathBuf,
        dst: PathBuf,
        #[serde(default = "default_dir_scope")]
        scope: DirScope,
        #[serde(default)]
        preserve_paths: Vec<String>,
    },
    SecretTemplate {
        src: PathBuf,
        dst: PathBuf,
        secrets_path: PathBuf,
    },
    CliProxyReadiness {
        deployment: CliProxyDeployment,
        gateway_host: bool,
    },
    CliProxyEndpointTemplates {
        #[serde(skip)]
        targets: Vec<CliProxyEndpointTarget>,
        deployment: CliProxyDeployment,
    },
    CliProxyConfig {
        src: PathBuf,
        dst: PathBuf,
        secrets_path: PathBuf,
        deployment: CliProxyDeployment,
        #[serde(default)]
        gateway_host: bool,
        #[serde(default)]
        cache_root: Option<PathBuf>,
        #[serde(default)]
        runtime_root: Option<PathBuf>,
    },
}

const fn default_dir_scope() -> DirScope {
    DirScope::Children
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PackageBootstrapHookPlan {
    pub harness: Harness,
    pub manifest_path: PathBuf,
    pub runtime_settings_path: PathBuf,
    pub cache_root: PathBuf,
    pub timeout_ms: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ExtensionDepsHookPlan {
    pub harness: Harness,
    pub job_root: PathBuf,
    pub root: PathBuf,
    pub source_root: PathBuf,
    pub relative_root: String,
    pub state_path: PathBuf,
    pub timeout_ms: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind")]
pub enum SyncHookPlan {
    PackageBootstrap(PackageBootstrapHookPlan),
    ExtensionDeps(ExtensionDepsHookPlan),
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct HarnessPlan {
    pub harness: Harness,
    pub state_path: PathBuf,
    pub root: PathBuf,
    pub source_root: PathBuf,
    pub instruction_target: PathBuf,
    pub current_entry_names: Vec<String>,
    pub cleanup_entry_names: Vec<String>,
    pub hooks: Vec<SyncHookPlan>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SyncPlan {
    pub harnesses: Vec<HarnessPlan>,
    pub jobs: Vec<Job>,
    pub hooks: Vec<SyncHookPlan>,
    pub cli_proxy_deployment: CliProxyDeployment,
    pub gateway_host: bool,
}

/// Constructs a complete, deterministic sync plan from `SyncEnv`.
pub fn build_sync_plan(sync_env: &SyncEnv) -> Result<SyncPlan, PlanError> {
    let deployment_path = sync_env
        .ssot_home
        .join(CLI_PROXY_SOURCE_DIR)
        .join("deployment.json");
    let cli_proxy_deployment = read_cli_proxy_deployment(&deployment_path)?;
    let gateway_host = is_cli_proxy_gateway_host(&cli_proxy_deployment, None);

    let harnesses: Vec<HarnessPlan> = sync_env
        .harnesses
        .iter()
        .map(|harness| build_harness_plan(sync_env, harness))
        .collect();

    let mut jobs = Vec::new();
    jobs.extend(harness_dir_jobs(&harnesses));
    jobs.extend(skills_jobs(sync_env, &harnesses));
    jobs.extend(instruction_jobs(sync_env, &harnesses));
    jobs.extend(config_jobs(
        sync_env,
        &harnesses,
        &cli_proxy_deployment,
        gateway_host,
    ));

    let hooks = harnesses
        .iter()
        .flat_map(|plan| plan.hooks.clone())
        .collect();

    Ok(SyncPlan {
        harnesses,
        jobs,
        hooks,
        cli_proxy_deployment,
        gateway_host,
    })
}

fn build_harness_plan(sync_env: &SyncEnv, harness: &Harness) -> HarnessPlan {
    let root = harness_root(harness);
    let source_root = harness_source_root(harness, &sync_env.harnesses_home);
    let instruction_target = harness_instruction_target(harness);

    let has_skills = skills_source_exists(sync_env);
    let current_entry_names = current_managed_entry_names(harness, &source_root, has_skills);

    let mut cleanup_set: HashSet<String> = current_entry_names.iter().cloned().collect();
    for entry in &harness.compat_managed_entries {
        cleanup_set.insert(entry.clone());
    }
    let mut cleanup_entry_names: Vec<String> = cleanup_set.into_iter().collect();
    cleanup_entry_names.sort();

    let hooks = build_hook_plans(sync_env, harness, &root, &source_root);
    let state_path = harness_managed_state_path(harness, &sync_env.managed_state_home);

    HarnessPlan {
        harness: harness.clone(),
        state_path,
        root,
        source_root,
        instruction_target,
        current_entry_names,
        cleanup_entry_names,
        hooks,
    }
}

fn current_managed_entry_names(
    harness: &Harness,
    source_root: &Path,
    has_skills_source: bool,
) -> Vec<String> {
    let mut names = HashSet::new();
    names.insert(harness_instruction_file_name(harness).to_string());

    for entry in top_level_entry_names(source_root) {
        names.insert(entry);
    }

    if has_skills_source {
        names.insert(SKILLS_DST_DIR.to_string());
    }

    let mut sorted: Vec<String> = names.into_iter().collect();
    sorted.sort();
    sorted
}

fn harness_dir_jobs(harnesses: &[HarnessPlan]) -> Vec<Job> {
    harnesses
        .iter()
        .map(|plan| {
            let endpoint_template = cli_proxy_endpoint_template_path(plan);
            Job::Dir {
                src: plan.source_root.clone(),
                dst: plan.root.clone(),
                scope: DirScope::Children,
                preserve_paths: endpoint_template.into_iter().collect(),
            }
        })
        .collect()
}

fn skills_jobs(sync_env: &SyncEnv, harnesses: &[HarnessPlan]) -> Vec<Job> {
    let skills_source = sync_env.skills_home.join(SKILLS_SOURCE_SUBDIR);
    harnesses
        .iter()
        .map(|plan| Job::Dir {
            src: skills_source.clone(),
            dst: plan.root.join(SKILLS_DST_DIR),
            scope: DirScope::Tree,
            preserve_paths: Vec::new(),
        })
        .collect()
}

fn skills_source_exists(sync_env: &SyncEnv) -> bool {
    sync_env.skills_home.join(SKILLS_SOURCE_SUBDIR).is_dir()
}

fn instruction_jobs(sync_env: &SyncEnv, harnesses: &[HarnessPlan]) -> Vec<Job> {
    let src = sync_env.ssot_home.join(SOURCE_AGENT_FILE);
    harnesses
        .iter()
        .map(|plan| Job::File {
            src: src.clone(),
            dst: plan.instruction_target.clone(),
        })
        .collect()
}

fn config_jobs(
    sync_env: &SyncEnv,
    harnesses: &[HarnessPlan],
    deployment: &CliProxyDeployment,
    gateway_host: bool,
) -> Vec<Job> {
    let mut endpoint_targets = Vec::new();
    for plan in harnesses {
        if let Some(rel_path) = cli_proxy_endpoint_template_path(plan) {
            let src = plan.source_root.join(&rel_path);
            let dst = plan.root.join(&rel_path);
            let preserve_top_levels = if plan.harness.id == "codex" {
                vec!["hooks.state".to_string(), "projects".to_string()]
            } else {
                Vec::new()
            };
            endpoint_targets.push(CliProxyEndpointTarget {
                src,
                dst,
                preserve_top_levels,
            });
        }
    }

    let mut jobs = vec![
        Job::CliProxyReadiness {
            deployment: deployment.clone(),
            gateway_host,
        },
        Job::File {
            src: sync_env
                .ssot_home
                .join("tools")
                .join("mcporter")
                .join("mcporter.jsonc"),
            dst: sync_env.mcporter_home.join("mcporter.json"),
        },
        Job::File {
            src: sync_env
                .ssot_home
                .join("tools")
                .join("summarize")
                .join("config.json"),
            dst: sync_env.summarize_home.join("config.json"),
        },
        Job::CliProxyConfig {
            src: sync_env
                .ssot_home
                .join(CLI_PROXY_SOURCE_DIR)
                .join("config.yaml.tmpl"),
            dst: sync_env.home.join(".cli-proxy-api").join("config.yaml"),
            secrets_path: sync_env
                .home
                .join(".config")
                .join("agents")
                .join("secrets.local.json"),
            deployment: deployment.clone(),
            gateway_host,
            cache_root: Some(
                sync_env
                    .home
                    .join(".cache")
                    .join("agents")
                    .join("model-catalog"),
            ),
            runtime_root: Some(sync_env.data_home.clone()),
        },
    ];

    if gateway_host {
        jobs.push(Job::File {
            src: sync_env
                .ssot_home
                .join(CLI_PROXY_SOURCE_DIR)
                .join("panel.html"),
            dst: sync_env
                .home
                .join(".cli-proxy-api")
                .join("static")
                .join("management.html"),
        });
    }

    jobs.push(Job::CliProxyEndpointTemplates {
        targets: endpoint_targets,
        deployment: deployment.clone(),
    });

    jobs
}

fn cli_proxy_endpoint_template_path(plan: &HarnessPlan) -> Option<String> {
    let rel_path = match plan.harness.id.as_str() {
        "codex" | "grok" => "config.toml",
        "opencode" => "opencode.jsonc",
        "pi" => "extensions/cliproxy/index.ts",
        "omp" => "models.yml",
        _ => return None,
    };

    let src = plan.source_root.join(rel_path);
    if !src.is_file() {
        return None;
    }

    let Ok(content) = fs::read_to_string(&src) else {
        return None;
    };
    if content.contains(CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER) {
        Some(rel_path.to_string())
    } else {
        None
    }
}

fn build_hook_plans(
    sync_env: &SyncEnv,
    harness: &Harness,
    root: &Path,
    source_root: &Path,
) -> Vec<SyncHookPlan> {
    harness
        .hooks
        .iter()
        .map(|hook| match hook {
            HarnessHook::PackageBootstrap {
                manifest_file,
                settings_file,
                cache_subdir,
            } => SyncHookPlan::PackageBootstrap(PackageBootstrapHookPlan {
                harness: harness.clone(),
                manifest_path: source_root.join(manifest_file),
                runtime_settings_path: root.join(settings_file),
                cache_root: sync_env.home.join(cache_subdir),
                timeout_ms: sync_env.install_timeout_ms,
            }),
            HarnessHook::ExtensionDeps { root_dir } => {
                let relative = root_dir.clone();
                let job_root = root.to_path_buf();
                let effective_root = if relative == "." || relative.is_empty() {
                    root.to_path_buf()
                } else {
                    root.join(&relative)
                };
                let effective_source = if relative == "." || relative.is_empty() {
                    source_root.to_path_buf()
                } else {
                    source_root.join(&relative)
                };
                let state_path = extension_hook_state_path(&sync_env.managed_state_home, harness);
                SyncHookPlan::ExtensionDeps(ExtensionDepsHookPlan {
                    harness: harness.clone(),
                    job_root,
                    root: effective_root,
                    source_root: effective_source,
                    relative_root: relative,
                    state_path,
                    timeout_ms: sync_env.install_timeout_ms,
                })
            }
        })
        .collect()
}

fn extension_hook_state_path(managed_state_home: &Path, harness: &Harness) -> PathBuf {
    managed_state_home.join(format!("{}.extension-deps.json", harness.source_name))
}

/// Returns the sorted list of direct child file/dir names in `root`.
#[must_use]
pub fn top_level_entry_names(root: &Path) -> Vec<String> {
    let Ok(entries) = fs::read_dir(root) else {
        return Vec::new();
    };

    let mut names = Vec::new();
    for entry in entries.filter_map(Result::ok) {
        names.push(entry.file_name().to_string_lossy().to_string());
    }
    names.sort();
    names
}

/// Returns whether an entry name represents a safe, non-escaping top-level name.
#[must_use]
pub fn is_safe_managed_entry_name(entry_name: &str) -> bool {
    if entry_name.is_empty()
        || entry_name == "."
        || entry_name == ".."
        || entry_name.contains('/')
        || entry_name.contains('\\')
    {
        return false;
    }

    !Path::new(entry_name).is_absolute()
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn test_is_safe_managed_entry_name() {
        assert!(is_safe_managed_entry_name("config.json"));
        assert!(is_safe_managed_entry_name("skills"));
        assert!(is_safe_managed_entry_name(".hidden"));
        assert!(!is_safe_managed_entry_name(""));
        assert!(!is_safe_managed_entry_name("."));
        assert!(!is_safe_managed_entry_name(".."));
        assert!(!is_safe_managed_entry_name("../escape"));
        assert!(!is_safe_managed_entry_name("/root"));
        assert!(!is_safe_managed_entry_name("sub/dir"));
    }

    #[test]
    fn test_top_level_entry_names_sorted() {
        let temp = match tempdir() {
            Ok(t) => t,
            Err(e) => panic!("tempdir: {e}"),
        };
        if let Err(e) = fs::write(temp.path().join("z.txt"), "z") {
            panic!("write: {e}");
        }
        if let Err(e) = fs::write(temp.path().join("a.txt"), "a") {
            panic!("write: {e}");
        }

        let names = top_level_entry_names(temp.path());
        assert_eq!(names, vec!["a.txt", "z.txt"]);
    }
}
