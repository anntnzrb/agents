use std::collections::{BTreeMap, HashMap};
use std::path::PathBuf;
use std::time::Duration;

use crate::extensions::install_extension_deps;
use crate::harness::{SyncEnv, supported_harness};
use crate::hook_state::{
    PreparedExtensionHookState, clear_extension_hook_state, prepare_extension_hook_state,
    record_extension_hook_state,
};
use crate::jobs::{JobRunOptions, run_jobs_with_preserve};
use crate::launcher::spec::NpmPackageSpec;
use crate::launcher::{LauncherRuntime, launch_harness, launch_npm_package};
use crate::managed_state::{
    clean_managed_entries, plan_managed_entries_for_sync_plan, record_managed_entries,
};
use crate::managed_tools::{ManagedToolRuntime, is_cli_proxy_running, prepare_managed_tools};
use crate::packages::{PackageBootstrapTarget, bootstrap_package_target};
use crate::plan::{ExtensionDepsHookPlan, SyncHookPlan, build_sync_plan};
use crate::runtime::errors::{panic_message, warn};
use crate::runtime::lock::{LockError, SyncLock, try_acquire_sync_lock as try_acquire_lock};
use crate::tool_launchers::tool_launcher;
use crate::wrappers::{WrapperDestination, managed_tool_wrapper_destination, reconcile_wrappers};

pub const SYNC_LOCK_FILE: &str = "sync.lock";
pub const DEFAULT_SYNC_TIMEOUT_SECONDS: u64 = 15 * 60;

/// Options controlling sync execution behavior.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct SyncOptions {
    pub warn_managed_services: bool,
    pub force_model_refresh: bool,
}

/// Resolves the absolute lock file path for a given `SyncEnv`.
#[must_use]
pub fn sync_lock_path(sync_env: &SyncEnv) -> PathBuf {
    sync_env.managed_state_home.join(SYNC_LOCK_FILE)
}

/// Attempts to acquire an exclusive, non-blocking sync lock.
pub fn try_acquire_sync_lock(sync_env: &SyncEnv) -> Result<Option<SyncLock>, LockError> {
    try_acquire_lock(&sync_env.managed_state_home, sync_lock_path(sync_env))
}

#[derive(Debug, Clone)]
struct ExtensionHookRuntimeState {
    hook: ExtensionDepsHookPlan,
    state: PreparedExtensionHookState,
}

fn prepare_extension_hook_states(
    hooks: &[SyncHookPlan],
) -> HashMap<PathBuf, ExtensionHookRuntimeState> {
    let mut states = HashMap::new();
    for hook in hooks {
        if let SyncHookPlan::ExtensionDeps(deps_hook) = hook {
            let state = prepare_extension_hook_state(deps_hook);
            states.insert(
                deps_hook.state_path.clone(),
                ExtensionHookRuntimeState {
                    hook: deps_hook.clone(),
                    state,
                },
            );
        }
    }
    states
}

fn preserve_paths_by_dst(
    states: &HashMap<PathBuf, ExtensionHookRuntimeState>,
) -> HashMap<PathBuf, Vec<String>> {
    let mut preserve_by_dst: HashMap<PathBuf, Vec<String>> = HashMap::new();
    for runtime_state in states.values() {
        if !runtime_state.state.should_skip || runtime_state.state.preserve_paths.is_empty() {
            continue;
        }
        let list = preserve_by_dst
            .entry(runtime_state.hook.job_root.clone())
            .or_default();
        list.extend(runtime_state.state.preserve_paths.clone());
        list.sort();
        list.dedup();
    }
    preserve_by_dst
}

fn run_sync_hooks(
    hooks: &[SyncHookPlan],
    extension_hook_states: &HashMap<PathBuf, ExtensionHookRuntimeState>,
) -> bool {
    let mut success = true;
    for hook in hooks {
        let state = match hook {
            SyncHookPlan::ExtensionDeps(deps) => extension_hook_states
                .get(&deps.state_path)
                .map(|r| &r.state),
            SyncHookPlan::PackageBootstrap(_) => None,
        };
        if !run_sync_hook(hook, state) {
            success = false;
        }
    }
    success
}

fn run_sync_hook(
    hook: &SyncHookPlan,
    extension_hook_state: Option<&PreparedExtensionHookState>,
) -> bool {
    match hook {
        SyncHookPlan::PackageBootstrap(bootstrap_hook) => {
            let target = PackageBootstrapTarget {
                manifest_path: bootstrap_hook.manifest_path.clone(),
                runtime_settings_path: bootstrap_hook.runtime_settings_path.clone(),
                cache_root: bootstrap_hook.cache_root.clone(),
                timeout_ms: bootstrap_hook.timeout_ms,
            };
            bootstrap_package_target(&target, None, None)
        }
        SyncHookPlan::ExtensionDeps(deps_hook) => {
            if let Some(state) = extension_hook_state
                && state.should_skip
            {
                if state.should_refresh_state {
                    let _ = record_extension_hook_state(deps_hook, state);
                }
                return true;
            }
            match install_extension_deps(
                &deps_hook.root,
                &deps_hook.source_root,
                deps_hook.timeout_ms,
                None,
            ) {
                Ok(true) => {
                    let prepared = extension_hook_state
                        .cloned()
                        .unwrap_or_else(|| prepare_extension_hook_state(deps_hook));
                    let _ = record_extension_hook_state(deps_hook, &prepared);
                    true
                }
                Ok(false) => {
                    clear_extension_hook_state(&deps_hook.state_path);
                    false
                }
                Err(e) => {
                    clear_extension_hook_state(&deps_hook.state_path);
                    eprintln!("sync: error: {}", panic_message(&e));
                    false
                }
            }
        }
    }
}

/// Executes full end-to-end synchronization for a given `SyncEnv`.
pub async fn run_sync(sync_env: &SyncEnv, options: &SyncOptions) -> bool {
    let sync_plan = match build_sync_plan(sync_env) {
        Ok(p) => p,
        Err(e) => {
            eprintln!("sync: error: {}", panic_message(&e));
            return false;
        }
    };

    let managed_plan = plan_managed_entries_for_sync_plan(&sync_plan);
    let extension_hook_states = prepare_extension_hook_states(&sync_plan.hooks);

    let cleanup_success = clean_managed_entries(&managed_plan);
    let base_success = if cleanup_success {
        let job_options = JobRunOptions {
            force_model_refresh: Some(options.force_model_refresh),
            quiet_model_refresh: Some(!options.warn_managed_services),
        };
        let preserve_paths = preserve_paths_by_dst(&extension_hook_states);
        run_jobs_with_preserve(&sync_plan.jobs, &preserve_paths, &job_options)
    } else {
        false
    };

    let mut managed_tools = Vec::new();
    let mut managed_tool_success = base_success;
    if base_success && sync_plan.gateway_host {
        let runtime = ManagedToolRuntime::default();
        let timeout = Duration::from_millis(sync_env.install_timeout_ms);
        match prepare_managed_tools(
            &sync_env.home,
            &sync_env.ssot_home,
            sync_env.platform.as_str(),
            timeout,
            &runtime,
        ) {
            Ok(tools) => {
                managed_tools = tools;
            }
            Err(e) => {
                eprintln!("sync: error: {}", panic_message(&e));
                managed_tool_success = false;
            }
        }
    }

    let additional_destinations: Vec<WrapperDestination> = managed_tools
        .iter()
        .map(|tool| {
            managed_tool_wrapper_destination(
                &sync_env.home,
                &tool.command,
                &tool.executable,
                &tool.config_path,
            )
        })
        .collect();

    let wrapper_success = if managed_tool_success {
        reconcile_wrappers(sync_env, &additional_destinations)
    } else {
        false
    };

    let managed_state_success = if base_success && wrapper_success {
        record_managed_entries(&managed_plan)
    } else {
        true
    };

    let hook_success = if base_success && wrapper_success && managed_state_success {
        run_sync_hooks(&sync_plan.hooks, &extension_hook_states)
    } else {
        true
    };

    let success = base_success
        && managed_tool_success
        && wrapper_success
        && managed_state_success
        && hook_success;

    if success
        && options.warn_managed_services
        && managed_tools.iter().any(|t| t.name == "cliproxyapi")
        && !is_cli_proxy_running(
            &sync_plan.cli_proxy_deployment.client.base_url,
            Duration::from_millis(500),
        )
    {
        eprintln!(
            "sync: warning: CLIProxyAPI is installed but not running; start it with: cli-proxy-api"
        );
    }

    success
}

/// Primary entrypoint for the `agentium sync` CLI command.
pub async fn sync_main(options: &SyncOptions) -> i32 {
    let sync_env = match SyncEnv::from_system() {
        Ok(env) => env,
        Err(e) => {
            eprintln!("sync: error: {}", panic_message(&e));
            return 1;
        }
    };

    sync_main_with_env(&sync_env, options).await
}

/// Synchronizes with an explicitly provided `SyncEnv`.
pub async fn sync_main_with_env(sync_env: &SyncEnv, options: &SyncOptions) -> i32 {
    let lock = match try_acquire_sync_lock(sync_env) {
        Ok(Some(lock)) => lock,
        Ok(None) => {
            eprintln!("sync: another sync is already running; skipping");
            return 0;
        }
        Err(e) => {
            eprintln!("sync: error: {}", panic_message(&e));
            return 1;
        }
    };

    let mut opts = options.clone();
    opts.warn_managed_services = true;

    let success = run_sync(sync_env, &opts).await;
    lock.release();

    i32::from(!success)
}

/// Primary entrypoint for the `agentium launch` CLI command.
pub async fn launch_main(source_name: &str, args: &[String]) -> i32 {
    let sync_env = match SyncEnv::from_system() {
        Ok(env) => env,
        Err(e) => {
            eprintln!("sync: error: {}", panic_message(&e));
            return 1;
        }
    };

    launch_main_with_env(&sync_env, source_name, args, &LauncherRuntime::default()).await
}

/// Launches a target harness or tool with an explicitly provided `SyncEnv`.
pub async fn launch_main_with_env(
    sync_env: &SyncEnv,
    source_name: &str,
    args: &[String],
    runtime: &LauncherRuntime,
) -> i32 {
    let ssot_available = sync_env.ssot_home.exists();
    let harness = sync_env
        .harnesses
        .iter()
        .find(|candidate| candidate.source_name == source_name)
        .cloned()
        .or_else(|| {
            if ssot_available {
                None
            } else {
                supported_harness(&sync_env.home, source_name, sync_env.platform)
            }
        });

    let tool = if harness.is_some() {
        None
    } else {
        tool_launcher(source_name)
    };

    if harness.is_none() && tool.is_none() {
        eprintln!("sync: error: unsupported launch target: {source_name}");
        return 2;
    }

    if ssot_available {
        match try_acquire_sync_lock(sync_env) {
            Ok(Some(lock)) => {
                let success = run_sync(sync_env, &SyncOptions::default()).await;
                if !success {
                    warn("continuing launch without completed sync");
                }
                lock.release();
            }
            Ok(None) => {
                warn("another sync is already running; continuing launch");
            }
            Err(e) => {
                warn(format!(
                    "sync before launch unavailable: {}",
                    panic_message(&e)
                ));
            }
        }
    } else {
        warn("agent configuration source is unavailable; continuing with registry package");
    }

    tool.map_or_else(
        || {
            if let Some(harness_spec) = harness {
                let harness_env: Option<BTreeMap<String, String>> =
                    if harness_spec.launcher.env.is_empty() {
                        None
                    } else {
                        Some(harness_spec.launcher.env.into_iter().collect())
                    };
                match launch_harness(
                    &sync_env.home,
                    None,
                    &harness_spec.source_name,
                    &harness_spec.launcher.package,
                    &harness_spec.launcher.bin,
                    Some(&harness_spec.launcher.dist_tag),
                    Some(&harness_spec.launcher.smoke_check),
                    harness_env.as_ref(),
                    Some(&sync_env.root_env),
                    args,
                    runtime,
                ) {
                    Ok(exit_code) => exit_code,
                    Err(e) => {
                        eprintln!("sync: error: launch failed: {}", panic_message(&e));
                        1
                    }
                }
            } else {
                eprintln!("sync: error: unreachable: launch target checked above");
                1
            }
        },
        |tool_spec| {
            let spec = NpmPackageSpec {
                tool: tool_spec.id.to_string(),
                package: tool_spec.package.to_string(),
                bin: tool_spec.bin.to_string(),
                dist_tag: tool_spec.dist_tag.map(ToString::to_string),
                smoke_check: tool_spec.smoke_check.map(ToString::to_string),
                env: None,
            };
            match launch_npm_package(&sync_env.home, None, &spec, args, runtime) {
                Ok(exit_code) => exit_code,
                Err(e) => {
                    eprintln!("sync: error: launch failed: {}", panic_message(&e));
                    1
                }
            }
        },
    )
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
    use crate::launcher::runner::{CommandStdio, ProcessRunner, RunnerError};
    use crate::launcher::{LauncherProcessResult, RegistryError, VersionResolver};
    use std::fs;
    use std::path::Path;
    use std::sync::Arc;
    use tempfile::tempdir;
    #[allow(dead_code)]
    struct MockProcessRunner {
        expected_bin: String,
        exit_code: i32,
    }

    impl ProcessRunner for MockProcessRunner {
        fn run(
            &self,
            command: &[String],
            _cwd: Option<&Path>,
            _timeout: Option<Duration>,
            _stdio: CommandStdio,
            _env: Option<&BTreeMap<String, String>>,
        ) -> Result<LauncherProcessResult, RunnerError> {
            if command
                .first()
                .is_some_and(|cmd| cmd == "bun" || cmd.ends_with("/bun"))
            {
                let Some(stage_dir) = command.get(3).map(Path::new) else {
                    return Ok(LauncherProcessResult::failure(
                        self.exit_code,
                        "missing install directory".to_string(),
                    ));
                };
                let Some(pkg_arg) = command.last() else {
                    return Ok(LauncherProcessResult::failure(
                        self.exit_code,
                        "missing package argument".to_string(),
                    ));
                };
                let Some((pkg_name, pkg_version)) = pkg_arg.rsplit_once('@') else {
                    return Ok(LauncherProcessResult::failure(
                        self.exit_code,
                        "invalid package argument".to_string(),
                    ));
                };

                let bin_dir = stage_dir.join("node_modules").join(".bin");
                fs::create_dir_all(&bin_dir).unwrap();
                let exec_file = bin_dir.join(&self.expected_bin);
                fs::write(&exec_file, "#!/bin/sh\nexit 0\n").unwrap();
                #[cfg(unix)]
                {
                    use std::os::unix::fs::PermissionsExt;
                    fs::set_permissions(&exec_file, fs::Permissions::from_mode(0o755)).unwrap();
                }

                let mut pkg_dir = stage_dir.join("node_modules");
                for segment in pkg_name.split('/') {
                    pkg_dir.push(segment);
                }
                fs::create_dir_all(&pkg_dir).unwrap();
                fs::write(
                    pkg_dir.join("package.json"),
                    format!(r#"{{"name":"{pkg_name}","version":"{pkg_version}"}}"#),
                )
                .unwrap();
                return Ok(LauncherProcessResult::success(String::new()));
            }

            let bin = command.first().cloned().unwrap_or_default();
            if bin.ends_with(&self.expected_bin) || bin.contains(&self.expected_bin) {
                Ok(LauncherProcessResult::success(String::new()))
            } else {
                Ok(LauncherProcessResult::failure(
                    self.exit_code,
                    String::new(),
                ))
            }
        }
    }

    struct FixedVersionResolver {
        version: String,
    }

    impl VersionResolver for FixedVersionResolver {
        fn resolve(
            &self,
            _package_name: &str,
            _dist_tag: &str,
            _timeout: Duration,
        ) -> Result<String, RegistryError> {
            Ok(self.version.clone())
        }
    }

    struct FailingVersionResolver;

    impl VersionResolver for FailingVersionResolver {
        fn resolve(
            &self,
            _package_name: &str,
            _dist_tag: &str,
            _timeout: Duration,
        ) -> Result<String, RegistryError> {
            Err(RegistryError::Request(
                "simulated network failure".to_string(),
            ))
        }
    }

    #[tokio::test]
    async fn test_sync_lock_contention_returns_zero() {
        let temp = tempdir().unwrap();
        let home = temp.path().to_path_buf();
        let ssot = home.join(".config").join("agents");
        fs::create_dir_all(&ssot).unwrap();

        // Write minimal deployment.json so build_sync_plan succeeds
        let cliproxy_dir = ssot.join("tools").join("cliproxyapi");
        fs::create_dir_all(&cliproxy_dir).unwrap();
        fs::write(
            cliproxy_dir.join("deployment.json"),
            r#"{
  "server": { "hostname": "localhost" },
  "listen": { "host": "127.0.0.1", "port": 8080 },
  "client": { "baseUrl": "http://127.0.0.1:8080/v1" }
}"#,
        )
        .unwrap();

        let sync_env = SyncEnv::from_home(home.clone(), 60_000, None).unwrap();

        // Pre-acquire lock
        let lock = try_acquire_sync_lock(&sync_env).unwrap();
        assert!(lock.is_some());

        // Second acquisition attempt during sync_main_with_env should cleanly report 0
        let exit_code = sync_main_with_env(&sync_env, &SyncOptions::default()).await;
        assert_eq!(exit_code, 0);

        drop(lock);
    }

    #[tokio::test]
    async fn test_sync_runs_on_temp_home_cleanly() {
        let temp = tempdir().unwrap();
        let home = temp.path().to_path_buf();
        let ssot = home.join(".config").join("agents");
        fs::create_dir_all(&ssot).unwrap();

        let cliproxy_dir = ssot.join("tools").join("cliproxyapi");
        fs::create_dir_all(&cliproxy_dir).unwrap();
        fs::write(
            cliproxy_dir.join("deployment.json"),
            r#"{
  "server": { "hostname": "localhost" },
  "listen": { "host": "127.0.0.1", "port": 8080 },
  "client": { "baseUrl": "http://127.0.0.1:8080/v1" }
}"#,
        )
        .unwrap();

        let sync_env = SyncEnv::from_home(home.clone(), 60_000, None).unwrap();
        let exit_code = sync_main_with_env(&sync_env, &SyncOptions::default()).await;
        assert_eq!(exit_code, 0);

        // Verify wrappers directory was reconciled
        let wrapper_dir = home.join(".local").join("bin");
        assert!(wrapper_dir.exists());
    }

    #[tokio::test]
    async fn test_launch_unsupported_target_returns_two() {
        let temp = tempdir().unwrap();
        let home = temp.path().to_path_buf();
        let sync_env = SyncEnv::from_home(home, 60_000, None).unwrap();

        let exit_code = launch_main_with_env(
            &sync_env,
            "nonexistent-agent",
            &[],
            &LauncherRuntime::default(),
        )
        .await;
        assert_eq!(exit_code, 2);
    }

    #[tokio::test]
    async fn test_launch_reconciles_ssot_wrappers_before_launch() {
        let temp = tempdir().unwrap();
        let home = temp.path().to_path_buf();
        let ssot = home.join(".config").join("agents");
        fs::create_dir_all(&ssot).unwrap();

        let cliproxy_dir = ssot.join("tools").join("cliproxyapi");
        fs::create_dir_all(&cliproxy_dir).unwrap();
        fs::write(
            cliproxy_dir.join("deployment.json"),
            r#"{
  "server": { "hostname": "localhost" },
  "listen": { "host": "127.0.0.1", "port": 8080 },
  "client": { "baseUrl": "http://127.0.0.1:8080/v1" }
}"#,
        )
        .unwrap();

        let codex_harness_dir = ssot.join("harnesses").join("codex");
        fs::create_dir_all(&codex_harness_dir).unwrap();

        let sync_env = SyncEnv::from_home(home.clone(), 60_000, None).unwrap();
        assert!(sync_env.harness("codex").is_some());

        let runtime = LauncherRuntime {
            resolver: Some(Arc::new(FailingVersionResolver)),
            runner: None,
        };

        let exit_code = launch_main_with_env(&sync_env, "codex", &[], &runtime).await;
        assert_eq!(exit_code, 1);

        let wrapper_path = home.join(".local").join("bin").join("codex");
        assert!(
            wrapper_path.exists(),
            "pre-launch synchronization must reconcile wrappers before launching"
        );
    }
    #[tokio::test]
    async fn test_launch_executes_prepared_harness() {
        let temp = tempdir().unwrap();
        let home = temp.path().to_path_buf();
        let ssot = home.join(".config").join("agents");
        fs::create_dir_all(&ssot).unwrap();

        let cliproxy_dir = ssot.join("tools").join("cliproxyapi");
        fs::create_dir_all(&cliproxy_dir).unwrap();
        fs::write(
            cliproxy_dir.join("deployment.json"),
            r#"{
  "server": { "hostname": "localhost" },
  "listen": { "host": "127.0.0.1", "port": 8080 },
  "client": { "baseUrl": "http://127.0.0.1:8080/v1" }
}"#,
        )
        .unwrap();

        let codex_harness_dir = ssot.join("harnesses").join("codex");
        fs::create_dir_all(&codex_harness_dir).unwrap();

        let sync_env = SyncEnv::from_home(home, 60_000, None).unwrap();
        let runtime = LauncherRuntime {
            resolver: Some(Arc::new(FixedVersionResolver {
                version: "1.0.0".to_string(),
            })),
            runner: Some(Arc::new(MockProcessRunner {
                expected_bin: "codex".to_string(),
                exit_code: 1,
            })),
        };

        let exit_code = launch_main_with_env(&sync_env, "codex", &[], &runtime).await;
        assert_eq!(exit_code, 0);
    }
}
