use std::fs;
use std::io;
use std::path::Path;
use std::process::{Command, Stdio};
use std::thread;
use std::time::Duration;

use wait_timeout::ChildExt;

use super::super::{command_exists, err, read_pipe};
use super::validate::missing_package_roots;

pub(super) fn install_package_deps(dir: &Path, timeout: Duration) -> bool {
    if !dir.join("package.json").is_file() {
        return true;
    }
    let Some(tool) = js_runner() else {
        err(&format!(
            "no JS package manager available for {}",
            dir.display()
        ));
        return false;
    };
    let install_command = vec![tool.to_string(), "install".to_string()];
    if !run_command(&install_command, Some(dir), timeout, "install") {
        return false;
    }
    install_inferred_import_packages(dir, timeout)
}

pub(super) fn install_inferred_import_packages(dir: &Path, timeout: Duration) -> bool {
    let missing = match missing_package_roots(dir) {
        Ok(missing) => missing,
        Err(message) => {
            err(&format!(
                "dependency scan failed in {}: {message}",
                dir.display()
            ));
            return false;
        }
    };
    if missing.is_empty() {
        return true;
    }
    if !ensure_install_project(dir) {
        return false;
    }

    let Some(tool) = js_runner() else {
        err(&format!(
            "no JS package manager available for inferred imports in {}",
            dir.display()
        ));
        return false;
    };
    let command = inferred_install_command(tool, &missing);
    let outcome = run_command_outcome(&command, Some(dir), timeout);
    match inferred_install_step(tool, command_exists("npm"), &outcome) {
        InferredInstallStep::Done => true,
        InferredInstallStep::RetryWithNpm => {
            err(&format!(
                "retrying inferred package install with npm in {} after bun resolution failed",
                dir.display()
            ));
            let fallback = inferred_install_command("npm", &missing);
            let fallback_outcome = run_command_outcome(&fallback, Some(dir), timeout);
            if fallback_outcome.succeeded() {
                return true;
            }
            log_command_failure(
                &fallback,
                "install inferred packages via npm fallback",
                &fallback_outcome,
            );
            false
        }
        InferredInstallStep::ReportPrimaryFailure => {
            log_command_failure(&command, "install inferred packages", &outcome);
            false
        }
    }
}

pub(super) fn run_package_build(dir: &Path, timeout: Duration) -> bool {
    let Some(tool) = js_runner() else {
        err(&format!(
            "no JS runtime available for build in {}",
            dir.display()
        ));
        return false;
    };
    let command = vec![tool.to_string(), "run".to_string(), "build".to_string()];
    run_command(&command, Some(dir), timeout, "build")
}

#[derive(Debug, PartialEq, Eq)]
enum CommandOutcome {
    Success,
    MissingCommand,
    Failure(String),
    TimedOut,
}

impl CommandOutcome {
    fn succeeded(&self) -> bool {
        matches!(self, Self::Success)
    }
}

#[derive(Debug, PartialEq, Eq)]
enum InferredInstallStep {
    Done,
    RetryWithNpm,
    ReportPrimaryFailure,
}

fn inferred_install_step(
    tool: &str,
    npm_available: bool,
    outcome: &CommandOutcome,
) -> InferredInstallStep {
    if outcome.succeeded() {
        return InferredInstallStep::Done;
    }
    if tool == "bun" && npm_available {
        return InferredInstallStep::RetryWithNpm;
    }
    InferredInstallStep::ReportPrimaryFailure
}

pub(super) fn run_command(
    command: &[String],
    cwd: Option<&Path>,
    timeout: Duration,
    action: &str,
) -> bool {
    let outcome = run_command_outcome(command, cwd, timeout);
    if outcome.succeeded() {
        return true;
    }
    log_command_failure(command, action, &outcome);
    false
}

fn run_command_outcome(
    command: &[String],
    cwd: Option<&Path>,
    timeout: Duration,
) -> CommandOutcome {
    let mut child = match Command::new(&command[0])
        .args(&command[1..])
        .current_dir(cwd.unwrap_or_else(|| Path::new(".")))
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
    {
        Ok(child) => child,
        Err(error) if error.kind() == io::ErrorKind::NotFound => {
            return CommandOutcome::MissingCommand;
        }
        Err(error) => panic!("{error}"),
    };

    let stdout = child
        .stdout
        .take()
        .unwrap_or_else(|| panic!("missing stdout pipe for {}", command[0]));
    let stderr = child
        .stderr
        .take()
        .unwrap_or_else(|| panic!("missing stderr pipe for {}", command[0]));
    let stdout_handle = thread::spawn(move || read_pipe(stdout));
    let stderr_handle = thread::spawn(move || read_pipe(stderr));

    match child.wait_timeout(timeout) {
        Ok(Some(status)) => {
            let stdout_text =
                String::from_utf8_lossy(&stdout_handle.join().unwrap_or_default()).into_owned();
            let stderr_text =
                String::from_utf8_lossy(&stderr_handle.join().unwrap_or_default()).into_owned();
            if status.success() {
                return CommandOutcome::Success;
            }
            let detail = if !stderr_text.trim().is_empty() {
                stderr_text.trim().to_string()
            } else if !stdout_text.trim().is_empty() {
                stdout_text.trim().to_string()
            } else {
                "unknown error".to_string()
            };
            CommandOutcome::Failure(detail)
        }
        Ok(None) => {
            let _ = child.kill();
            let _ = child.wait();
            let _ = stdout_handle.join();
            let _ = stderr_handle.join();
            CommandOutcome::TimedOut
        }
        Err(error) => panic!("{error}"),
    }
}

fn log_command_failure(command: &[String], action: &str, outcome: &CommandOutcome) {
    match outcome {
        CommandOutcome::Success => {}
        CommandOutcome::MissingCommand => {
            err(&format!("missing command for {action}: {}", command[0]));
        }
        CommandOutcome::Failure(detail) => {
            err(&format!(
                "{action} failed: {} ({detail})",
                command.join(" ")
            ));
        }
        CommandOutcome::TimedOut => {
            err(&format!("{action} timed out: {}", command.join(" ")));
        }
    }
}

fn js_runner() -> Option<&'static str> {
    if command_exists("bun") {
        return Some("bun");
    }
    if command_exists("npm") {
        return Some("npm");
    }
    None
}

fn inferred_install_command(tool: &str, missing: &[String]) -> Vec<String> {
    if tool == "bun" {
        let mut command = vec![tool.to_string(), "add".to_string(), "--no-save".to_string()];
        command.extend(missing.iter().cloned());
        return command;
    }

    let mut command = vec![
        tool.to_string(),
        "install".to_string(),
        "--no-save".to_string(),
    ];
    command.extend(missing.iter().cloned());
    command
}

fn ensure_install_project(dir: &Path) -> bool {
    let package_json = dir.join("package.json");
    if package_json.is_file() {
        return true;
    }
    match fs::write(
        &package_json,
        "{\n  \"name\": \"pi-extension-deps\",\n  \"private\": true\n}\n",
    ) {
        Ok(()) => true,
        Err(error) => {
            err(&format!("write {} ({error})", package_json.display()));
            false
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{CommandOutcome, InferredInstallStep, inferred_install_step};

    #[test]
    fn successful_inferred_install_stops_after_first_attempt() {
        assert_eq!(
            inferred_install_step("bun", true, &CommandOutcome::Success),
            InferredInstallStep::Done
        );
    }

    #[test]
    fn bun_failure_retries_with_npm_when_available() {
        assert_eq!(
            inferred_install_step(
                "bun",
                true,
                &CommandOutcome::Failure("bun add failed".to_string()),
            ),
            InferredInstallStep::RetryWithNpm
        );
    }

    #[test]
    fn bun_failure_reports_when_npm_is_unavailable() {
        assert_eq!(
            inferred_install_step(
                "bun",
                false,
                &CommandOutcome::Failure("bun add failed".to_string()),
            ),
            InferredInstallStep::ReportPrimaryFailure
        );
    }

    #[test]
    fn non_bun_failure_does_not_retry_with_npm() {
        assert_eq!(
            inferred_install_step(
                "npm",
                true,
                &CommandOutcome::Failure("npm install failed".to_string()),
            ),
            InferredInstallStep::ReportPrimaryFailure
        );
    }
}
