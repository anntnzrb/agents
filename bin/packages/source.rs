use std::io;
use std::path::{Path, PathBuf};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use super::process::run_command;

pub(super) fn package_cache_dir(cache_root: &Path, source: &str) -> PathBuf {
    let slug = source_slug(source);
    cache_root.join(format!("{slug}-{:016x}", fnv1a64(source)))
}

pub(super) fn staging_dir_for(final_dir: &Path) -> PathBuf {
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    let pid = std::process::id();
    final_dir.with_extension(format!("staging-{pid}-{now}"))
}

pub(super) fn replace_dir_atomically(src: &Path, dst: &Path) -> io::Result<()> {
    let backup = dst.with_extension("backup");
    super::super::rm_entry(&backup)?;
    if dst.exists() {
        std::fs::rename(dst, &backup)?;
    }
    match std::fs::rename(src, dst) {
        Ok(()) => {
            let _ = super::super::rm_entry(&backup);
            Ok(())
        }
        Err(error) => {
            if backup.exists() {
                let _ = std::fs::rename(&backup, dst);
            }
            Err(error)
        }
    }
}

pub(super) fn clone_package(source: &str, target_dir: &Path, timeout: Duration) -> bool {
    clone_package_with_runner(
        source,
        target_dir,
        super::super::command_exists("gh"),
        |command| run_command(command, None, timeout, "clone"),
    )
}

fn source_slug(source: &str) -> String {
    let trimmed = source.trim().trim_end_matches('/');
    let normalized = trimmed.strip_suffix(".git").unwrap_or(trimmed);
    let tail = normalized
        .split(['/', ':'])
        .filter(|part| !part.is_empty())
        .rev()
        .take(2)
        .collect::<Vec<_>>();
    let joined = if tail.is_empty() {
        "package".to_string()
    } else {
        tail.into_iter().rev().collect::<Vec<_>>().join("-")
    };

    let sanitized = joined
        .chars()
        .map(|ch| {
            if ch.is_ascii_alphanumeric() {
                ch.to_ascii_lowercase()
            } else {
                '-'
            }
        })
        .collect::<String>();
    let compact = sanitized
        .split('-')
        .filter(|part| !part.is_empty())
        .collect::<Vec<_>>()
        .join("-");
    if compact.is_empty() {
        "package".to_string()
    } else {
        compact
    }
}

fn fnv1a64(input: &str) -> u64 {
    let mut hash = 0xcbf29ce484222325_u64;
    for byte in input.as_bytes() {
        hash ^= u64::from(*byte);
        hash = hash.wrapping_mul(0x100000001b3);
    }
    hash
}

fn clone_package_with_runner<F>(
    source: &str,
    target_dir: &Path,
    gh_available: bool,
    mut runner: F,
) -> bool
where
    F: FnMut(&[String]) -> bool,
{
    for command in clone_commands(source, target_dir, gh_available) {
        if runner(&command) {
            return true;
        }
    }
    false
}

fn clone_commands(source: &str, target_dir: &Path, gh_available: bool) -> Vec<Vec<String>> {
    let mut commands = Vec::new();
    if let Some(slug) = github_repo_slug(source).filter(|_| gh_available) {
        commands.push(vec![
            "gh".to_string(),
            "repo".to_string(),
            "clone".to_string(),
            slug,
            target_dir.to_string_lossy().to_string(),
            "--".to_string(),
            "--depth=1".to_string(),
        ]);
    }
    commands.push(vec![
        "git".to_string(),
        "clone".to_string(),
        "--depth=1".to_string(),
        source.to_string(),
        target_dir.to_string_lossy().to_string(),
    ]);
    commands
}

fn github_repo_slug(source: &str) -> Option<String> {
    let trimmed = source.trim();
    let normalized = trimmed.strip_suffix(".git").unwrap_or(trimmed);
    if let Some(rest) = normalized.strip_prefix("https://github.com/") {
        return split_owner_repo(rest);
    }
    if let Some(rest) = normalized.strip_prefix("http://github.com/") {
        return split_owner_repo(rest);
    }
    if let Some(rest) = normalized.strip_prefix("git@github.com:") {
        return split_owner_repo(rest);
    }
    None
}

fn split_owner_repo(rest: &str) -> Option<String> {
    let parts = rest
        .split('/')
        .filter(|part| !part.is_empty())
        .take(2)
        .collect::<Vec<_>>();
    if parts.len() != 2 {
        return None;
    }
    Some(format!("{}/{}", parts[0], parts[1]))
}

#[cfg(test)]
pub(super) fn github_slug_for_tests(source: &str) -> Option<String> {
    github_repo_slug(source)
}

#[cfg(test)]
pub(super) fn command_for_tests(source: &str, target_dir: &Path) -> Vec<String> {
    clone_commands(source, target_dir, true)
        .into_iter()
        .next()
        .unwrap_or_else(|| panic!("missing clone command"))
}

#[cfg(test)]
pub(super) fn clone_attempts_for_tests(
    source: &str,
    target_dir: &Path,
    gh_available: bool,
    outcomes: &[bool],
) -> (bool, Vec<Vec<String>>) {
    let mut attempts = Vec::new();
    let mut outcomes = outcomes.iter().copied();
    let result = clone_package_with_runner(source, target_dir, gh_available, |command| {
        attempts.push(command.to_vec());
        outcomes.next().unwrap_or(false)
    });
    (result, attempts)
}
