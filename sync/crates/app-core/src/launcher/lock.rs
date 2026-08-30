use std::fs::{self, OpenOptions};
use std::io::{self, Write};
use std::path::{Path, PathBuf};
use std::thread;
use std::time::{Duration, Instant};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum LockError {
    #[error("timed out waiting for package cache lock: {0}")]
    Timeout(PathBuf),
    #[error("I/O error at {path}: {source}")]
    Io {
        path: PathBuf,
        #[source]
        source: io::Error,
    },
}

#[derive(Debug)]
pub struct AdvisoryCacheLock {
    lock_file: PathBuf,
}

impl Drop for AdvisoryCacheLock {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.lock_file);
    }
}

/// Attempts to acquire an advisory file lock exclusively without blocking.
#[must_use]
pub fn try_acquire_cache_lock(lock_file: &Path) -> Option<AdvisoryCacheLock> {
    if let Some(parent) = lock_file.parent()
        && fs::create_dir_all(parent).is_err()
    {
        return None;
    }

    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(lock_file)
        .ok()?;

    let pid = std::process::id();
    let _ = writeln!(file, "{pid}");

    Some(AdvisoryCacheLock {
        lock_file: lock_file.to_path_buf(),
    })
}

/// Acquires an advisory file lock, polling every 25ms until acquired or the timeout expires.
pub fn acquire_cache_lock(
    lock_file: &Path,
    timeout: Duration,
) -> Result<AdvisoryCacheLock, LockError> {
    let start = Instant::now();
    let poll_interval = Duration::from_millis(25);

    loop {
        if let Some(lock) = try_acquire_cache_lock(lock_file) {
            return Ok(lock);
        }

        if start.elapsed() >= timeout {
            return Err(LockError::Timeout(lock_file.to_path_buf()));
        }

        thread::sleep(poll_interval);
    }
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
    fn test_acquire_and_release_lock() {
        let tmp = tempdir().unwrap();
        let lock_file = tmp.path().join("test.lock");

        let lock1 = acquire_cache_lock(&lock_file, Duration::from_millis(500));
        assert!(lock1.is_ok());

        // While locked, another acquire with short timeout should fail
        let lock2 = acquire_cache_lock(&lock_file, Duration::from_millis(50));
        assert!(matches!(lock2, Err(LockError::Timeout(_))));

        // Dropping lock1 frees the lock
        drop(lock1);

        let lock3 = acquire_cache_lock(&lock_file, Duration::from_millis(500));
        assert!(lock3.is_ok());
    }
}
