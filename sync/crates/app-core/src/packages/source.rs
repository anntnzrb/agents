use std::fs;
use std::io;
use std::path::{Path, PathBuf};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use super::PackageError;

pub type PackageFetchFn =
    Box<dyn Fn(&str, Duration) -> Result<Vec<u8>, PackageError> + Send + Sync>;
pub type PackageExtractFn =
    Box<dyn Fn(&[u8], &Path, Duration) -> Result<(), PackageError> + Send + Sync>;

/// Runtime hooks for package fetching and archive extraction.
#[derive(Default)]
pub struct PackageSourceRuntime {
    pub fetch: Option<PackageFetchFn>,
    pub extract: Option<PackageExtractFn>,
}

/// Computes the 64-bit FNV-1a hash of a string, formatted as 16 lowercase hex characters.
#[must_use]
pub fn fnv1a64(input: &str) -> String {
    const PRIME: u64 = 0x0100_0000_01b3;
    let mut hash: u64 = 0xcbf2_9ce4_8422_2325;
    for byte in input.as_bytes() {
        hash ^= u64::from(*byte);
        hash = hash.wrapping_mul(PRIME);
    }
    format!("{hash:016x}")
}

/// Checks whether the source specifier refers to a local filesystem path.
#[must_use]
pub fn is_local_path_source(source: &str) -> bool {
    let path = Path::new(source);
    path.is_absolute() || path.exists()
}

/// Derives a clean directory slug from a package source string.
#[must_use]
pub fn source_slug(source: &str) -> String {
    let trimmed = source.trim().trim_end_matches('/');
    let normalized = trimmed.strip_suffix(".git").unwrap_or(trimmed);

    let source_parts: Vec<String> = if is_local_path_source(normalized) {
        let path = Path::new(normalized);
        let base_name = path
            .file_name()
            .and_then(|n| n.to_str())
            .unwrap_or("package");
        vec![base_name.to_owned()]
    } else {
        let parts: Vec<&str> = normalized
            .split(['/', ':'])
            .filter(|part| !part.is_empty())
            .collect();
        let count = parts.len();
        if count >= 2 {
            let start = count.saturating_sub(2);
            parts
                .iter()
                .skip(start)
                .map(|part| (*part).to_owned())
                .collect()
        } else {
            parts.iter().map(|part| (*part).to_owned()).collect()
        }
    };

    let joined = if source_parts.is_empty() {
        "package".to_owned()
    } else {
        source_parts.join("-")
    };

    let sanitized: String = joined
        .chars()
        .map(|ch| {
            if ch.is_ascii_alphanumeric() {
                ch.to_ascii_lowercase()
            } else {
                '-'
            }
        })
        .collect();

    let compact: String = sanitized
        .split('-')
        .filter(|part| !part.is_empty())
        .collect::<Vec<_>>()
        .join("-");

    if compact.is_empty() {
        "package".to_owned()
    } else {
        compact
    }
}

/// Returns the deterministic cache directory for a package source.
#[must_use]
pub fn package_cache_dir(cache_root: impl AsRef<Path>, source: &str) -> PathBuf {
    let slug = source_slug(source);
    let hash = fnv1a64(source);
    cache_root.as_ref().join(format!("{slug}-{hash}"))
}

/// Changes or appends a custom extension to a path, replacing the last extension if present.
fn with_extension_custom(target: &Path, extension: &str) -> PathBuf {
    let parent = target.parent().unwrap_or_else(|| Path::new(""));
    let file_name = target.file_name().and_then(|n| n.to_str()).unwrap_or("");
    let stem = file_name.rfind('.').map_or(file_name, |idx| {
        if idx > 0 {
            file_name.get(..idx).unwrap_or(file_name)
        } else {
            file_name
        }
    });
    parent.join(format!("{stem}.{extension}"))
}

/// Generates a unique staging directory path for an atomic target directory.
#[must_use]
pub fn staging_dir_for(final_dir: impl AsRef<Path>) -> PathBuf {
    let pid = std::process::id();
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |d| d.as_nanos());
    with_extension_custom(final_dir.as_ref(), &format!("staging-{pid}-{now}"))
}

/// Safely removes a file, symlink, or directory without failing if it does not exist.
pub fn rm_entry(path: impl AsRef<Path>) -> io::Result<()> {
    let p = path.as_ref();
    if !p.exists() && fs::symlink_metadata(p).is_err() {
        return Ok(());
    }
    if let Ok(metadata) = fs::symlink_metadata(p) {
        if metadata.is_dir() && !metadata.file_type().is_symlink() {
            fs::remove_dir_all(p)?;
        } else {
            fs::remove_file(p)?;
        }
    }
    Ok(())
}

/// Atomically replaces destination directory with source directory using a temporary backup.
pub fn replace_dir_atomically(src: impl AsRef<Path>, dst: impl AsRef<Path>) -> io::Result<()> {
    let src_path = src.as_ref();
    let dst_path = dst.as_ref();
    let backup = with_extension_custom(dst_path, "backup");
    let _ = rm_entry(&backup);

    let dst_exists = dst_path.exists();
    if dst_exists {
        fs::rename(dst_path, &backup)?;
    }

    match fs::rename(src_path, dst_path) {
        Ok(()) => {
            let _ = rm_entry(&backup);
            Ok(())
        }
        Err(err) => {
            if dst_exists && backup.exists() {
                let _ = fs::rename(&backup, dst_path);
            }
            Err(err)
        }
    }
}

/// Parses an owner/repo slug from a GitHub git or web URL.
#[must_use]
pub fn github_repo_slug(source: &str) -> Option<String> {
    let trimmed = source.trim();
    let normalized = trimmed.strip_suffix(".git").unwrap_or(trimmed);

    let repository_path = if let Some(stripped) = normalized.strip_prefix("git@github.com:") {
        stripped.to_owned()
    } else if let Ok(url) = url::Url::parse(normalized) {
        let host = url.host_str()?;
        if host != "github.com" && host != "www.github.com" {
            return None;
        }
        url.path().to_owned()
    } else {
        return None;
    };

    let parts: Vec<&str> = repository_path
        .split('/')
        .filter(|part| !part.is_empty())
        .take(2)
        .collect();

    if parts.len() == 2 {
        let owner = parts.first()?;
        let repo = parts.get(1)?;
        Some(format!("{owner}/{repo}"))
    } else {
        None
    }
}

/// Recursively copies a directory or file to a destination path.
pub fn copy_dir_recursive(src: &Path, dst: &Path) -> io::Result<()> {
    let metadata = fs::metadata(src)?;
    if metadata.is_dir() {
        fs::create_dir_all(dst)?;
        for entry in fs::read_dir(src)? {
            let entry = entry?;
            let entry_path = entry.path();
            let dest_path = dst.join(entry.file_name());
            copy_dir_recursive(&entry_path, &dest_path)?;
        }
    } else {
        if let Some(parent) = dst.parent() {
            fs::create_dir_all(parent)?;
        }
        fs::copy(src, dst)?;
    }
    Ok(())
}

/// Extracts a `.tar.gz` archive buffer into the destination directory.
pub fn extract_archive_tar_gz(archive: &[u8], destination: &Path) -> Result<(), PackageError> {
    let decoder = flate2::read::GzDecoder::new(archive);
    let mut tar_archive = tar::Archive::new(decoder);
    tar_archive
        .unpack(destination)
        .map_err(|err| PackageError::Archive(format!("archive extraction failed: {err}")))?;
    Ok(())
}

/// Clones a package from a local path or GitHub archive into a target directory.
pub fn clone_package(
    source: &str,
    target_dir: impl AsRef<Path>,
    timeout: Duration,
    runtime: Option<&PackageSourceRuntime>,
) -> Result<bool, PackageError> {
    let target = target_dir.as_ref();
    let normalized = source.trim();

    if is_local_path_source(normalized) {
        let src_path = Path::new(normalized);
        if target.exists() {
            return Ok(false);
        }
        if copy_dir_recursive(src_path, target).is_err() {
            return Ok(false);
        }
        return Ok(true);
    }

    let Some(slug) = github_repo_slug(normalized) else {
        return Ok(false);
    };

    let url = format!("https://codeload.github.com/{slug}/tar.gz/HEAD");

    let archive_bytes = if let Some(fetch_fn) = runtime.and_then(|r| r.fetch.as_ref()) {
        fetch_fn(&url, timeout)?
    } else {
        let fetched = std::thread::scope(|scope| {
            scope
                .spawn(|| -> Result<Option<Vec<u8>>, PackageError> {
                    let client = reqwest::blocking::Client::builder()
                        .timeout(timeout)
                        .build()
                        .map_err(|err| {
                            PackageError::CloneFailed(format!("HTTP client error: {err}"))
                        })?;
                    let response = client.get(&url).send().map_err(|err| {
                        PackageError::CloneFailed(format!("HTTP request failed: {err}"))
                    })?;
                    if !response.status().is_success() {
                        return Ok(None);
                    }
                    let bytes = response
                        .bytes()
                        .map_err(|err| {
                            PackageError::CloneFailed(format!("HTTP read body error: {err}"))
                        })?
                        .to_vec();
                    Ok(Some(bytes))
                })
                .join()
                .map_err(|_| {
                    PackageError::CloneFailed("package fetch thread panicked".to_string())
                })?
        })?;
        match fetched {
            Some(bytes) => bytes,
            None => return Ok(false),
        }
    };

    let parent_dir = target.parent().unwrap_or_else(|| Path::new("."));
    fs::create_dir_all(parent_dir)?;

    let temp_dir = tempfile::Builder::new()
        .prefix(".source.")
        .tempdir_in(parent_dir)?;
    let extraction_dir = temp_dir.path();

    if let Some(extract_fn) = runtime.and_then(|r| r.extract.as_ref()) {
        extract_fn(&archive_bytes, extraction_dir, timeout)?;
    } else {
        extract_archive_tar_gz(&archive_bytes, extraction_dir)?;
    }

    let entries: Vec<fs::DirEntry> = fs::read_dir(extraction_dir)?
        .filter_map(Result::ok)
        .collect();

    if entries.len() != 1 {
        return Ok(false);
    }

    let first_entry = entries
        .first()
        .ok_or_else(|| PackageError::Archive("missing extracted directory entry".to_owned()))?;

    if !first_entry.file_type()?.is_dir() {
        return Ok(false);
    }

    fs::rename(first_entry.path(), target)?;
    Ok(true)
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn test_fnv1a64_matches_legacy() {
        assert_eq!(fnv1a64(""), "cbf29ce484222325");
        assert_eq!(
            fnv1a64("https://github.com/tintinweb/pi-supervisor"),
            "72b1c1c0f7a8719a"
        );
    }

    #[test]
    fn test_source_slug_generation() {
        assert_eq!(source_slug("https://github.com/foo/bar.git"), "foo-bar");
        assert_eq!(source_slug("git@github.com:owner/repo.git"), "owner-repo");
        assert_eq!(source_slug(""), "package");
    }

    #[test]
    fn test_package_cache_dir_stability() {
        let root = Path::new("/tmp/cache");
        let a = package_cache_dir(root, "https://github.com/tintinweb/pi-supervisor");
        let b = package_cache_dir(root, "https://github.com/tintinweb/pi-supervisor");
        assert_eq!(a, b);
    }

    #[test]
    fn test_replace_dir_atomically() {
        let dir = tempdir().unwrap();
        let src = dir.path().join("src");
        let dst = dir.path().join("dst");

        fs::create_dir_all(&src).unwrap();
        fs::write(src.join("test.txt"), "hello").unwrap();

        replace_dir_atomically(&src, &dst).unwrap();
        assert!(!src.exists());
        assert!(dst.join("test.txt").exists());
    }

    #[test]
    fn test_github_repo_slug_parsing() {
        assert_eq!(
            github_repo_slug("https://github.com/owner/repo.git"),
            Some("owner/repo".to_owned())
        );
        assert_eq!(
            github_repo_slug("git@github.com:owner/repo.git"),
            Some("owner/repo".to_owned())
        );
        assert_eq!(github_repo_slug("https://example.com/not-github"), None);
    }

    #[test]
    fn test_clone_package_with_mock_runtime() {
        let dir = tempdir().unwrap();
        let target = dir.path().join("out");

        let runtime = PackageSourceRuntime {
            fetch: Some(Box::new(|url, _| {
                assert!(url.contains("tintinweb/pi-supervisor"));
                Ok(b"mock-archive".to_vec())
            })),
            extract: Some(Box::new(|_archive, destination, _| {
                let inner = destination.join("pi-supervisor-main");
                fs::create_dir_all(&inner)?;
                fs::write(inner.join("package.json"), "{}")?;
                Ok(())
            })),
        };

        let result = clone_package(
            "https://github.com/tintinweb/pi-supervisor",
            &target,
            Duration::from_secs(1),
            Some(&runtime),
        );

        assert!(result.is_ok());
        assert!(result.unwrap());
        assert!(target.join("package.json").exists());
    }
}
