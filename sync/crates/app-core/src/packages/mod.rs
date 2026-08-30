use crate::runtime::fs::rm_entry;
use std::collections::HashSet;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::Duration;

pub mod process;
pub mod source;
pub mod validate;

pub use process::{
    CommandOutcome, ensure_install_project, install_inferred_import_packages, install_package_deps,
    log_command_failure, pick_bun_runner, run_command_outcome, run_package_build,
};
pub use source::{
    PackageSourceRuntime, clone_package, fnv1a64, github_repo_slug, is_local_path_source,
    package_cache_dir, replace_dir_atomically, source_slug, staging_dir_for,
};
pub use validate::{
    RESOURCE_KEYS, extract_import_specifiers, missing_package_roots, package_has_build_script,
    package_is_healthy, package_root_from_specifier, package_root_is_builtin, package_source_files,
    validate_package_for_tests,
};

/// Errors encountered during package operations.
#[derive(Debug, thiserror::Error)]
pub enum PackageError {
    #[error("I/O error: {0}")]
    Io(#[from] std::io::Error),
    #[error("JSON error: {0}")]
    Json(#[from] serde_json::Error),
    #[error("JSON5 error: {0}")]
    Json5(#[from] json5::Error),
    #[error("Clone failed: {0}")]
    CloneFailed(String),
    #[error("Dependency install failed")]
    DependencyInstallFailed,
    #[error("Build failed")]
    BuildFailed,
    #[error("Inferred packages install failed")]
    InferredInstallFailed,
    #[error("Package resources failed validation")]
    ValidationFailed,
    #[error("Archive error: {0}")]
    Archive(String),
    #[error("Command timed out")]
    TimedOut,
    #[error("Command failed: {0}")]
    CommandFailed(String),
    #[error("Missing command: {0}")]
    MissingCommand(String),
}

/// Parsed package manifest declaring package sources.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize, Default)]
pub struct PackageManifest {
    #[serde(default)]
    pub packages: Vec<String>,
}

/// Target configuration for package bootstrapping.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PackageBootstrapTarget {
    pub manifest_path: PathBuf,
    pub runtime_settings_path: PathBuf,
    pub cache_root: PathBuf,
    pub timeout_ms: u64,
}

/// Reads a package manifest from `packages.json`, deduplicating package source entries.
pub fn read_package_manifest(file_path: impl AsRef<Path>) -> Result<PackageManifest, PackageError> {
    let path = file_path.as_ref();
    if !path.exists() {
        return Ok(PackageManifest {
            packages: Vec::new(),
        });
    }

    let content = fs::read_to_string(path)?;
    let value: serde_json::Value =
        json5::from_str(&content).or_else(|_| serde_json::from_str(&content))?;

    let mut packages = Vec::new();
    let mut seen = HashSet::new();

    if let Some(pkgs) = value.get("packages").and_then(|p| p.as_array()) {
        for pkg in pkgs {
            if let Some(s) = pkg.as_str() {
                let trimmed = s.trim();
                if !trimmed.is_empty() && seen.insert(trimmed.to_owned()) {
                    packages.push(trimmed.to_owned());
                }
            }
        }
    }

    Ok(PackageManifest { packages })
}

/// Patches the `"packages"` field in a runtime settings JSON file.
pub fn patch_runtime_settings(
    file_path: impl AsRef<Path>,
    package_paths: &[impl AsRef<Path>],
) -> Result<(), PackageError> {
    let path = file_path.as_ref();
    let current_content = if path.exists() {
        fs::read_to_string(path)?
    } else {
        "{}".to_owned()
    };

    let mut value: serde_json::Value = json5::from_str(&current_content)
        .or_else(|_| serde_json::from_str(&current_content))
        .unwrap_or_else(|_| serde_json::Value::Object(serde_json::Map::new()));

    if !value.is_object() {
        value = serde_json::Value::Object(serde_json::Map::new());
    }

    let paths_array: Vec<serde_json::Value> = package_paths
        .iter()
        .map(|p| serde_json::Value::String(p.as_ref().to_string_lossy().to_string()))
        .collect();

    if let Some(obj) = value.as_object_mut() {
        obj.insert("packages".to_owned(), serde_json::Value::Array(paths_array));
    }

    if let Some(parent) = path.parent()
        && !parent.as_os_str().is_empty()
        && parent != Path::new(".")
    {
        fs::create_dir_all(parent)?;
    }

    let formatted = serde_json::to_string_pretty(&value)?;
    fs::write(path, format!("{formatted}\n"))?;
    Ok(())
}

/// Ensures that a package source is acquired, dependencies installed, built, and placed in cache.
pub fn ensure_package(
    source: &str,
    cache_root: impl AsRef<Path>,
    timeout_ms: u64,
    runner: Option<&Path>,
    runtime: Option<&PackageSourceRuntime>,
) -> Result<PathBuf, PackageError> {
    let final_dir = package_cache_dir(&cache_root, source);
    if package_is_healthy(&final_dir).unwrap_or(false) {
        return Ok(final_dir);
    }

    fs::create_dir_all(&cache_root)?;

    let staging_dir = staging_dir_for(&final_dir);
    let _ = rm_entry(&staging_dir);
    if let Some(parent) = staging_dir.parent() {
        fs::create_dir_all(parent)?;
    }

    let timeout = Duration::from_millis(timeout_ms);
    let clone_res = clone_package(source, &staging_dir, timeout, runtime);
    if !clone_res.unwrap_or(false) {
        let _ = rm_entry(&staging_dir);
        return Err(PackageError::CloneFailed(format!(
            "clone failed for {source}"
        )));
    }

    if !install_package_deps(&staging_dir, timeout_ms, runner)? {
        let _ = rm_entry(&staging_dir);
        return Err(PackageError::DependencyInstallFailed);
    }

    let mut healthy = package_is_healthy(&staging_dir)?;
    if !healthy && package_has_build_script(&staging_dir)? {
        if !run_package_build(&staging_dir, timeout_ms, runner)? {
            let _ = rm_entry(&staging_dir);
            return Err(PackageError::BuildFailed);
        }
        if !install_inferred_import_packages(&staging_dir, timeout_ms, &staging_dir, runner)? {
            let _ = rm_entry(&staging_dir);
            return Err(PackageError::InferredInstallFailed);
        }
        healthy = package_is_healthy(&staging_dir)?;
    }

    if !healthy {
        let _ = rm_entry(&staging_dir);
        return Err(PackageError::ValidationFailed);
    }

    replace_dir_atomically(&staging_dir, &final_dir)?;
    Ok(final_dir)
}

/// Orchestrates bootstrapping of all declared packages and runtime settings updating.
#[must_use]
pub fn bootstrap_package_target(
    target: &PackageBootstrapTarget,
    runner: Option<&Path>,
    runtime: Option<&PackageSourceRuntime>,
) -> bool {
    let manifest = match read_package_manifest(&target.manifest_path) {
        Ok(m) => m,
        Err(err) => {
            eprintln!("sync: package bootstrap failed: {err}");
            return false;
        }
    };

    let mut installed_paths = Vec::new();
    let mut success = true;

    for source in &manifest.packages {
        match ensure_package(
            source,
            &target.cache_root,
            target.timeout_ms,
            runner,
            runtime,
        ) {
            Ok(path) => installed_paths.push(path),
            Err(err) => {
                eprintln!("sync: package bootstrap failed for {source}: {err}");
                success = false;
            }
        }
    }

    if let Err(err) = patch_runtime_settings(&target.runtime_settings_path, &installed_paths) {
        eprintln!("sync: package settings patch failed: {err}");
        success = false;
    }

    success
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn test_read_package_manifest_dedupes_sources() {
        let dir = tempdir().unwrap();
        let path = dir.path().join("packages.json");
        fs::write(
            &path,
            r#"{
  "packages": [
    "https://github.com/tintinweb/pi-supervisor",
    "https://github.com/tintinweb/pi-supervisor",
    "https://github.com/joelhooks/pi-tools"
  ]
}"#,
        )
        .unwrap();

        let manifest = read_package_manifest(&path).unwrap();
        assert_eq!(manifest.packages.len(), 2);
        assert_eq!(
            manifest.packages,
            vec![
                "https://github.com/tintinweb/pi-supervisor",
                "https://github.com/joelhooks/pi-tools"
            ]
        );
    }

    #[test]
    fn test_patch_runtime_settings_preserves_other_keys() {
        let dir = tempdir().unwrap();
        let path = dir.path().join("settings.json");
        fs::write(
            &path,
            r#"{
  "theme": "dark",
  "defaultModel": "gpt-5.4"
}
"#,
        )
        .unwrap();

        let pkg_path = dir.path().join("pkg");
        patch_runtime_settings(&path, &[&pkg_path]).unwrap();

        let content = fs::read_to_string(&path).unwrap();
        let parsed: serde_json::Value = serde_json::from_str(&content).unwrap();
        assert_eq!(parsed["theme"], "dark");
        assert_eq!(parsed["defaultModel"], "gpt-5.4");
        assert_eq!(
            parsed["packages"],
            serde_json::json!([pkg_path.to_str().unwrap()])
        );
    }
}
