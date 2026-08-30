pub mod cache;
pub mod lock;
pub mod registry;
pub mod runner;
pub mod spec;

use std::collections::BTreeMap;
use std::fs;
use std::io;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Duration;
use thiserror::Error;

pub use cache::{
    CacheError, NpmCacheLayout, current_cached_package, is_executable, npm_cache_layout,
    package_bin_path, prune_versions, update_current_and_previous,
};
pub use lock::{AdvisoryCacheLock, LockError, acquire_cache_lock, try_acquire_cache_lock};
pub use registry::{
    DefaultNpmRegistryResolver, RegistryError, VersionResolver, validate_resolved_version,
};
pub use runner::{
    CommandStdio, DefaultProcessRunner, LauncherProcessResult, ProcessRunner, RunnerError,
};
pub use spec::{
    NpmPackageSpec, SpecValidationError, is_valid_component, is_valid_package_name, validate_spec,
};

pub const DEFAULT_LAUNCH_TIMEOUT: Duration = Duration::from_secs(120);

#[derive(Debug, Error)]
pub enum LauncherError {
    #[error(transparent)]
    SpecValidation(#[from] SpecValidationError),
    #[error(transparent)]
    Cache(#[from] CacheError),
    #[error(transparent)]
    Lock(#[from] LockError),
    #[error(transparent)]
    Registry(#[from] RegistryError),
    #[error(transparent)]
    Runner(#[from] RunnerError),
    #[error("I/O error at {path}: {source}")]
    Io {
        path: PathBuf,
        #[source]
        source: io::Error,
    },
    #[error("cached package identity mismatch: {0}")]
    CachedIdentityMismatch(String),
    #[error("cached package is incomplete: {0}")]
    CachedIncomplete(String),
    #[error("bun install failed: {0}")]
    InstallFailed(String),
    #[error("installed package has no executable bin: {0}")]
    MissingInstalledBin(String),
    #[error("installed package identity mismatch: {0}")]
    InstalledIdentityMismatch(String),
    #[error("installed package smoke check failed: {0}")]
    SmokeCheckFailed(String),
    #[error("current package has no executable bin: {0}")]
    MissingCurrentBin(String),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PreparedNpmPackage {
    pub layout: NpmCacheLayout,
    pub resolved_version: String,
    pub current_bin: PathBuf,
}

#[derive(Default)]
pub struct LauncherRuntime {
    pub resolver: Option<Arc<dyn VersionResolver>>,
    pub runner: Option<Arc<dyn ProcessRunner>>,
}

#[derive(Default)]
pub struct PreparePackageOptions {
    pub home: PathBuf,
    pub cache_home: Option<PathBuf>,
    pub timeout: Option<Duration>,
    pub runtime: LauncherRuntime,
}

fn warn_using_cached_package(spec: &NpmPackageSpec, version: &str, error_msg: &str) {
    let tag = spec.dist_tag.as_deref().unwrap_or("latest");
    eprintln!(
        "sync: warning: latest {}@{} unavailable ({}); using cached {}@{}",
        spec.package, tag, error_msg, spec.tool, version
    );
}

/// Prepares an npm package inside the versioned cache, resolving the latest version,
/// installing in a staging directory, verifying executables and smoke checks, and rotating symlinks.
#[allow(clippy::too_many_lines)]
pub fn prepare_npm_package(
    spec: &NpmPackageSpec,
    options: &PreparePackageOptions,
) -> Result<PreparedNpmPackage, LauncherError> {
    validate_spec(spec)?;
    let timeout = options.timeout.unwrap_or(DEFAULT_LAUNCH_TIMEOUT);
    let layout = npm_cache_layout(
        &options.home,
        &spec.tool,
        &spec.package,
        options.cache_home.as_deref(),
    )?;

    fs::create_dir_all(&layout.versions_dir).map_err(|e| LauncherError::Io {
        path: layout.versions_dir.clone(),
        source: e,
    })?;

    let _lock = acquire_cache_lock(&layout.lock_file, timeout)?;

    let dist_tag = spec.dist_tag.as_deref().unwrap_or("latest");
    let cached = current_cached_package(&layout, spec);

    let resolved_version = {
        let resolve_result = options.runtime.resolver.as_ref().map_or_else(
            || DefaultNpmRegistryResolver.resolve(&spec.package, dist_tag, timeout),
            |resolver| resolver.resolve(&spec.package, dist_tag, timeout),
        );

        match resolve_result {
            Ok(v) => validate_resolved_version(&v)?,
            Err(err) => {
                if let Some((cached_version, current_bin)) = cached {
                    warn_using_cached_package(spec, &cached_version, &err.to_string());
                    return Ok(PreparedNpmPackage {
                        layout,
                        resolved_version: cached_version,
                        current_bin,
                    });
                }
                return Err(LauncherError::Registry(err));
            }
        }
    };

    let version_dir = layout.versions_dir.join(&resolved_version);
    let staged_bin = package_bin_path(&version_dir, &spec.bin);

    let install_and_rotate = || -> Result<PreparedNpmPackage, LauncherError> {
        if is_executable(&staged_bin)
            && !cache::installed_package_matches(&version_dir, &spec.package, &resolved_version)
        {
            return Err(LauncherError::CachedIdentityMismatch(
                resolved_version.clone(),
            ));
        }

        if !is_executable(&staged_bin) {
            if version_dir.exists() {
                return Err(LauncherError::CachedIncomplete(resolved_version.clone()));
            }

            let stage_dir = tempfile::Builder::new()
                .prefix(".stage.")
                .tempdir_in(&layout.versions_dir)
                .map_err(|e| LauncherError::Io {
                    path: layout.versions_dir.clone(),
                    source: e,
                })?;
            let stage_path = stage_dir.path();

            let bun_path = std::env::var("BUN_PATH").unwrap_or_else(|_| String::from("bun"));
            let install_cmd = vec![
                bun_path,
                String::from("install"),
                String::from("--cwd"),
                stage_path.to_string_lossy().into_owned(),
                String::from("--no-save"),
                String::from("--no-progress"),
                String::from("--no-summary"),
                format!("{}@{}", spec.package, resolved_version),
            ];

            let install_res = if let Some(runner) = &options.runtime.runner {
                runner.run(&install_cmd, None, Some(timeout), CommandStdio::Pipe, None)?
            } else {
                DefaultProcessRunner.run(
                    &install_cmd,
                    None,
                    Some(timeout),
                    CommandStdio::Pipe,
                    None,
                )?
            };

            if install_res.timed_out || install_res.exit_code != 0 {
                return Err(LauncherError::InstallFailed(
                    install_res.detail().to_string(),
                ));
            }

            let installed_bin = package_bin_path(stage_path, &spec.bin);
            if !is_executable(&installed_bin) {
                return Err(LauncherError::MissingInstalledBin(spec.bin.clone()));
            }

            if !cache::installed_package_matches(stage_path, &spec.package, &resolved_version) {
                return Err(LauncherError::InstalledIdentityMismatch(format!(
                    "{}@{}",
                    spec.package, resolved_version
                )));
            }

            let smoke_flag = spec.smoke_check.as_deref().unwrap_or("--version");
            if smoke_flag != "-" {
                let smoke_cmd = vec![
                    installed_bin.to_string_lossy().into_owned(),
                    smoke_flag.to_string(),
                ];

                let smoke_res = if let Some(runner) = &options.runtime.runner {
                    runner.run(
                        &smoke_cmd,
                        Some(stage_path),
                        Some(timeout),
                        CommandStdio::Pipe,
                        None,
                    )?
                } else {
                    DefaultProcessRunner.run(
                        &smoke_cmd,
                        Some(stage_path),
                        Some(timeout),
                        CommandStdio::Pipe,
                        None,
                    )?
                };

                if smoke_res.timed_out || smoke_res.exit_code != 0 {
                    return Err(LauncherError::SmokeCheckFailed(
                        smoke_res.detail().to_string(),
                    ));
                }
            }

            fs::rename(stage_path, &version_dir).map_err(|e| LauncherError::Io {
                path: version_dir.clone(),
                source: e,
            })?;
        }

        update_current_and_previous(&layout, &resolved_version)?;
        prune_versions(&layout)?;

        let current_bin = package_bin_path(&layout.current_link, &spec.bin);
        if !is_executable(&current_bin) {
            return Err(LauncherError::MissingCurrentBin(spec.bin.clone()));
        }

        Ok(PreparedNpmPackage {
            layout: layout.clone(),
            resolved_version: resolved_version.clone(),
            current_bin,
        })
    };

    match install_and_rotate() {
        Ok(prepared) => Ok(prepared),
        Err(err) => {
            if let Some((fallback_version, current_bin)) = current_cached_package(&layout, spec) {
                warn_using_cached_package(spec, &fallback_version, &err.to_string());
                return Ok(PreparedNpmPackage {
                    layout,
                    resolved_version: fallback_version,
                    current_bin,
                });
            }
            Err(err)
        }
    }
}

/// Prepares and launches an npm package binary with specified arguments and merged environment variables.
pub fn launch_npm_package(
    home: &Path,
    install_timeout: Option<Duration>,
    spec: &NpmPackageSpec,
    args: &[String],
    runtime: &LauncherRuntime,
) -> Result<i32, LauncherError> {
    let options = PreparePackageOptions {
        home: home.to_path_buf(),
        cache_home: None,
        timeout: install_timeout,
        runtime: LauncherRuntime {
            resolver: runtime.resolver.clone(),
            runner: runtime.runner.clone(),
        },
    };

    let prepared = prepare_npm_package(spec, &options)?;

    let mut cmd = vec![prepared.current_bin.to_string_lossy().into_owned()];
    cmd.extend_from_slice(args);

    let result = if let Some(runner) = &runtime.runner {
        runner.run(&cmd, None, None, CommandStdio::Inherit, spec.env.as_ref())?
    } else {
        DefaultProcessRunner.run(&cmd, None, None, CommandStdio::Inherit, spec.env.as_ref())?
    };

    if result.timed_out {
        eprintln!("sync: {} launch timed out", spec.tool);
        return Ok(124);
    }

    Ok(result.exit_code)
}

/// Launches a harness binary, merging root and adapter environments.
#[allow(clippy::too_many_arguments)]
pub fn launch_harness(
    home: &Path,
    install_timeout: Option<Duration>,
    source_name: &str,
    package: &str,
    bin: &str,
    dist_tag: Option<&str>,
    smoke_check: Option<&str>,
    harness_env: Option<&BTreeMap<String, String>>,
    root_env: Option<&BTreeMap<String, String>>,
    args: &[String],
    runtime: &LauncherRuntime,
) -> Result<i32, LauncherError> {
    let mut merged_env = BTreeMap::new();

    if let Some(root) = root_env {
        for (k, v) in root {
            if std::env::var_os(k).is_none() {
                merged_env.insert(k.clone(), v.clone());
            }
        }
    }

    if let Some(harness) = harness_env {
        for (k, v) in harness {
            merged_env.insert(k.clone(), v.clone());
        }
    }

    let spec_env = if merged_env.is_empty() {
        None
    } else {
        Some(merged_env)
    };

    let spec = NpmPackageSpec {
        tool: source_name.to_string(),
        package: package.to_string(),
        bin: bin.to_string(),
        dist_tag: dist_tag.map(ToString::to_string),
        smoke_check: smoke_check.map(ToString::to_string),
        env: spec_env,
    };

    launch_npm_package(home, install_timeout, &spec, args, runtime)
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
    use std::sync::Mutex;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use tempfile::tempdir;

    struct MockResolver {
        version: Mutex<Result<String, String>>,
    }

    impl VersionResolver for MockResolver {
        fn resolve(
            &self,
            _package: &str,
            _dist_tag: &str,
            _timeout: Duration,
        ) -> Result<String, RegistryError> {
            self.version.lock().map_or_else(
                |_| Err(RegistryError::Request(String::from("lock poisoned"))),
                |res| match &*res {
                    Ok(v) => Ok(v.clone()),
                    Err(e) => Err(RegistryError::Request(e.clone())),
                },
            )
        }
    }

    struct MockRunner {
        calls: Mutex<Vec<Vec<String>>>,
        install_fails: Mutex<bool>,
        smoke_fails: Mutex<bool>,
        install_count: AtomicUsize,
    }

    impl ProcessRunner for MockRunner {
        fn run(
            &self,
            command: &[String],
            _cwd: Option<&Path>,
            _timeout: Option<Duration>,
            _stdio: CommandStdio,
            _env: Option<&BTreeMap<String, String>>,
        ) -> Result<LauncherProcessResult, RunnerError> {
            if let Ok(mut calls) = self.calls.lock() {
                calls.push(command.to_vec());
            }

            if let Some(cmd_name) = command.first() {
                if cmd_name == "bun" || cmd_name.ends_with("/bun") {
                    self.install_count.fetch_add(1, Ordering::SeqCst);
                    let should_fail = self.install_fails.lock().is_ok_and(|g| *g);
                    if should_fail {
                        return Ok(LauncherProcessResult::failure(
                            1,
                            String::from("install failed"),
                        ));
                    }
                    // Emulate bun install: create node_modules/.bin/{bin} and package.json
                    let stage_dir = Path::new(&command[3]);
                    let pkg_arg = command.last().unwrap();
                    let (pkg_name, pkg_version) = pkg_arg.rsplit_once('@').unwrap();

                    let bin_dir = stage_dir.join("node_modules").join(".bin");
                    fs::create_dir_all(&bin_dir).unwrap();
                    let exec_file = bin_dir.join("demo");
                    fs::write(&exec_file, "#!/bin/sh\nexit 0\n").unwrap();
                    #[cfg(unix)]
                    {
                        use std::os::unix::fs::PermissionsExt;
                        let _ = fs::set_permissions(&exec_file, fs::Permissions::from_mode(0o755));
                    }

                    let mut pkg_dir = stage_dir.join("node_modules");
                    for seg in pkg_name.split('/') {
                        pkg_dir.push(seg);
                    }
                    fs::create_dir_all(&pkg_dir).unwrap();
                    fs::write(
                        pkg_dir.join("package.json"),
                        format!(r#"{{"name":"{pkg_name}","version":"{pkg_version}"}}"#),
                    )
                    .unwrap();

                    return Ok(LauncherProcessResult::success(String::new()));
                }

                if command.iter().any(|c| c == "--version") {
                    let should_fail = self.smoke_fails.lock().is_ok_and(|g| *g);
                    if should_fail {
                        return Ok(LauncherProcessResult::failure(
                            1,
                            String::from("smoke check failed"),
                        ));
                    }
                    return Ok(LauncherProcessResult::success(String::from("1.0.0")));
                }
            }

            Ok(LauncherProcessResult::success(String::new()))
        }
    }

    #[test]
    fn test_npm_launcher_resolves_latest_and_caches_current_previous() {
        let tmp = tempdir().unwrap();
        let home = tmp.path().join("home");
        let cache_home = tmp.path().join("cache");
        fs::create_dir_all(&home).unwrap();

        let resolver = Arc::new(MockResolver {
            version: Mutex::new(Ok(String::from("1.2.3"))),
        });
        let runner = Arc::new(MockRunner {
            calls: Mutex::new(Vec::new()),
            install_fails: Mutex::new(false),
            smoke_fails: Mutex::new(false),
            install_count: AtomicUsize::new(0),
        });

        let runtime = LauncherRuntime {
            resolver: Some(resolver),
            runner: Some(runner.clone()),
        };

        let spec = NpmPackageSpec {
            tool: String::from("demo"),
            package: String::from("demo-package"),
            bin: String::from("demo"),
            dist_tag: Some(String::from("latest")),
            smoke_check: Some(String::from("--version")),
            env: None,
        };

        let options = PreparePackageOptions {
            home,
            cache_home: Some(cache_home),
            timeout: Some(Duration::from_secs(2)),
            runtime,
        };

        // First install
        let prepared1 = prepare_npm_package(&spec, &options).unwrap();
        assert_eq!(prepared1.resolved_version, "1.2.3");
        assert!(prepared1.current_bin.exists());
        assert_eq!(runner.install_count.load(Ordering::SeqCst), 1);

        // Second run: cached, skips install
        let prepared2 = prepare_npm_package(&spec, &options).unwrap();
        assert_eq!(prepared2.resolved_version, "1.2.3");
        assert_eq!(prepared2.current_bin, prepared1.current_bin);
        assert_eq!(runner.install_count.load(Ordering::SeqCst), 1);
    }

    #[test]
    fn test_npm_launcher_rotates_previous_and_falls_back_to_last_known_good() {
        let tmp = tempdir().unwrap();
        let home = tmp.path().join("home");
        let cache_home = tmp.path().join("cache");
        fs::create_dir_all(&home).unwrap();

        let resolver = Arc::new(MockResolver {
            version: Mutex::new(Ok(String::from("1.0.0"))),
        });
        let runner = Arc::new(MockRunner {
            calls: Mutex::new(Vec::new()),
            install_fails: Mutex::new(false),
            smoke_fails: Mutex::new(false),
            install_count: AtomicUsize::new(0),
        });

        let runtime = LauncherRuntime {
            resolver: Some(resolver.clone()),
            runner: Some(runner.clone()),
        };

        let spec = NpmPackageSpec {
            tool: String::from("demo"),
            package: String::from("demo-package"),
            bin: String::from("demo"),
            dist_tag: None,
            smoke_check: None,
            env: None,
        };

        let options = PreparePackageOptions {
            home,
            cache_home: Some(cache_home),
            timeout: Some(Duration::from_secs(2)),
            runtime,
        };

        // Install 1.0.0
        let p1 = prepare_npm_package(&spec, &options).unwrap();
        assert_eq!(p1.resolved_version, "1.0.0");

        // Install 2.0.0
        *resolver.version.lock().unwrap() = Ok(String::from("2.0.0"));
        let p2 = prepare_npm_package(&spec, &options).unwrap();
        assert_eq!(p2.resolved_version, "2.0.0");

        // Offline resolution: falls back to 2.0.0
        *resolver.version.lock().unwrap() = Err(String::from("network offline"));
        let p_offline = prepare_npm_package(&spec, &options).unwrap();
        assert_eq!(p_offline.resolved_version, "2.0.0");

        // Install failure for 3.0.0: falls back to 2.0.0
        *resolver.version.lock().unwrap() = Ok(String::from("3.0.0"));
        *runner.install_fails.lock().unwrap() = true;
        let p_failed_install = prepare_npm_package(&spec, &options).unwrap();
        assert_eq!(p_failed_install.resolved_version, "2.0.0");

        // Smoke check failure for 4.0.0: falls back to 2.0.0
        *resolver.version.lock().unwrap() = Ok(String::from("4.0.0"));
        *runner.install_fails.lock().unwrap() = false;
        *runner.smoke_fails.lock().unwrap() = true;
        let p_failed_smoke = prepare_npm_package(&spec, &options).unwrap();
        assert_eq!(p_failed_smoke.resolved_version, "2.0.0");
    }

    #[test]
    fn test_first_ever_resolution_failure_errors() {
        let tmp = tempdir().unwrap();
        let home = tmp.path().join("home");

        let resolver = Arc::new(MockResolver {
            version: Mutex::new(Err(String::from("network unavailable"))),
        });

        let runtime = LauncherRuntime {
            resolver: Some(resolver),
            runner: None,
        };

        let spec = NpmPackageSpec {
            tool: String::from("demo"),
            package: String::from("demo-package"),
            bin: String::from("demo"),
            dist_tag: None,
            smoke_check: None,
            env: None,
        };

        let options = PreparePackageOptions {
            home,
            cache_home: None,
            timeout: Some(Duration::from_secs(1)),
            runtime,
        };

        let res = prepare_npm_package(&spec, &options);
        assert!(res.is_err());
    }
}
