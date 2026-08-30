use std::collections::{HashMap, HashSet};
use std::fs::{self, File, Metadata, OpenOptions};
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

#[cfg(unix)]
use std::os::unix::fs::{MetadataExt, OpenOptionsExt, PermissionsExt};

/// Mode for private files (owner read/write only, 0600).
pub const PRIVATE_FILE_MODE: u32 = 0o600;

/// Default mode for executable/directory operations (0755).
pub const DEFAULT_DIR_MODE: u32 = 0o755;

/// Cached representation of source file content and metadata.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CachedSourceEntry {
    pub size: u64,
    pub mode: u32,
    pub mtime_nanos: i128,
    pub ctime_nanos: i128,
    pub content: Vec<u8>,
}

/// Cache mapping canonical/relative file paths to their cached content and stat metadata.
pub type SourceContentCache = HashMap<PathBuf, CachedSourceEntry>;

/// Returns true if the target path exists and is a symbolic link.
#[must_use]
pub fn is_symlink(target_path: impl AsRef<Path>) -> bool {
    fs::symlink_metadata(target_path).is_ok_and(|meta| meta.file_type().is_symlink())
}

/// Symlink-aware removal of a file, symlink, or directory.
///
/// If target does not exist, returns `Ok(())` without error.
/// Symbolic links are unlinked directly without deleting their target.
/// Directories are removed recursively.
pub fn rm_entry(target_path: impl AsRef<Path>) -> io::Result<()> {
    let path = target_path.as_ref();
    let meta = match fs::symlink_metadata(path) {
        Ok(m) => m,
        Err(err) if err.kind() == io::ErrorKind::NotFound => return Ok(()),
        Err(err) => return Err(err),
    };

    let result = if meta.file_type().is_symlink() || meta.file_type().is_file() {
        fs::remove_file(path)
    } else if meta.file_type().is_dir() {
        fs::remove_dir_all(path)
    } else {
        fs::remove_file(path)
    };

    match result {
        Ok(()) => Ok(()),
        Err(err) if err.kind() == io::ErrorKind::NotFound => Ok(()),
        Err(err) => Err(err),
    }
}

/// Recursively copies `src` to `dst`.
///
/// If `src` is a file or symlink to a file, copies the single file to `dst`.
/// If `src` is a directory, recursively recreates directory hierarchy and copies all files.
pub fn copy_tree(src: impl AsRef<Path>, dst: impl AsRef<Path>) -> io::Result<()> {
    let src = src.as_ref();
    let dst = dst.as_ref();
    let meta = fs::metadata(src)?;

    if !meta.is_dir() {
        if let Some(parent) = dst.parent() {
            fs::create_dir_all(parent)?;
        }
        fs::copy(src, dst)?;
        return Ok(());
    }

    copy_tree_recursive(src, dst)
}

fn copy_tree_recursive(src: &Path, dst: &Path) -> io::Result<()> {
    let meta = fs::metadata(src)?;
    if !meta.is_dir() {
        if let Some(parent) = dst.parent() {
            fs::create_dir_all(parent)?;
        }
        fs::copy(src, dst)?;
        return Ok(());
    }

    fs::create_dir_all(dst)?;
    for entry in fs::read_dir(src)? {
        let entry = entry?;
        let child_src = entry.path();
        let child_dst = dst.join(entry.file_name());
        let child_meta = fs::metadata(&child_src)?;
        if child_meta.is_dir() {
            copy_tree_recursive(&child_src, &child_dst)?;
        } else {
            if let Some(parent) = child_dst.parent() {
                fs::create_dir_all(parent)?;
            }
            fs::copy(&child_src, &child_dst)?;
        }
    }
    Ok(())
}

/// Synchronizes a managed directory tree from `src` to `dst`, preserving specified paths
/// and deleting untracked files in `dst`.
pub fn sync_managed_tree(
    src: impl AsRef<Path>,
    dst: impl AsRef<Path>,
    preserve_paths: &[impl AsRef<Path>],
    mut cache: Option<&mut SourceContentCache>,
) -> io::Result<()> {
    let src = src.as_ref();
    let dst = dst.as_ref();
    let meta = fs::metadata(src)?;

    if !meta.is_dir() {
        sync_managed_file(src, dst, &meta, cache)?;
        return Ok(());
    }

    let normalized_preserve = normalize_preserve_paths(preserve_paths);
    sync_managed_tree_recursive(src, dst, &normalized_preserve, &mut cache)
}

/// Synchronizes the children of `src` into `dst` without removing existing untracked files in `dst`.
pub fn sync_managed_children(
    src: impl AsRef<Path>,
    dst: impl AsRef<Path>,
    preserve_paths: &[impl AsRef<Path>],
    mut cache: Option<&mut SourceContentCache>,
) -> io::Result<()> {
    let src = src.as_ref();
    let dst = dst.as_ref();
    let meta = fs::metadata(src)?;

    if !meta.is_dir() {
        sync_managed_file(src, dst, &meta, cache)?;
        return Ok(());
    }

    let normalized_preserve = normalize_preserve_paths(preserve_paths);
    sync_managed_children_recursive(src, dst, &normalized_preserve, &mut cache)
}

fn sync_managed_tree_recursive(
    src: &Path,
    dst: &Path,
    preserve_paths: &[String],
    cache: &mut Option<&mut SourceContentCache>,
) -> io::Result<()> {
    let meta = fs::metadata(src)?;
    if !meta.is_dir() {
        return sync_managed_file(src, dst, &meta, cache.as_deref_mut());
    }

    ensure_directory(dst)?;

    let mut src_names = HashSet::new();
    let mut src_entries = Vec::new();
    for entry in fs::read_dir(src)? {
        let entry = entry?;
        let name = entry.file_name().to_string_lossy().to_string();
        src_names.insert(name.clone());
        src_entries.push((name, entry.path()));
    }

    // Delete extraneous items in dst not present in src and not preserved
    for dst_entry in safe_read_dir(dst)? {
        let name = dst_entry.file_name().to_string_lossy().to_string();
        if src_names.contains(&name) || preserve_paths.contains(&name) {
            continue;
        }
        rm_entry(dst.join(&name))?;
    }

    // Synchronize entries from src into dst
    for (name, child_src) in src_entries {
        if preserve_paths.contains(&name) {
            continue;
        }
        let child_dst = dst.join(&name);
        let child_preserve = child_preserve(preserve_paths, &name);
        let child_meta = fs::metadata(&child_src)?;
        if child_meta.is_dir() {
            sync_managed_tree_recursive(&child_src, &child_dst, &child_preserve, cache)?;
        } else {
            sync_managed_file(&child_src, &child_dst, &child_meta, cache.as_deref_mut())?;
        }
    }

    Ok(())
}

fn sync_managed_children_recursive(
    src: &Path,
    dst: &Path,
    preserve_paths: &[String],
    cache: &mut Option<&mut SourceContentCache>,
) -> io::Result<()> {
    let meta = fs::metadata(src)?;
    if !meta.is_dir() {
        return sync_managed_file(src, dst, &meta, cache.as_deref_mut());
    }

    ensure_directory(dst)?;

    for entry in fs::read_dir(src)? {
        let entry = entry?;
        let name = entry.file_name().to_string_lossy().to_string();
        if preserve_paths.contains(&name) {
            continue;
        }
        let child_src = entry.path();
        let child_dst = dst.join(&name);
        let child_preserve = child_preserve(preserve_paths, &name);
        let child_meta = fs::metadata(&child_src)?;
        if child_meta.is_dir() {
            sync_managed_tree_recursive(&child_src, &child_dst, &child_preserve, cache)?;
        } else {
            sync_managed_file(&child_src, &child_dst, &child_meta, cache.as_deref_mut())?;
        }
    }

    Ok(())
}

/// Synchronizes a single managed file if it is not already identical.
pub fn sync_managed_file(
    src: &Path,
    dst: &Path,
    src_meta: &Metadata,
    cache: Option<&mut SourceContentCache>,
) -> io::Result<()> {
    if is_identical_file(src, src_meta, dst, cache) {
        return Ok(());
    }

    if let Some(parent) = dst.parent() {
        fs::create_dir_all(parent)?;
    }
    rm_entry(dst)?;
    fs::copy(src, dst)?;

    #[cfg(unix)]
    {
        let mode = src_meta.mode() & 0o777;
        fs::set_permissions(dst, fs::Permissions::from_mode(mode))?;
    }

    Ok(())
}

/// Checks if destination matches source in size, mode, and byte content.
#[must_use]
pub fn is_identical_file(
    src: &Path,
    src_meta: &Metadata,
    dst: &Path,
    mut cache: Option<&mut SourceContentCache>,
) -> bool {
    if src_meta.is_dir() {
        return false;
    }

    let Ok(dst_symlink_meta) = fs::symlink_metadata(dst) else {
        return false;
    };
    if dst_symlink_meta.file_type().is_symlink() {
        return false;
    }

    let Ok(dst_meta) = fs::metadata(dst) else {
        return false;
    };
    if !dst_meta.is_file() {
        return false;
    }
    if src_meta.len() != dst_meta.len() {
        return false;
    }

    #[cfg(unix)]
    {
        if (src_meta.mode() & 0o777) != (dst_meta.mode() & 0o777) {
            return false;
        }
    }

    if src_meta.len() == 0 {
        return true;
    }

    let (src_mode, src_modified_time, src_ctime) = {
        #[cfg(unix)]
        {
            (
                src_meta.mode() & 0o777,
                i128::from(src_meta.mtime_nsec())
                    .wrapping_add(i128::from(src_meta.mtime()).wrapping_mul(1_000_000_000)),
                i128::from(src_meta.ctime_nsec())
                    .wrapping_add(i128::from(src_meta.ctime()).wrapping_mul(1_000_000_000)),
            )
        }
        #[cfg(not(unix))]
        {
            (0, 0, 0)
        }
    };

    let src_content = if let Some(cache_map) = cache.as_mut() {
        if let Some(cached) = cache_map.get(src) {
            if cached.size == src_meta.len()
                && cached.mode == src_mode
                && cached.mtime_nanos == src_modified_time
                && cached.ctime_nanos == src_ctime
            {
                cached.content.clone()
            } else {
                let Ok(content) = fs::read(src) else {
                    return false;
                };
                cache_map.insert(
                    src.to_path_buf(),
                    CachedSourceEntry {
                        size: src_meta.len(),
                        mode: src_mode,
                        mtime_nanos: src_modified_time,
                        ctime_nanos: src_ctime,
                        content: content.clone(),
                    },
                );
                content
            }
        } else {
            let Ok(content) = fs::read(src) else {
                return false;
            };
            cache_map.insert(
                src.to_path_buf(),
                CachedSourceEntry {
                    size: src_meta.len(),
                    mode: src_mode,
                    mtime_nanos: src_modified_time,
                    ctime_nanos: src_ctime,
                    content: content.clone(),
                },
            );
            content
        }
    } else {
        let Ok(content) = fs::read(src) else {
            return false;
        };
        content
    };

    let Ok(dst_content) = fs::read(dst) else {
        return false;
    };

    src_content == dst_content
}

/// Ensures the directory at `dst` exists and is a genuine directory (not a file or symlink).
pub fn ensure_directory(dst: impl AsRef<Path>) -> io::Result<()> {
    let dst = dst.as_ref();
    match fs::symlink_metadata(dst) {
        Ok(meta) => {
            if meta.is_dir() && !meta.file_type().is_symlink() {
                return Ok(());
            }
            rm_entry(dst)?;
        }
        Err(err) if err.kind() == io::ErrorKind::NotFound => {}
        Err(err) => return Err(err),
    }
    fs::create_dir_all(dst)
}

/// Idempotently writes text content with mode 0600 (owner read/write).
pub fn sync_private_text_file(dst: impl AsRef<Path>, content: &str) -> io::Result<bool> {
    sync_text_file(dst, content, PRIVATE_FILE_MODE)
}

/// Idempotently writes text content to `dst` with target `mode`.
///
/// Returns `Ok(false)` if the file already exists with exact content and mode.
/// Returns `Ok(true)` if the file was written/updated atomically.
pub fn sync_text_file(dst: impl AsRef<Path>, content: &str, mode: u32) -> io::Result<bool> {
    let dst = dst.as_ref();
    if matches_output(dst, content, mode) {
        return Ok(false);
    }

    atomic_write_text_file(dst, content, mode)?;
    Ok(true)
}

/// Atomically writes content to `dst` using a unique temporary sibling file and rename.
pub fn atomic_write_text_file(dst: impl AsRef<Path>, content: &str, mode: u32) -> io::Result<()> {
    let dst = dst.as_ref();
    let parent = dst.parent().unwrap_or_else(|| Path::new("."));
    fs::create_dir_all(parent)?;

    let (temp_path, mut file) = create_temp_file(dst, mode)?;
    let write_result = (|| -> io::Result<()> {
        file.write_all(content.as_bytes())?;
        file.flush()?;
        #[cfg(unix)]
        {
            fs::set_permissions(&temp_path, fs::Permissions::from_mode(mode & 0o777))?;
        }
        file.sync_all()?;
        drop(file);
        fs::rename(&temp_path, dst)?;
        Ok(())
    })();

    if write_result.is_err() {
        let _ = rm_entry(&temp_path);
    }
    write_result
}

/// Checks if destination file exists, is a regular file (not symlink), has exact content and matching permissions.
pub fn matches_output(path: impl AsRef<Path>, content: &str, mode: u32) -> bool {
    let path = path.as_ref();
    let Ok(meta) = fs::symlink_metadata(path) else {
        return false;
    };

    if meta.file_type().is_symlink() || !meta.is_file() {
        return false;
    }

    #[cfg(unix)]
    {
        if (meta.mode() & 0o777) != (mode & 0o777) {
            return false;
        }
    }

    let mut existing = String::new();
    match File::open(path).and_then(|mut f| f.read_to_string(&mut existing)) {
        Ok(_) => existing == content,
        Err(_) => false,
    }
}

fn create_temp_file(target: &Path, mode: u32) -> io::Result<(PathBuf, File)> {
    let parent = target.parent().unwrap_or_else(|| Path::new("."));
    let file_name = target
        .file_name()
        .map_or_else(|| "config".to_string(), |n| n.to_string_lossy().to_string());
    let pid = std::process::id();
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis();

    for attempt in 0..16 {
        let temp_name = format!(".{file_name}.{pid}.{now:x}-{attempt}.tmp");
        let temp_path = parent.join(temp_name);

        let mut opts = OpenOptions::new();
        opts.write(true).create_new(true);

        #[cfg(unix)]
        {
            opts.mode(mode & 0o777);
        }

        match opts.open(&temp_path) {
            Ok(file) => return Ok((temp_path, file)),
            Err(err) if err.kind() == io::ErrorKind::AlreadyExists => {}
            Err(err) => return Err(err),
        }
    }

    Err(io::Error::new(
        io::ErrorKind::AlreadyExists,
        format!(
            "create temporary file near {} (name collision)",
            target.display()
        ),
    ))
}

fn safe_read_dir(path: &Path) -> io::Result<Vec<fs::DirEntry>> {
    match fs::read_dir(path) {
        Ok(entries) => entries.collect(),
        Err(err) if err.kind() == io::ErrorKind::NotFound => Ok(Vec::new()),
        Err(err) => Err(err),
    }
}

fn child_preserve(preserve_paths: &[String], child_name: &str) -> Vec<String> {
    let prefix = format!("{child_name}/");
    preserve_paths
        .iter()
        .filter_map(|candidate| candidate.strip_prefix(&prefix).map(ToString::to_string))
        .collect()
}

fn normalize_preserve_paths(preserve_paths: &[impl AsRef<Path>]) -> Vec<String> {
    let mut set = HashSet::new();
    for p in preserve_paths {
        let s = p.as_ref().to_string_lossy().trim().to_string();
        if !s.is_empty() {
            set.insert(s);
        }
    }
    let mut list: Vec<String> = set.into_iter().collect();
    list.sort();
    list
}

#[cfg(test)]
#[allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::indexing_slicing,
    clippy::panic,
    clippy::panic_in_result_fn
)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn test_rm_entry_file_dir_symlink_nonexistent() -> io::Result<()> {
        let dir = tempdir()?;
        let file_path = dir.path().join("file.txt");
        let sub_dir = dir.path().join("sub");
        let sub_file = sub_dir.join("inner.txt");
        let symlink_path = dir.path().join("link.txt");

        fs::write(&file_path, "test")?;
        fs::create_dir_all(&sub_dir)?;
        fs::write(&sub_file, "nested")?;

        #[cfg(unix)]
        std::os::unix::fs::symlink(&file_path, &symlink_path)?;

        assert!(file_path.exists());
        assert!(sub_dir.exists());

        #[cfg(unix)]
        {
            assert!(is_symlink(&symlink_path));
            assert!(!is_symlink(&file_path));
            rm_entry(&symlink_path)?;
            assert!(!symlink_path.exists());
            assert!(file_path.exists()); // Original target intact
        }

        rm_entry(&file_path)?;
        assert!(!file_path.exists());

        rm_entry(&sub_dir)?;
        assert!(!sub_dir.exists());

        // Nonexistent path returns Ok(())
        rm_entry(dir.path().join("nonexistent_path"))?;

        Ok(())
    }

    #[test]
    fn test_copy_tree_single_file_and_directory() -> io::Result<()> {
        let dir = tempdir()?;
        let src_dir = dir.path().join("src");
        let dst_dir = dir.path().join("dst");

        fs::create_dir_all(src_dir.join("nested"))?;
        fs::write(src_dir.join("root.txt"), "hello")?;
        fs::write(src_dir.join("nested/inner.txt"), "world")?;

        copy_tree(&src_dir, &dst_dir)?;

        assert_eq!(fs::read_to_string(dst_dir.join("root.txt"))?, "hello");
        assert_eq!(
            fs::read_to_string(dst_dir.join("nested/inner.txt"))?,
            "world"
        );

        // Copy single file
        let single_dst = dir.path().join("single.txt");
        copy_tree(src_dir.join("root.txt"), &single_dst)?;
        assert_eq!(fs::read_to_string(single_dst)?, "hello");

        Ok(())
    }

    #[test]
    fn test_sync_managed_tree_and_preserve() -> io::Result<()> {
        let dir = tempdir()?;
        let src = dir.path().join("src");
        let dst = dir.path().join("dst");

        fs::create_dir_all(src.join("sub"))?;
        fs::write(src.join("file1.txt"), "v1")?;
        fs::write(src.join("sub/file2.txt"), "v2")?;

        fs::create_dir_all(dst.join("sub"))?;
        fs::write(dst.join("untracked.txt"), "extra")?;
        fs::write(dst.join("preserved.txt"), "keep_me")?;
        fs::write(dst.join("sub/preserved_nested.txt"), "keep_nested")?;

        let mut cache = SourceContentCache::new();
        let preserve = vec!["preserved.txt", "sub/preserved_nested.txt"];

        sync_managed_tree(&src, &dst, &preserve, Some(&mut cache))?;

        assert_eq!(fs::read_to_string(dst.join("file1.txt"))?, "v1");
        assert_eq!(fs::read_to_string(dst.join("sub/file2.txt"))?, "v2");
        assert_eq!(fs::read_to_string(dst.join("preserved.txt"))?, "keep_me");
        assert_eq!(
            fs::read_to_string(dst.join("sub/preserved_nested.txt"))?,
            "keep_nested"
        );
        // Untracked file removed
        assert!(!dst.join("untracked.txt").exists());

        // Second run with cache (idempotent)
        sync_managed_tree(&src, &dst, &preserve, Some(&mut cache))?;
        assert_eq!(fs::read_to_string(dst.join("file1.txt"))?, "v1");

        Ok(())
    }

    #[test]
    fn test_sync_managed_children_preserves_dst_extra() -> io::Result<()> {
        let dir = tempdir()?;
        let src = dir.path().join("src");
        let dst = dir.path().join("dst");

        fs::create_dir_all(&src)?;
        fs::write(src.join("from_src.txt"), "hello")?;

        fs::create_dir_all(&dst)?;
        fs::write(dst.join("extra_dst.txt"), "leave_alone")?;

        let preserve: &[&str] = &[];
        sync_managed_children(&src, &dst, preserve, None)?;

        assert_eq!(fs::read_to_string(dst.join("from_src.txt"))?, "hello");
        assert_eq!(
            fs::read_to_string(dst.join("extra_dst.txt"))?,
            "leave_alone"
        );

        Ok(())
    }

    #[test]
    fn test_sync_text_file_and_private_file_idempotency() -> io::Result<()> {
        let dir = tempdir()?;
        let target = dir.path().join("secret.cfg");

        let written = sync_private_text_file(&target, "my_secret_token\n")?;
        assert!(written);
        assert_eq!(fs::read_to_string(&target)?, "my_secret_token\n");

        #[cfg(unix)]
        {
            let meta = fs::metadata(&target)?;
            assert_eq!(meta.mode() & 0o777, 0o600);
        }

        // Idempotent second sync: should return false (not modified)
        let written_again = sync_private_text_file(&target, "my_secret_token\n")?;
        assert!(!written_again);

        // Updating content should atomically overwrite
        let updated = sync_private_text_file(&target, "new_secret_token\n")?;
        assert!(updated);
        assert_eq!(fs::read_to_string(&target)?, "new_secret_token\n");

        Ok(())
    }
}
