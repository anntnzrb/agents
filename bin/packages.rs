use std::collections::HashSet;
use std::fs;
use std::io;
use std::path::{Path, PathBuf};
use std::time::Duration;

use serde_json::{Map, Value};

use super::{HarnessId, SyncEnv, err};

mod process;
mod source;
mod validate;

use process::{
    install_inferred_import_packages as install_inferred_import_packages_impl,
    install_package_deps, run_package_build,
};
#[cfg(test)]
use source::{
    clone_attempts_for_tests as clone_attempts_for_tests_impl,
    command_for_tests as command_for_tests_impl,
    github_slug_for_tests as github_slug_for_tests_impl,
};
use source::{
    clone_package, package_cache_dir as package_cache_dir_impl, replace_dir_atomically,
    staging_dir_for,
};
#[cfg(test)]
use validate::validate_package_for_tests as validate_package_for_tests_impl;
use validate::{package_has_build_script, package_is_healthy};

const PACKAGE_SOURCE_FILE: &str = "packages.json";
const PACKAGE_CACHE_SUBDIR: &str = ".local/share/agents/pi-packages";
const RESOURCE_KEYS: [&str; 4] = ["extensions", "skills", "prompts", "themes"];

#[derive(Clone, Debug, PartialEq, Eq)]
pub(super) struct PackageManifest {
    pub(super) packages: Vec<String>,
}

pub(super) fn install_inferred_import_packages(dir: &Path, timeout: Duration) -> bool {
    install_inferred_import_packages_impl(dir, timeout)
}

pub(super) fn package_cache_dir(cache_root: &Path, source: &str) -> PathBuf {
    package_cache_dir_impl(cache_root, source)
}

#[cfg(test)]
pub(super) fn github_slug_for_tests(source: &str) -> Option<String> {
    github_slug_for_tests_impl(source)
}

#[cfg(test)]
pub(super) fn command_for_tests(source: &str, target_dir: &Path) -> Vec<String> {
    command_for_tests_impl(source, target_dir)
}

#[cfg(test)]
pub(super) fn clone_attempts_for_tests(
    source: &str,
    target_dir: &Path,
    gh_available: bool,
    outcomes: &[bool],
) -> (bool, Vec<Vec<String>>) {
    clone_attempts_for_tests_impl(source, target_dir, gh_available, outcomes)
}

#[cfg(test)]
pub(super) fn validate_package_for_tests(dir: &Path) -> Result<bool, String> {
    validate_package_for_tests_impl(dir)
}

pub(super) fn bootstrap_packages(sync_env: &SyncEnv) -> bool {
    let manifest_path = sync_env
        .harness(HarnessId::Pi)
        .map(|harness| {
            harness
                .source_root(&sync_env.tools_home)
                .join(PACKAGE_SOURCE_FILE)
        })
        .unwrap_or_else(|| {
            sync_env
                .tools_home
                .join("pi")
                .join("agent")
                .join(PACKAGE_SOURCE_FILE)
        });
    let manifest = match read_package_manifest(&manifest_path) {
        Ok(manifest) => manifest,
        Err(message) => {
            err(&format!("package bootstrap failed: {message}"));
            return false;
        }
    };

    let runtime_settings_path = sync_env
        .harness(HarnessId::Pi)
        .map(|harness| harness.root().join("settings.json"))
        .unwrap_or_else(|| {
            sync_env
                .tools_home
                .join("pi")
                .join("agent")
                .join("settings.json")
        });
    let cache_root = sync_env.home.join(PACKAGE_CACHE_SUBDIR);

    let mut installed_paths = Vec::new();
    let mut success = true;
    for source in &manifest.packages {
        match ensure_package(source, &cache_root, sync_env.install_timeout) {
            Ok(Some(path)) => installed_paths.push(path),
            Ok(None) => {}
            Err(message) => {
                err(&format!("package bootstrap failed for {source}: {message}"));
                success = false;
            }
        }
    }

    if let Err(message) = patch_runtime_settings(&runtime_settings_path, &installed_paths) {
        err(&format!("package settings patch failed: {message}"));
        success = false;
    }

    success
}

pub(super) fn read_package_manifest(path: &Path) -> Result<PackageManifest, String> {
    let content = match fs::read_to_string(path) {
        Ok(content) => content,
        Err(error) if error.kind() == io::ErrorKind::NotFound => {
            return Ok(PackageManifest {
                packages: Vec::new(),
            });
        }
        Err(error) => return Err(format!("{} ({error})", path.display())),
    };

    let value: Value = serde_json::from_str(&content)
        .map_err(|error| format!("invalid JSON in {}: {error}", path.display()))?;
    let object = value
        .as_object()
        .ok_or_else(|| format!("{} must contain a JSON object", path.display()))?;
    let packages_value = object
        .get("packages")
        .ok_or_else(|| format!("{} missing \"packages\" array", path.display()))?;
    let packages_array = packages_value
        .as_array()
        .ok_or_else(|| format!("{} field \"packages\" must be an array", path.display()))?;

    let mut seen = HashSet::new();
    let mut packages = Vec::new();
    for entry in packages_array {
        let source = entry
            .as_str()
            .ok_or_else(|| format!("{} package entries must be strings", path.display()))?
            .trim();
        if source.is_empty() {
            return Err(format!(
                "{} package entries must not be empty",
                path.display()
            ));
        }
        if seen.insert(source.to_string()) {
            packages.push(source.to_string());
        }
    }

    Ok(PackageManifest { packages })
}

pub(super) fn patch_runtime_settings(path: &Path, package_paths: &[PathBuf]) -> Result<(), String> {
    let current = match fs::read_to_string(path) {
        Ok(content) => content,
        Err(error) if error.kind() == io::ErrorKind::NotFound => "{}".to_string(),
        Err(error) => return Err(format!("read {} ({error})", path.display())),
    };
    let mut value: Value = serde_json::from_str(&current)
        .map_err(|error| format!("parse {} ({error})", path.display()))?;
    if !value.is_object() {
        value = Value::Object(Map::new());
    }
    let object = value
        .as_object_mut()
        .ok_or_else(|| format!("{} must contain a JSON object", path.display()))?;
    object.insert(
        "packages".to_string(),
        Value::Array(
            package_paths
                .iter()
                .map(|path| Value::String(path.to_string_lossy().to_string()))
                .collect(),
        ),
    );

    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)
            .map_err(|error| format!("create {} ({error})", parent.display()))?;
    }
    let content = serde_json::to_string_pretty(&value)
        .map_err(|error| format!("serialize {} ({error})", path.display()))?;
    fs::write(path, format!("{content}\n"))
        .map_err(|error| format!("write {} ({error})", path.display()))
}

fn ensure_package(
    source: &str,
    cache_root: &Path,
    timeout: Duration,
) -> Result<Option<PathBuf>, String> {
    let final_dir = package_cache_dir(cache_root, source);
    if package_is_healthy(&final_dir)? {
        return Ok(Some(final_dir));
    }

    fs::create_dir_all(cache_root)
        .map_err(|error| format!("create cache root {} ({error})", cache_root.display()))?;
    let staging_dir = staging_dir_for(&final_dir);
    super::rm_entry(&staging_dir)
        .map_err(|error| format!("clear staging dir {} ({error})", staging_dir.display()))?;
    fs::create_dir_all(staging_dir.parent().unwrap_or(cache_root))
        .map_err(|error| format!("create staging parent {} ({error})", staging_dir.display()))?;

    if !clone_package(source, &staging_dir, timeout) {
        let _ = super::rm_entry(&staging_dir);
        return Err("clone failed".to_string());
    }
    if !install_package_deps(&staging_dir, timeout) {
        let _ = super::rm_entry(&staging_dir);
        return Err("dependency install failed".to_string());
    }

    let mut healthy = package_is_healthy(&staging_dir)?;
    if !healthy && package_has_build_script(&staging_dir)? {
        if !run_package_build(&staging_dir, timeout) {
            let _ = super::rm_entry(&staging_dir);
            return Err("build failed".to_string());
        }
        if !install_inferred_import_packages(&staging_dir, timeout) {
            let _ = super::rm_entry(&staging_dir);
            return Err("install inferred packages after build failed".to_string());
        }
        healthy = package_is_healthy(&staging_dir)?;
    }

    if !healthy {
        let _ = super::rm_entry(&staging_dir);
        return Err("package resources failed validation".to_string());
    }

    replace_dir_atomically(&staging_dir, &final_dir)
        .map_err(|error| format!("activate package {} ({error})", final_dir.display()))?;
    Ok(Some(final_dir))
}
