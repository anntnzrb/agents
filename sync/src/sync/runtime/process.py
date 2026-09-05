# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Asynchronous subprocess execution and command outcome management."""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import TypeAdapter, ValidationError

from sync.runtime.errors import assert_never, err

__all__ = [
    "CommandOutcome",
    "Failure",
    "MissingCommand",
    "ProcessResult",
    "RunProcessOptions",
    "Success",
    "TimedOut",
    "command_exists",
    "log_command_failure",
    "resolve_executable",
    "run_command",
    "run_command_outcome",
    "run_process",
]

EXIT_SUCCESS: int = 0
EXIT_GENERAL_ERROR: int = 1
EXIT_MISSING_COMMAND: int = 127
MILLISECONDS_PER_SECOND: float = 1000.0
TIMEOUT_MIN_SECONDS: float = 0.0


@dataclass(frozen=True, slots=True)
class Success:
    """Command executed successfully with zero exit code."""

    _tag: Literal["Success"] = "Success"

    @property
    def tag(self) -> Literal["Success"]:
        """Discriminator tag for outcome."""
        return "Success"


@dataclass(frozen=True, slots=True)
class MissingCommand:
    """Command executable was not found."""

    _tag: Literal["MissingCommand"] = "MissingCommand"

    @property
    def tag(self) -> Literal["MissingCommand"]:
        """Discriminator tag for outcome."""
        return "MissingCommand"


@dataclass(frozen=True, slots=True)
class Failure:
    """Command failed with non-zero exit code or error output."""

    detail: str
    _tag: Literal["Failure"] = "Failure"

    @property
    def tag(self) -> Literal["Failure"]:
        """Discriminator tag for outcome."""
        return "Failure"


@dataclass(frozen=True, slots=True)
class TimedOut:
    """Command execution timed out."""

    _tag: Literal["TimedOut"] = "TimedOut"

    @property
    def tag(self) -> Literal["TimedOut"]:
        """Discriminator tag for outcome."""
        return "TimedOut"


type CommandOutcome = Success | MissingCommand | Failure | TimedOut


@dataclass(frozen=True, slots=True)
class ProcessResult:
    """Captured result of a finished or timed-out child process."""

    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool

    @property
    def exitCode(self) -> int:  # noqa: N802
        """CamelCase alias for compatibility with TS callers."""
        return self.exit_code

    @property
    def timedOut(self) -> bool:  # noqa: N802
        """CamelCase alias for compatibility with TS callers."""
        return self.timed_out


@dataclass(frozen=True, slots=True)
class RunProcessOptions:
    """Options configuring subprocess execution."""

    cwd: str | Path | None = None
    env: Mapping[str, str | None] | None = None
    timeout_ms: float | None = None
    stdio: Literal["pipe", "inherit"] = "pipe"


def _detail_from_output(stdout: str, stderr: str) -> str:
    if stderr.strip():
        return stderr.strip()
    if stdout.strip():
        return stdout.strip()
    return "unknown error"


def _has_path_separator(command: str) -> bool:
    return os.path.sep in command or "/" in command


def _resolve_command_path(command: str, cwd: str | Path | None) -> str:
    if (
        _has_path_separator(command)
        and cwd is not None
        and not Path(command).is_absolute()
    ):
        return str(Path(cwd) / command)
    return command


async def _which_from_path(
    command: str,
    env: Mapping[str, str],
) -> str | None:
    path_env = env.get("PATH")
    if not path_env:
        return None
    for dir_path in path_env.split(os.pathsep):
        if not dir_path:
            continue
        candidate = Path(dir_path) / command
        try:
            stat_result = await asyncio.to_thread(candidate.stat)
            if not stat_result.st_mode & 0o111 or stat.S_ISDIR(stat_result.st_mode):
                continue
            if await asyncio.to_thread(os.access, candidate, os.X_OK):
                return str(candidate)
        except OSError:
            continue
    return None


async def _existing_path_command(command: str) -> str | None:
    candidate = Path(command)
    try:
        stat_result = await asyncio.to_thread(candidate.stat)
        if stat.S_ISDIR(stat_result.st_mode):
            return None
        if await asyncio.to_thread(os.access, candidate, os.X_OK):
            return str(candidate)
    except OSError:
        return None
    return None


async def resolve_executable(
    command: str,
    cwd: str | Path | None = None,
    env: Mapping[str, str | None] | None = None,
) -> str | None:
    """Resolve an executable path either via PATH or direct file access."""
    effective_env: dict[str, str] = dict(os.environ)
    if env is not None:
        for key, value in env.items():
            if value is None:
                effective_env.pop(key, None)
            else:
                effective_env[key] = value

    executable = _resolve_command_path(command, cwd)
    if not _has_path_separator(executable):
        return await _which_from_path(executable, effective_env)
    return await _existing_path_command(executable)


async def command_exists(
    command: str,
    cwd: str | Path | None = None,
) -> bool:
    """Check if a command executable is available and executable."""
    resolved = await resolve_executable(command, cwd, os.environ)
    return resolved is not None


def _parse_mapping_options(
    options: Mapping[str, object],
    cwd: str | Path | None,
    env: Mapping[str, str | None] | None,
    timeout_ms: float | None,
    stdio: Literal["pipe", "inherit"],
) -> tuple[
    str | Path | None,
    Mapping[str, str | None] | None,
    float | None,
    Literal["pipe", "inherit"],
]:
    eff_cwd = cwd
    eff_env = env
    eff_timeout = timeout_ms
    eff_stdio = stdio

    opt_cwd = options.get("cwd")
    if isinstance(opt_cwd, (str, Path)):
        eff_cwd = opt_cwd
    opt_env = options.get("env")
    if isinstance(opt_env, Mapping):
        try:
            validated_env = TypeAdapter(dict[object, object]).validate_python(opt_env)
            eff_env = {
                k: v
                for k, v in validated_env.items()
                if isinstance(k, str) and (isinstance(v, str) or v is None)
            }
        except ValidationError:
            pass
    opt_timeout = options.get("timeout_ms", options.get("timeoutMs"))
    if isinstance(opt_timeout, (int, float)):
        eff_timeout = float(opt_timeout)
    opt_stdio = options.get("stdio")
    if opt_stdio in ("inherit", "pipe"):
        eff_stdio = opt_stdio

    return eff_cwd, eff_env, eff_timeout, eff_stdio


def _parse_run_options(
    options: RunProcessOptions | Mapping[str, object] | None,
    cwd: str | Path | None,
    env: Mapping[str, str | None] | None,
    timeout_ms: float | None,
    stdio: Literal["pipe", "inherit"],
) -> tuple[
    str | Path | None,
    Mapping[str, str | None] | None,
    float | None,
    Literal["pipe", "inherit"],
]:
    if isinstance(options, RunProcessOptions):
        eff_cwd = options.cwd if options.cwd is not None else cwd
        eff_env = options.env if options.env is not None else env
        eff_timeout = (
            options.timeout_ms if options.timeout_ms is not None else timeout_ms
        )
        eff_stdio = options.stdio if options.stdio != "pipe" else stdio
        return eff_cwd, eff_env, eff_timeout, eff_stdio

    if isinstance(options, Mapping):
        return _parse_mapping_options(options, cwd, env, timeout_ms, stdio)

    return cwd, env, timeout_ms, stdio


def _build_process_env(
    effective_env: Mapping[str, str | None] | None,
) -> dict[str, str]:
    resolved_env = dict(os.environ)
    if effective_env is not None:
        for key, value in effective_env.items():
            if value is None:
                resolved_env.pop(key, None)
            else:
                resolved_env[key] = value
    return resolved_env


async def _communicate_subprocess(
    proc: asyncio.subprocess.Process,
    timeout_ms: float | None,
) -> tuple[bytes | None, bytes | None, bool]:
    if timeout_ms is None:
        stdout_raw, stderr_raw = await proc.communicate()
        return stdout_raw, stderr_raw, False

    timeout_sec = max(
        timeout_ms / MILLISECONDS_PER_SECOND,
        TIMEOUT_MIN_SECONDS,
    )
    try:
        async with asyncio.timeout(timeout_sec):
            stdout_raw, stderr_raw = await proc.communicate()
            return stdout_raw, stderr_raw, False
    except TimeoutError:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            with contextlib.suppress(OSError):
                proc.kill()
        try:
            stdout_raw, stderr_raw = await proc.communicate()
        except OSError:
            stdout_raw, stderr_raw = b"", b""
        return stdout_raw, stderr_raw, True


async def run_process(  # noqa: PLR0913
    command: Sequence[str],
    options: RunProcessOptions | Mapping[str, object] | None = None,
    *,
    cwd: str | Path | None = None,
    env: Mapping[str, str | None] | None = None,
    timeout_ms: float | None = None,
    stdio: Literal["pipe", "inherit"] = "pipe",
) -> ProcessResult:
    """Execute a command in a child process with optional timeout and I/O capturing."""
    if not command or not command[0]:
        return ProcessResult(
            exit_code=EXIT_MISSING_COMMAND,
            stdout="",
            stderr="",
            timed_out=False,
        )

    eff_cwd, eff_env, eff_timeout, eff_stdio = _parse_run_options(
        options, cwd, env, timeout_ms, stdio
    )
    resolved_env = _build_process_env(eff_env)
    executable = await resolve_executable(command[0], eff_cwd, resolved_env)
    if executable is None:
        return ProcessResult(
            exit_code=EXIT_MISSING_COMMAND,
            stdout="",
            stderr="",
            timed_out=False,
        )

    is_inherit = eff_stdio == "inherit"
    proc = await asyncio.create_subprocess_exec(
        executable,
        *command[1:],
        cwd=str(eff_cwd) if eff_cwd is not None else None,
        env=resolved_env,
        stdin=None if is_inherit else asyncio.subprocess.DEVNULL,
        stdout=None if is_inherit else asyncio.subprocess.PIPE,
        stderr=None if is_inherit else asyncio.subprocess.PIPE,
        start_new_session=True,
    )

    stdout_raw, stderr_raw, timed_out = await _communicate_subprocess(proc, eff_timeout)
    exit_code = proc.returncode if proc.returncode is not None else EXIT_GENERAL_ERROR
    stdout_text = (
        stdout_raw.decode("utf-8", errors="replace") if stdout_raw is not None else ""
    )
    stderr_text = (
        stderr_raw.decode("utf-8", errors="replace") if stderr_raw is not None else ""
    )

    return ProcessResult(
        exit_code=exit_code,
        stdout=stdout_text,
        stderr=stderr_text,
        timed_out=timed_out,
    )


async def run_command_outcome(
    command: Sequence[str],
    cwd: str | Path | None = None,
    timeout_ms: float = 0.0,
) -> CommandOutcome:
    """Run a command and convert the process execution result into a CommandOutcome."""
    result = await run_process(
        command,
        cwd=cwd,
        timeout_ms=timeout_ms if timeout_ms > 0 else None,
        stdio="pipe",
    )
    if result.timed_out:
        return TimedOut()
    if (
        result.exit_code == EXIT_MISSING_COMMAND
        and result.stdout == ""
        and result.stderr == ""
    ):
        return MissingCommand()
    if result.exit_code == EXIT_SUCCESS:
        return Success()
    return Failure(detail=_detail_from_output(result.stdout, result.stderr))


async def run_command(
    command: Sequence[str],
    cwd: str | Path | None,
    timeout_ms: float,
    action: str,
) -> bool:
    """Run a command, logging failure messages to stderr on non-zero outcome."""
    outcome = await run_command_outcome(command, cwd, timeout_ms)
    if outcome.tag == "Success":
        return True
    log_command_failure(command, action, outcome)
    return False


def log_command_failure(
    command: Sequence[str],
    action: str,
    outcome: CommandOutcome,
) -> None:
    """Log an informative error to stderr describing a failed command outcome."""
    cmd_first = command[0] if command else ""
    cmd_str = " ".join(command)
    match outcome:
        case Success():
            return
        case MissingCommand():
            err(f"missing command for {action}: {cmd_first}")
        case Failure(detail=detail):
            err(f"{action} failed: {cmd_str} ({detail})")
        case TimedOut():
            err(f"{action} timed out: {cmd_str}")
        case _ as unreachable:
            assert_never(unreachable)
