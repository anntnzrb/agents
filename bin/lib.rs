#!/usr/bin/env -S cargo -q -Zscript run --release --manifest-path
---cargo
[package]
edition = "2024"

[dependencies]
serde_json = "1"
wait-timeout = "0.2"
walkdir = "2"

[dev-dependencies]
tempfile = "3"

[lints.rust]
warnings = { level = "deny", priority = -2 }
future_incompatible = { level = "deny", priority = -1 }
rust_2018_idioms = { level = "deny", priority = -1 }
rust_2024_compatibility = { level = "deny", priority = -1 }
unused = { level = "deny", priority = -1 }
nonstandard_style = { level = "deny", priority = -1 }
unsafe_code = "forbid"
missing_docs = "deny"
missing_debug_implementations = "deny"
missing_copy_implementations = "deny"
unreachable_pub = "deny"
single_use_lifetimes = "deny"
private_interfaces = "deny"
private_bounds = "deny"
unused_crate_dependencies = "deny"

[lints.rustdoc]
all = "deny"
broken_intra_doc_links = "deny"
private_intra_doc_links = "deny"
missing_crate_level_docs = "deny"
private_doc_tests = "deny"
invalid_codeblock_attributes = "deny"
invalid_rust_codeblocks = "deny"
invalid_html_tags = "deny"
bare_urls = "deny"
unescaped_backticks = "deny"
redundant_explicit_links = "deny"
---

//! Sync runner entrypoint for syncing agent configs into tool homes.

use std::fs;
use std::io;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::thread;
use std::time::Duration;

use fs2::FileExt;
mod harness;
mod install;
mod jobs;
mod managed;
mod packages;

use harness::{HarnessId, SyncEnv};
use install::{command_exists, install_extension_deps, read_pipe};
#[cfg(test)]
use install::{iter_extension_packages, run_install};
#[cfg(test)]
use jobs::{copy_dir_into, copy_item};
use jobs::{iter_jobs, run_jobs};
use managed::{clean_managed_entries, plan_managed_entries, record_managed_entries};

const SYNC_TIMEOUT_ENV: &str = "AGENTS_SYNC_TIMEOUT_SECONDS";
const DEFAULT_SYNC_TIMEOUT_SECONDS: u64 = 15 * 60;
const SYNC_LOCK_FILE: &str = "sync.lock";

fn err(message: &str) {
    eprintln!("sync: {message}");
}

fn panic_message(payload: Box<dyn std::any::Any + Send>) -> String {
    if let Some(text) = payload.downcast_ref::<&str>() {
        return (*text).to_string();
    }
    if let Some(text) = payload.downcast_ref::<String>() {
        return text.clone();
    }
    "panic".to_string()
}

fn is_symlink(path: &Path) -> bool {
    fs::symlink_metadata(path)
        .map(|metadata| metadata.file_type().is_symlink())
        .unwrap_or(false)
}

fn rm_entry(path: &Path) -> io::Result<()> {
    let metadata = match fs::symlink_metadata(path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(()),
        Err(error) => return Err(error),
    };

    if metadata.file_type().is_symlink() {
        return fs::remove_file(path).or_else(ignore_not_found);
    }
    if metadata.is_dir() {
        return fs::remove_dir_all(path);
    }
    fs::remove_file(path).or_else(ignore_not_found)
}

fn ignore_not_found(error: io::Error) -> io::Result<()> {
    if error.kind() == io::ErrorKind::NotFound {
        Ok(())
    } else {
        Err(error)
    }
}

fn copy_tree(src: &Path, dst: &Path) -> io::Result<()> {
    let metadata = fs::metadata(src)?;
    if !metadata.is_dir() {
        if let Some(parent) = dst.parent() {
            fs::create_dir_all(parent)?;
        }
        fs::copy(src, dst)?;
        return Ok(());
    }

    fs::create_dir_all(dst)?;
    for entry_result in walkdir::WalkDir::new(src).follow_links(true).min_depth(1) {
        let entry = entry_result.map_err(io::Error::other)?;
        let relative = entry.path().strip_prefix(src).map_err(io::Error::other)?;
        let target = dst.join(relative);
        if entry.file_type().is_dir() {
            fs::create_dir_all(&target)?;
        } else {
            if let Some(parent) = target.parent() {
                fs::create_dir_all(parent)?;
            }
            fs::copy(entry.path(), &target)?;
        }
    }
    Ok(())
}

#[derive(Debug)]
struct SyncLock {
    _file: fs::File,
}

fn parse_timeout_seconds(value: Option<&str>, default_seconds: u64) -> Duration {
    value
        .and_then(|raw| raw.parse::<u64>().ok())
        .filter(|seconds| *seconds > 0)
        .map(Duration::from_secs)
        .unwrap_or_else(|| Duration::from_secs(default_seconds))
}

fn sync_timeout() -> Duration {
    parse_timeout_seconds(
        std::env::var(SYNC_TIMEOUT_ENV).ok().as_deref(),
        DEFAULT_SYNC_TIMEOUT_SECONDS,
    )
}

fn sync_lock_path(sync_env: &SyncEnv) -> PathBuf {
    sync_env.managed_state_home.join(SYNC_LOCK_FILE)
}

fn try_acquire_sync_lock(sync_env: &SyncEnv) -> Result<Option<SyncLock>, String> {
    fs::create_dir_all(&sync_env.managed_state_home).map_err(|error| {
        format!(
            "create sync state dir {} ({error})",
            sync_env.managed_state_home.display()
        )
    })?;

    let lock_path = sync_lock_path(sync_env);
    let mut file = std::fs::OpenOptions::new()
        .create(true)
        .read(true)
        .write(true)
        .truncate(false)
        .open(&lock_path)
        .map_err(|error| format!("open sync lock {} ({error})", lock_path.display()))?;

    match file.try_lock_exclusive() {
        Ok(()) => {
            file.set_len(0)
                .map_err(|error| format!("clear sync lock {} ({error})", lock_path.display()))?;
            writeln!(file, "pid={}", std::process::id())
                .map_err(|error| format!("write sync lock {} ({error})", lock_path.display()))?;
            Ok(Some(SyncLock { _file: file }))
        }
        Err(error) if error.kind() == io::ErrorKind::WouldBlock => Ok(None),
        Err(error) => Err(format!("lock sync {} ({error})", lock_path.display())),
    }
}

fn start_sync_watchdog(timeout: Duration) {
    let _ = thread::spawn(move || {
        thread::sleep(timeout);
        err(&format!("timed out after {}s", timeout.as_secs()));
        std::process::exit(124);
    });
}

fn run_sync(sync_env: &SyncEnv) -> bool {
    let managed_plan = match plan_managed_entries(sync_env) {
        Ok(plan) => plan,
        Err(message) => {
            err(&message);
            return false;
        }
    };

    let cleanup_success = clean_managed_entries(&managed_plan);
    let base_success = if cleanup_success {
        match iter_jobs(sync_env) {
            Ok(jobs) => run_jobs(&jobs),
            Err(message) => {
                err(&message);
                false
            }
        }
    } else {
        false
    };
    let managed_state_success = if base_success {
        record_managed_entries(&managed_plan)
    } else {
        true
    };
    let post_sync_ready = base_success && managed_state_success;
    let package_success = if post_sync_ready {
        packages::bootstrap_packages(sync_env)
    } else {
        true
    };
    let install_success = if post_sync_ready {
        sync_env
            .harness(HarnessId::Pi)
            .map(|harness| {
                install_extension_deps(&harness.root().join("extensions"), sync_env.install_timeout)
            })
            .unwrap_or(true)
    } else {
        true
    };

    base_success && managed_state_success && package_success && install_success
}

pub(crate) fn main() -> std::process::ExitCode {
    let sync_env = match SyncEnv::from_system() {
        Ok(sync_env) => sync_env,
        Err(message) => {
            err(&message);
            return std::process::ExitCode::from(1);
        }
    };

    let _lock = match try_acquire_sync_lock(&sync_env) {
        Ok(Some(lock)) => lock,
        Ok(None) => {
            err("another sync is already running; skipping");
            return std::process::ExitCode::from(0);
        }
        Err(message) => {
            err(&message);
            return std::process::ExitCode::from(1);
        }
    };

    start_sync_watchdog(sync_timeout());
    std::process::ExitCode::from(if run_sync(&sync_env) { 0 } else { 1 })
}

#[cfg(test)]
#[path = "tests.rs"]
mod tests;
