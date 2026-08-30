use std::collections::BTreeMap;
use std::io::{self, Read};
use std::path::Path;
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum RunnerError {
    #[error("command execution error: {0}")]
    Io(#[from] io::Error),
    #[error("command list is empty")]
    EmptyCommand,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CommandStdio {
    Pipe,
    Inherit,
}

#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct LauncherProcessResult {
    pub exit_code: i32,
    pub stdout: String,
    pub stderr: String,
    pub timed_out: bool,
}

impl LauncherProcessResult {
    #[must_use]
    pub const fn success(stdout: String) -> Self {
        Self {
            exit_code: 0,
            stdout,
            stderr: String::new(),
            timed_out: false,
        }
    }

    #[must_use]
    pub const fn failure(exit_code: i32, stderr: String) -> Self {
        Self {
            exit_code,
            stdout: String::new(),
            stderr,
            timed_out: false,
        }
    }

    #[must_use]
    pub fn timeout() -> Self {
        Self {
            exit_code: 124,
            stdout: String::new(),
            stderr: String::from("command timed out"),
            timed_out: true,
        }
    }

    #[must_use]
    pub fn detail(&self) -> &str {
        if !self.stderr.trim().is_empty() {
            self.stderr.trim()
        } else if !self.stdout.trim().is_empty() {
            self.stdout.trim()
        } else {
            "unknown error"
        }
    }
}

pub trait ProcessRunner: Send + Sync {
    fn run(
        &self,
        command: &[String],
        cwd: Option<&Path>,
        timeout: Option<Duration>,
        stdio: CommandStdio,
        env: Option<&BTreeMap<String, String>>,
    ) -> Result<LauncherProcessResult, RunnerError>;
}

#[derive(Debug, Default)]
pub struct DefaultProcessRunner;

impl ProcessRunner for DefaultProcessRunner {
    fn run(
        &self,
        command: &[String],
        cwd: Option<&Path>,
        timeout: Option<Duration>,
        stdio: CommandStdio,
        env: Option<&BTreeMap<String, String>>,
    ) -> Result<LauncherProcessResult, RunnerError> {
        let Some((program, args)) = command.split_first() else {
            return Err(RunnerError::EmptyCommand);
        };

        let mut cmd = Command::new(program);
        cmd.args(args);

        if let Some(dir) = cwd {
            cmd.current_dir(dir);
        }

        if let Some(env_vars) = env {
            for (k, v) in env_vars {
                cmd.env(k, v);
            }
        }

        match stdio {
            CommandStdio::Pipe => {
                cmd.stdin(Stdio::null());
                cmd.stdout(Stdio::piped());
                cmd.stderr(Stdio::piped());
            }
            CommandStdio::Inherit => {
                cmd.stdin(Stdio::inherit());
                cmd.stdout(Stdio::inherit());
                cmd.stderr(Stdio::inherit());
            }
        }

        let mut child = match cmd.spawn() {
            Ok(c) => c,
            Err(err) => {
                return Ok(LauncherProcessResult {
                    exit_code: 127,
                    stdout: String::new(),
                    stderr: err.to_string(),
                    timed_out: false,
                });
            }
        };

        let start = Instant::now();
        let poll_delay = Duration::from_millis(10);

        loop {
            match child.try_wait() {
                Ok(Some(status)) => {
                    let exit_code = status.code().unwrap_or(1);
                    let mut stdout = String::new();
                    let mut stderr = String::new();

                    if stdio == CommandStdio::Pipe {
                        if let Some(mut out) = child.stdout.take() {
                            let _ = out.read_to_string(&mut stdout);
                        }
                        if let Some(mut err) = child.stderr.take() {
                            let _ = err.read_to_string(&mut stderr);
                        }
                    }

                    return Ok(LauncherProcessResult {
                        exit_code,
                        stdout,
                        stderr,
                        timed_out: false,
                    });
                }
                Ok(None) => {
                    if let Some(timeout_dur) = timeout
                        && start.elapsed() >= timeout_dur
                    {
                        let _ = child.kill();
                        let _ = child.wait();
                        return Ok(LauncherProcessResult::timeout());
                    }
                    std::thread::sleep(poll_delay);
                }
                Err(err) => {
                    return Ok(LauncherProcessResult {
                        exit_code: 1,
                        stdout: String::new(),
                        stderr: err.to_string(),
                        timed_out: false,
                    });
                }
            }
        }
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

    #[test]
    fn test_default_runner_echo() {
        let runner = DefaultProcessRunner;
        let cmd = vec![String::from("echo"), String::from("hello world")];
        let res = runner
            .run(
                &cmd,
                None,
                Some(Duration::from_secs(2)),
                CommandStdio::Pipe,
                None,
            )
            .unwrap();
        assert_eq!(res.exit_code, 0);
        assert_eq!(res.stdout.trim(), "hello world");
        assert!(!res.timed_out);
    }
}
