use std::fs::{self, File, OpenOptions};
use std::io::{self, Write};
use std::path::{Path, PathBuf};
use thiserror::Error;

#[cfg(unix)]
use std::os::unix::io::AsRawFd;

/// Errors that can occur during synchronization lock operations.
#[derive(Debug, Error)]
pub enum LockError {
    #[error("create sync state dir {dir}: {source}")]
    CreateStateDir {
        dir: PathBuf,
        #[source]
        source: io::Error,
    },

    #[error("open sync lock {path}: {source}")]
    OpenLock {
        path: PathBuf,
        #[source]
        source: io::Error,
    },

    #[error("lock sync {path} ({message})")]
    AcquireLock { path: PathBuf, message: String },

    #[error("clear sync lock {path}: {source}")]
    ClearLock {
        path: PathBuf,
        #[source]
        source: io::Error,
    },

    #[error("write sync lock {path}: {source}")]
    WriteLock {
        path: PathBuf,
        #[source]
        source: io::Error,
    },

    #[error("io error: {0}")]
    Io(#[from] io::Error),
}

/// An active, exclusively held synchronization lock.
///
/// When dropped, the lock is automatically released (flock unlocked and file descriptor closed).
#[derive(Debug)]
pub struct SyncLock {
    file: Option<File>,
    path: PathBuf,
}

impl SyncLock {
    /// Returns the path to the held lock file.
    #[must_use]
    pub fn lock_path(&self) -> &Path {
        &self.path
    }

    /// Explicitly releases the lock immediately.
    pub fn release(mut self) {
        self.unlock_internal();
    }

    fn unlock_internal(&mut self) {
        if let Some(file) = self.file.take() {
            #[cfg(unix)]
            {
                let fd = file.as_raw_fd();
                unsafe {
                    libc::flock(fd, libc::LOCK_UN);
                }
            }
            drop(file);
        }
    }
}

impl Drop for SyncLock {
    fn drop(&mut self) {
        self.unlock_internal();
    }
}

/// Attempts to non-blockingly acquire an exclusive POSIX sync lock on `lock_path`.
///
/// Ensures `state_dir` exists. If another process holds the lock, returns `Ok(None)`.
/// If successfully acquired, truncates the file, writes the current process PID marker (`pid={pid}\n`),
/// and returns `Ok(Some(SyncLock))`.
pub fn try_acquire_sync_lock(
    state_dir: impl AsRef<Path>,
    lock_path: impl AsRef<Path>,
) -> Result<Option<SyncLock>, LockError> {
    let state_dir = state_dir.as_ref();
    let lock_path = lock_path.as_ref();

    if let Err(source) = fs::create_dir_all(state_dir) {
        return Err(LockError::CreateStateDir {
            dir: state_dir.to_path_buf(),
            source,
        });
    }

    let file = match OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(lock_path)
    {
        Ok(f) => f,
        Err(source) => {
            return Err(LockError::OpenLock {
                path: lock_path.to_path_buf(),
                source,
            });
        }
    };

    #[cfg(unix)]
    {
        let fd = file.as_raw_fd();
        let ret = unsafe { libc::flock(fd, libc::LOCK_EX | libc::LOCK_NB) };
        if ret != 0 {
            let err = io::Error::last_os_error();
            let raw = err.raw_os_error();
            if raw == Some(libc::EAGAIN) || raw == Some(libc::EWOULDBLOCK) {
                return Ok(None);
            }
            return Err(LockError::AcquireLock {
                path: lock_path.to_path_buf(),
                message: format!("{} (os error {})", err, raw.unwrap_or(0)),
            });
        }
    }

    if let Err(source) = file.set_len(0) {
        return Err(LockError::ClearLock {
            path: lock_path.to_path_buf(),
            source,
        });
    }

    let mut file = file;
    let pid_marker = format!("pid={}\n", std::process::id());
    if let Err(source) = file.write_all(pid_marker.as_bytes()) {
        return Err(LockError::WriteLock {
            path: lock_path.to_path_buf(),
            source,
        });
    }
    if let Err(source) = file.flush() {
        return Err(LockError::WriteLock {
            path: lock_path.to_path_buf(),
            source,
        });
    }

    Ok(Some(SyncLock {
        file: Some(file),
        path: lock_path.to_path_buf(),
    }))
}

/// Releases the given `SyncLock` by consuming it.
pub fn release_sync_lock(lock: SyncLock) {
    lock.release();
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
    fn test_acquire_and_release_lock() -> Result<(), Box<dyn std::error::Error>> {
        let dir = tempdir()?;
        let lock_path = dir.path().join("test.lock");

        // First acquire should succeed
        let lock1 = try_acquire_sync_lock(dir.path(), &lock_path)?;
        assert!(lock1.is_some());
        let lock1 = lock1.unwrap();

        // Lock file should contain pid marker
        let content = fs::read_to_string(&lock_path)?;
        assert!(content.starts_with("pid="));

        // Second acquire on the same path while lock1 is held should return None (contention)
        let lock2 = try_acquire_sync_lock(dir.path(), &lock_path)?;
        assert!(lock2.is_none());

        // Release first lock
        release_sync_lock(lock1);

        // Third acquire should now succeed
        let lock3 = try_acquire_sync_lock(dir.path(), &lock_path)?;
        assert!(lock3.is_some());

        // Drop RAII test: lock drops here
        drop(lock3);

        // Fourth acquire after drop should succeed
        let lock4 = try_acquire_sync_lock(dir.path(), &lock_path)?;
        assert!(lock4.is_some());

        Ok(())
    }

    #[test]
    fn test_lock_state_dir_error() {
        let dir = tempdir().unwrap();
        // Create a regular file where a directory is expected
        let file_blocking_dir = dir.path().join("file_blocking_dir");
        fs::write(&file_blocking_dir, "blocking").unwrap();

        let lock_path = file_blocking_dir.join("sub").join("test.lock");
        let result = try_acquire_sync_lock(file_blocking_dir.join("sub"), &lock_path);
        assert!(result.is_err());
        match result.unwrap_err() {
            LockError::CreateStateDir { dir: _, source: _ } => {}
            other => panic!("expected CreateStateDir error, got {other:?}"),
        }
    }
}
