use std::fs;
use std::io::{self, Read};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::thread;
use std::time::{Duration, Instant};

use super::PackageError;
use super::validate::missing_package_roots;

/// The outcome of running a subprocess command.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CommandOutcome {
    Success,
    MissingCommand,
    Failure { detail: String },
    TimedOut,
}

/// Locates a viable Bun runner executable from the environment or PATH.
#[must_use]
pub fn pick_bun_runner() -> Option<PathBuf> {
    if let Ok(bun_path) = std::env::var("BUN_PATH") {
        let p = PathBuf::from(bun_path);
        if p.is_file() {
            return Some(p);
        }
    }
    if let Ok(path) = std::env::var("PATH") {
        for dir in std::env::split_paths(&path) {
            let candidate = dir.join("bun");
            if candidate.is_file() {
                return Some(candidate);
            }
        }
    }
    None
}

/// Formats the error detail from standard output and standard error.
fn detail_from_output(stdout: &str, stderr: &str) -> String {
    let err_trimmed = stderr.trim();
    if !err_trimmed.is_empty() {
        return err_trimmed.to_owned();
    }
    let out_trimmed = stdout.trim();
    if !out_trimmed.is_empty() {
        return out_trimmed.to_owned();
    }
    "unknown error".to_owned()
}

/// Executes a subprocess command with explicit arguments and a hard deadline timeout.
#[must_use]
pub fn run_command_outcome(
    command: &[&str],
    cwd: Option<&Path>,
    timeout: Duration,
) -> CommandOutcome {
    let Some(executable) = command.first() else {
        return CommandOutcome::MissingCommand;
    };

    let mut cmd = Command::new(executable);
    let args: Vec<&str> = command.iter().skip(1).copied().collect();
    cmd.args(args);

    if let Some(dir) = cwd {
        cmd.current_dir(dir);
    }
    cmd.stdin(Stdio::null());
    cmd.stdout(Stdio::piped());
    cmd.stderr(Stdio::piped());

    let mut child = match cmd.spawn() {
        Ok(c) => c,
        Err(err) if err.kind() == io::ErrorKind::NotFound => return CommandOutcome::MissingCommand,
        Err(err) => {
            return CommandOutcome::Failure {
                detail: err.to_string(),
            };
        }
    };

    let mut stdout_handle = child.stdout.take();
    let mut stderr_handle = child.stderr.take();

    let stdout_thread = thread::spawn(move || {
        let mut stdout_bytes = Vec::new();
        if let Some(out) = &mut stdout_handle {
            let _ = out.read_to_end(&mut stdout_bytes);
        }
        stdout_bytes
    });

    let stderr_thread = thread::spawn(move || {
        let mut stderr_bytes = Vec::new();
        if let Some(err) = &mut stderr_handle {
            let _ = err.read_to_end(&mut stderr_bytes);
        }
        stderr_bytes
    });

    let start = Instant::now();
    let mut exit_status = None;

    loop {
        match child.try_wait() {
            Ok(Some(status)) => {
                exit_status = Some(Ok(status));
                break;
            }
            Ok(None) => {
                if start.elapsed() >= timeout {
                    break;
                }
                let remaining = timeout.saturating_sub(start.elapsed());
                let sleep_time = remaining.min(Duration::from_millis(5));
                if sleep_time.is_zero() {
                    break;
                }
                thread::sleep(sleep_time);
            }
            Err(err) => {
                exit_status = Some(Err(err));
                break;
            }
        }
    }

    let Some(status_res) = exit_status else {
        let _ = child.kill();
        let _ = child.wait();
        let _ = stdout_thread.join();
        let _ = stderr_thread.join();
        return CommandOutcome::TimedOut;
    };

    match status_res {
        Ok(status) => {
            let stdout_bytes = stdout_thread.join().unwrap_or_default();
            let stderr_bytes = stderr_thread.join().unwrap_or_default();
            if status.success() {
                CommandOutcome::Success
            } else {
                let stdout_str = String::from_utf8_lossy(&stdout_bytes);
                let stderr_str = String::from_utf8_lossy(&stderr_bytes);
                CommandOutcome::Failure {
                    detail: detail_from_output(&stdout_str, &stderr_str),
                }
            }
        }
        Err(err) => {
            let _ = child.kill();
            let _ = child.wait();
            let _ = stdout_thread.join();
            let _ = stderr_thread.join();
            CommandOutcome::Failure {
                detail: err.to_string(),
            }
        }
    }
}

/// Logs a subprocess failure to standard error matching legacy sync formatting.
pub fn log_command_failure(command: &[&str], action: &str, outcome: &CommandOutcome) {
    match outcome {
        CommandOutcome::Success => {}
        CommandOutcome::MissingCommand => {
            let exec = command.first().copied().unwrap_or("");
            eprintln!("sync: missing command for {action}: {exec}");
        }
        CommandOutcome::Failure { detail } => {
            let cmd_str = command.join(" ");
            eprintln!("sync: {action} failed: {cmd_str} ({detail})");
        }
        CommandOutcome::TimedOut => {
            let cmd_str = command.join(" ");
            eprintln!("sync: {action} timed out: {cmd_str}");
        }
    }
}

/// Ensures a minimal `package.json` exists in the target directory.
pub fn ensure_install_project(dir: &Path) -> Result<bool, PackageError> {
    let pkg_json = dir.join("package.json");
    if pkg_json.exists() {
        return Ok(true);
    }
    fs::write(
        &pkg_json,
        "{\n  \"name\": \"pi-extension-deps\",\n  \"private\": true\n}\n",
    )?;
    Ok(true)
}

/// Installs declared dependencies in a package directory using Bun.
pub fn install_package_deps(
    dir: &Path,
    timeout_ms: u64,
    runner: Option<&Path>,
) -> Result<bool, PackageError> {
    let package_json_path = dir.join("package.json");
    if !package_json_path.is_file() {
        return Ok(true);
    }

    let runner_buf;
    let bun = if let Some(r) = runner {
        r
    } else if let Some(r) = pick_bun_runner() {
        runner_buf = r;
        &runner_buf
    } else {
        eprintln!(
            "sync: bun is required for dependency install in {}",
            dir.display()
        );
        return Ok(false);
    };

    let bun_str = bun.to_str().unwrap_or("bun");
    let cmd = [bun_str, "install"];
    let timeout = Duration::from_millis(timeout_ms);
    let outcome = run_command_outcome(&cmd, Some(dir), timeout);
    if outcome != CommandOutcome::Success {
        log_command_failure(&cmd, "install", &outcome);
        return Ok(false);
    }

    install_inferred_import_packages(dir, timeout_ms, dir, runner)
}

/// Installs missing dependencies inferred from imported specifiers in source files.
pub fn install_inferred_import_packages(
    dir: &Path,
    timeout_ms: u64,
    source_dir: &Path,
    runner: Option<&Path>,
) -> Result<bool, PackageError> {
    let missing = missing_package_roots(source_dir)?;
    if missing.is_empty() {
        return Ok(true);
    }

    if !ensure_install_project(dir)? {
        return Ok(false);
    }

    let runner_buf;
    let bun = if let Some(r) = runner {
        r
    } else if let Some(r) = pick_bun_runner() {
        runner_buf = r;
        &runner_buf
    } else {
        eprintln!(
            "sync: bun is required for inferred imports in {}",
            dir.display()
        );
        return Ok(false);
    };

    let bun_str = bun.to_str().unwrap_or("bun");
    let mut command: Vec<&str> = vec![bun_str, "add", "--no-save"];
    for pkg in &missing {
        command.push(pkg.as_str());
    }

    let timeout = Duration::from_millis(timeout_ms);
    let outcome = run_command_outcome(&command, Some(dir), timeout);
    if outcome == CommandOutcome::Success {
        Ok(true)
    } else {
        log_command_failure(&command, "install inferred packages", &outcome);
        Ok(false)
    }
}

/// Executes a package build script via Bun.
pub fn run_package_build(
    dir: &Path,
    timeout_ms: u64,
    runner: Option<&Path>,
) -> Result<bool, PackageError> {
    let runner_buf;
    let bun = if let Some(r) = runner {
        r
    } else if let Some(r) = pick_bun_runner() {
        runner_buf = r;
        &runner_buf
    } else {
        eprintln!("sync: bun is required for build in {}", dir.display());
        return Ok(false);
    };

    let bun_str = bun.to_str().unwrap_or("bun");
    let cmd = [bun_str, "run", "build"];
    let timeout = Duration::from_millis(timeout_ms);
    let outcome = run_command_outcome(&cmd, Some(dir), timeout);
    if outcome == CommandOutcome::Success {
        Ok(true)
    } else {
        log_command_failure(&cmd, "build", &outcome);
        Ok(false)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn test_ensure_install_project_creates_package_json() {
        let dir = tempdir().unwrap();
        let pkg_path = dir.path().join("package.json");
        assert!(!pkg_path.exists());

        assert!(ensure_install_project(dir.path()).unwrap());
        assert!(pkg_path.exists());
        let content = fs::read_to_string(&pkg_path).unwrap();
        assert!(content.contains("pi-extension-deps"));
    }

    #[test]
    fn test_run_command_outcome_missing_command() {
        let outcome = run_command_outcome(
            &["non_existent_binary_xyz_123"],
            None,
            Duration::from_millis(500),
        );
        assert_eq!(outcome, CommandOutcome::MissingCommand);
    }

    #[test]
    fn test_run_command_outcome_success() {
        let outcome = run_command_outcome(&["echo", "hello"], None, Duration::from_millis(1000));
        assert_eq!(outcome, CommandOutcome::Success);
    }

    #[test]
    #[cfg(unix)]
    fn test_run_command_outcome_terminates_timed_out_process() {
        let dir = tempdir().unwrap();
        let marker = dir.path().join("marker.txt");
        let script = format!("sleep 0.15 && touch '{}'", marker.display());
        let outcome = run_command_outcome(&["sh", "-c", &script], None, Duration::from_millis(30));
        assert_eq!(outcome, CommandOutcome::TimedOut);

        thread::sleep(Duration::from_millis(250));
        assert!(
            !marker.exists(),
            "timed-out subprocess was not terminated and created marker file"
        );
    }
}
