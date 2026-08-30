use sha2::{Digest, Sha256};
use std::collections::HashSet;
use std::fs;
use std::io;
use std::path::{Path, PathBuf};
use thiserror::Error;

use super::spec::{NpmPackageSpec, is_valid_component};

#[derive(Debug, Error)]
pub enum CacheError {
    #[error("invalid tool: {0}")]
    InvalidTool(String),
    #[error("I/O error at {path}: {source}")]
    Io {
        path: PathBuf,
        #[source]
        source: io::Error,
    },
    #[error("cache entry is not a symlink: {0}")]
    NotASymlink(PathBuf),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NpmCacheLayout {
    pub tool_cache: PathBuf,
    pub versions_dir: PathBuf,
    pub current_link: PathBuf,
    pub previous_link: PathBuf,
    pub lock_file: PathBuf,
}

/// Calculates the deterministic cache layout for a tool and package.
pub fn npm_cache_layout(
    home: &Path,
    tool: &str,
    package: &str,
    cache_home: Option<&Path>,
) -> Result<NpmCacheLayout, CacheError> {
    if !is_valid_component(tool) {
        return Err(CacheError::InvalidTool(tool.to_string()));
    }

    let mut hasher = Sha256::new();
    hasher.update(package.as_bytes());
    let full_hex = hex::encode(hasher.finalize());
    let package_key = match full_hex.get(..16) {
        Some(slice) => slice,
        None => &full_hex,
    };

    let base_cache = cache_home
        .map(Path::to_path_buf)
        .or_else(|| std::env::var_os("XDG_CACHE_HOME").map(PathBuf::from))
        .unwrap_or_else(|| home.join(".cache"));

    let tool_cache = base_cache.join("npm-tools").join(tool);
    let package_cache = tool_cache.join("packages").join(package_key);

    Ok(NpmCacheLayout {
        tool_cache: tool_cache.clone(),
        versions_dir: package_cache.join("versions"),
        current_link: package_cache.join("current"),
        previous_link: package_cache.join("previous"),
        lock_file: tool_cache.join("lock"),
    })
}

/// Returns the executable binary path inside a package installation root (`node_modules/.bin/{bin}`).
#[must_use]
pub fn package_bin_path(root: &Path, bin: &str) -> PathBuf {
    root.join("node_modules").join(".bin").join(bin)
}

/// Checks if a target path is an existing, executable regular file.
#[must_use]
pub fn is_executable(target_path: &Path) -> bool {
    let Ok(metadata) = fs::metadata(target_path) else {
        return false;
    };
    if !metadata.is_file() {
        return false;
    }

    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        (metadata.permissions().mode() & 0o111) != 0
    }
    #[cfg(not(unix))]
    {
        true
    }
}

/// Checks if the installed `package.json` at `root/node_modules/{package}/package.json` matches the name and version.
#[must_use]
pub fn installed_package_matches(root: &Path, package_name: &str, version: &str) -> bool {
    let mut manifest_path = root.join("node_modules");
    for segment in package_name.split('/') {
        manifest_path.push(segment);
    }
    manifest_path.push("package.json");

    let Ok(content) = fs::read_to_string(&manifest_path) else {
        return false;
    };

    let Ok(parsed): Result<serde_json::Value, _> = serde_json::from_str(&content) else {
        return false;
    };

    let Some(name_val) = parsed.get("name").and_then(|v| v.as_str()) else {
        return false;
    };
    let Some(version_val) = parsed.get("version").and_then(|v| v.as_str()) else {
        return false;
    };

    name_val == package_name && version_val == version
}

/// Reads the symlink target of `link_path`. If it exists but is not a symlink, returns an error.
pub fn read_link_target(link_path: &Path) -> Result<Option<PathBuf>, CacheError> {
    match fs::symlink_metadata(link_path) {
        Ok(metadata) => {
            if !metadata.file_type().is_symlink() {
                return Err(CacheError::NotASymlink(link_path.to_path_buf()));
            }
            let target = fs::read_link(link_path).map_err(|e| CacheError::Io {
                path: link_path.to_path_buf(),
                source: e,
            })?;
            Ok(Some(target))
        }
        Err(err) if err.kind() == io::ErrorKind::NotFound => Ok(None),
        Err(err) => Err(CacheError::Io {
            path: link_path.to_path_buf(),
            source: err,
        }),
    }
}

/// Atomically replaces or creates a symlink at `link_path` pointing to `target`.
pub fn replace_link(link_path: &Path, target: &Path) -> Result<(), CacheError> {
    let temp_path = link_path.with_extension(format!("{}.tmp", std::process::id()));
    let _ = fs::remove_file(&temp_path);

    #[cfg(unix)]
    {
        std::os::unix::fs::symlink(target, &temp_path).map_err(|e| CacheError::Io {
            path: temp_path.clone(),
            source: e,
        })?;
    }
    #[cfg(windows)]
    {
        std::os::windows::fs::symlink_dir(target, &temp_path).map_err(|e| CacheError::Io {
            path: temp_path.clone(),
            source: e,
        })?;
    }

    if let Err(err) = fs::rename(&temp_path, link_path) {
        let _ = fs::remove_file(&temp_path);
        return Err(CacheError::Io {
            path: link_path.to_path_buf(),
            source: err,
        });
    }

    Ok(())
}

/// Updates the `current` and `previous` symlinks in the layout to point to the resolved version directory.
pub fn update_current_and_previous(
    layout: &NpmCacheLayout,
    version: &str,
) -> Result<(), CacheError> {
    let expected_target = Path::new("versions").join(version);
    let current_target = read_link_target(&layout.current_link)?;

    if current_target.as_ref() == Some(&expected_target) {
        return Ok(());
    }

    if let Some(ref target) = current_target {
        replace_link(&layout.previous_link, target)?;
    }

    replace_link(&layout.current_link, &expected_target)?;
    Ok(())
}

/// Prunes old versions in `versions_dir`, preserving only the versions currently referenced by `current` and `previous`.
pub fn prune_versions(layout: &NpmCacheLayout) -> Result<(), CacheError> {
    let mut keep = HashSet::new();

    for link_path in [&layout.current_link, &layout.previous_link] {
        if let Ok(Some(target)) = read_link_target(link_path)
            && let Some(file_name) = target.file_name()
        {
            keep.insert(file_name.to_string_lossy().into_owned());
        }
    }

    let Ok(entries) = fs::read_dir(&layout.versions_dir) else {
        return Ok(());
    };

    for entry in entries.flatten() {
        let name = entry.file_name().to_string_lossy().into_owned();
        if name.starts_with(".stage.") {
            continue;
        }
        if keep.contains(&name) {
            continue;
        }
        let entry_path = entry.path();
        let _ = fs::remove_dir_all(&entry_path);
    }

    Ok(())
}

/// Checks if there is a valid, existing cached package at `layout.current_link`.
#[must_use]
pub fn current_cached_package(
    layout: &NpmCacheLayout,
    spec: &NpmPackageSpec,
) -> Option<(String, PathBuf)> {
    let target = read_link_target(&layout.current_link).ok()??;
    let version = target.file_name()?.to_string_lossy().into_owned();

    let current_bin = package_bin_path(&layout.current_link, &spec.bin);
    if !is_executable(&current_bin) {
        return None;
    }

    if !installed_package_matches(&layout.current_link, &spec.package, &version) {
        return None;
    }

    Some((version, current_bin))
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
    fn test_npm_cache_layout_deterministic() {
        let home = Path::new("/Users/testuser");
        let layout1 = npm_cache_layout(home, "demo", "demo-package", None).unwrap();
        let layout2 = npm_cache_layout(home, "demo", "demo-package", None).unwrap();
        assert_eq!(layout1, layout2);
        assert!(layout1.tool_cache.ends_with(".cache/npm-tools/demo"));
        assert!(layout1.versions_dir.to_string_lossy().contains("packages"));
        assert!(layout1.current_link.to_string_lossy().ends_with("current"));
        assert!(
            layout1
                .previous_link
                .to_string_lossy()
                .ends_with("previous")
        );
    }

    #[test]
    fn test_symlink_rotation_and_pruning() {
        let tmp = tempdir().unwrap();
        let home = tmp.path().join("home");
        let cache_home = tmp.path().join("cache");
        let layout = npm_cache_layout(&home, "demo", "demo-package", Some(&cache_home)).unwrap();
        fs::create_dir_all(&layout.versions_dir).unwrap();

        // Create version directories
        let v1_dir = layout.versions_dir.join("1.0.0");
        let v2_dir = layout.versions_dir.join("2.0.0");
        let v3_dir = layout.versions_dir.join("3.0.0");
        fs::create_dir_all(&v1_dir).unwrap();
        fs::create_dir_all(&v2_dir).unwrap();
        fs::create_dir_all(&v3_dir).unwrap();

        // Rotate to 1.0.0
        update_current_and_previous(&layout, "1.0.0").unwrap();
        assert_eq!(
            read_link_target(&layout.current_link).unwrap(),
            Some(PathBuf::from("versions/1.0.0"))
        );
        assert_eq!(read_link_target(&layout.previous_link).unwrap(), None);

        // Rotate to 2.0.0
        update_current_and_previous(&layout, "2.0.0").unwrap();
        assert_eq!(
            read_link_target(&layout.current_link).unwrap(),
            Some(PathBuf::from("versions/2.0.0"))
        );
        assert_eq!(
            read_link_target(&layout.previous_link).unwrap(),
            Some(PathBuf::from("versions/1.0.0"))
        );

        // Rotate to 3.0.0
        update_current_and_previous(&layout, "3.0.0").unwrap();
        assert_eq!(
            read_link_target(&layout.current_link).unwrap(),
            Some(PathBuf::from("versions/3.0.0"))
        );
        assert_eq!(
            read_link_target(&layout.previous_link).unwrap(),
            Some(PathBuf::from("versions/2.0.0"))
        );

        // Prune: 1.0.0 should be deleted because current is 3.0.0 and previous is 2.0.0
        prune_versions(&layout).unwrap();
        assert!(!v1_dir.exists());
        assert!(v2_dir.exists());
        assert!(v3_dir.exists());
    }

    #[test]
    fn test_installed_package_matches() {
        let tmp = tempdir().unwrap();
        let stage = tmp.path().join("stage");
        let pkg_dir = stage.join("node_modules").join("@openai").join("codex");
        fs::create_dir_all(&pkg_dir).unwrap();

        fs::write(
            pkg_dir.join("package.json"),
            r#"{"name": "@openai/codex", "version": "1.2.3"}"#,
        )
        .unwrap();

        assert!(installed_package_matches(&stage, "@openai/codex", "1.2.3"));
        assert!(!installed_package_matches(&stage, "@openai/codex", "1.2.4"));
        assert!(!installed_package_matches(&stage, "other-pkg", "1.2.3"));
    }
}
