# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Asynchronous subprocess execution and command outcome management."""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

from sync.runtime.errors import assert_never, err

__all__ = [
    "CommandOutcome",
    "Failure",
    "MissingCommand",
    "OutputLimit",
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
MAX_OUTPUT_BYTES: int = 10 * 1024 * 1024
MAX_DETAIL_CHARS: int = 2000


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


@dataclass(frozen=True, slots=True)
class OutputLimit:
    """Command output exceeded the retained-byte limit."""

    detail: str
    _tag: Literal["OutputLimit"] = "OutputLimit"

    @property
    def tag(self) -> Literal["OutputLimit"]:
        """Discriminator tag for outcome."""
        return "OutputLimit"


type CommandOutcome = Success | MissingCommand | Failure | TimedOut | OutputLimit


@dataclass(frozen=True, slots=True)
class ProcessResult:
    """Captured result of a finished, timed-out, or output-limited child process."""

    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool
    output_limited: bool = False


@dataclass(frozen=True, slots=True)
class RunProcessOptions:
    """Options configuring subprocess execution."""

    cwd: str | Path | None = None
    env: Mapping[str, str | None] | None = None
    timeout_ms: float | None = None
    stdio: Literal["pipe", "inherit"] = "pipe"


def _detail_from_output(stdout: str, stderr: str) -> str:
    detail = stderr.strip() or stdout.strip() or "unknown error"
    if len(detail) > MAX_DETAIL_CHARS:
        return f"{detail[:MAX_DETAIL_CHARS]}…[truncated]"
    return detail


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


def _parse_run_options(
    options: RunProcessOptions | None,
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


def _kill_process_group(proc: asyncio.subprocess.Process) -> None:
    """Terminate the owned process group; best effort, never raises."""
    with contextlib.suppress(OSError):
        os.killpg(proc.pid, signal.SIGKILL)
        return
    with contextlib.suppress(OSError):
        proc.kill()


async def _reap_process(proc: asyncio.subprocess.Process) -> None:
    """Wait for the direct child to exit; suppresses close races."""
    with contextlib.suppress(OSError):
        await proc.wait()


_READ_CHUNK_SIZE: int = 65536


async def _drain_one_stream(
    stream: asyncio.StreamReader,
    chunks: list[bytes],
    state: dict[str, int | bool],
    proc: asyncio.subprocess.Process,
) -> None:
    """Drain one pipe, enforcing the shared retained-byte limit."""
    while True:
        try:
            data = await stream.read(_READ_CHUNK_SIZE)
        except OSError:
            return
        if not data:
            return
        total = int(state["total"])
        overflow = bool(state["overflow"])
        if overflow:
            continue
        if total + len(data) > MAX_OUTPUT_BYTES:
            allowed = MAX_OUTPUT_BYTES - total
            if allowed > 0:
                chunks.append(data[:allowed])
            state["total"] = MAX_OUTPUT_BYTES
            state["overflow"] = True
            _kill_process_group(proc)
            continue
        chunks.append(data)
        state["total"] = total + len(data)


async def _discard_stream(stream: asyncio.StreamReader) -> None:
    """Drain and discard all bytes from a stream to EOF."""
    while True:
        try:
            data = await stream.read(_READ_CHUNK_SIZE)
        except OSError:
            return
        if not data:
            return


async def _discard_and_reap_pipes(proc: asyncio.subprocess.Process) -> None:
    """Drain and discard pipe output concurrently with process reaping."""
    stdout = proc.stdout
    stderr = proc.stderr
    if stdout is None and stderr is None:
        await _reap_process(proc)
        return
    with contextlib.suppress(OSError):
        async with asyncio.TaskGroup() as tg:
            if stdout is not None:
                tg.create_task(_discard_stream(stdout))
            if stderr is not None:
                tg.create_task(_discard_stream(stderr))
            tg.create_task(_reap_process(proc))


async def _drain_pipes(
    proc: asyncio.subprocess.Process,
    stdout_chunks: list[bytes],
    stderr_chunks: list[bytes],
    shared: dict[str, int | bool],
) -> None:
    """Drain both pipes and wait for exit; callers handle timeouts."""
    stdout = proc.stdout
    stderr = proc.stderr
    if stdout is None or stderr is None:
        await proc.wait()
        return
    async with asyncio.TaskGroup() as tg:
        tg.create_task(_drain_one_stream(stdout, stdout_chunks, shared, proc))
        tg.create_task(_drain_one_stream(stderr, stderr_chunks, shared, proc))
        tg.create_task(proc.wait())


async def _communicate_subprocess(
    proc: asyncio.subprocess.Process,
    timeout_ms: float | None,
) -> tuple[bytes | None, bytes | None, bool, bool]:
    if proc.stdout is None or proc.stderr is None:
        if timeout_ms is None:
            try:
                await proc.wait()
            except asyncio.CancelledError:
                _kill_process_group(proc)
                await _reap_process(proc)
                raise
            return None, None, False, False
        timeout_sec = max(
            timeout_ms / MILLISECONDS_PER_SECOND,
            TIMEOUT_MIN_SECONDS,
        )
        try:
            async with asyncio.timeout(timeout_sec):
                await proc.wait()
                return None, None, False, False
        except TimeoutError:
            _kill_process_group(proc)
            await _reap_process(proc)
            return None, None, True, False
        except asyncio.CancelledError:
            _kill_process_group(proc)
            await _reap_process(proc)
            raise
    stdout_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []
    shared: dict[str, int | bool] = {"total": 0, "overflow": False}
    if timeout_ms is None:
        try:
            await _drain_pipes(proc, stdout_chunks, stderr_chunks, shared)
        except asyncio.CancelledError:
            _kill_process_group(proc)
            await _discard_and_reap_pipes(proc)
            raise
        overflow = bool(shared["overflow"])
        return b"".join(stdout_chunks), b"".join(stderr_chunks), False, overflow
    timeout_sec = max(
        timeout_ms / MILLISECONDS_PER_SECOND,
        TIMEOUT_MIN_SECONDS,
    )
    try:
        async with asyncio.timeout(timeout_sec):
            await _drain_pipes(proc, stdout_chunks, stderr_chunks, shared)
    except TimeoutError:
        _kill_process_group(proc)
        await _discard_and_reap_pipes(proc)
        overflow = bool(shared["overflow"])
        return b"".join(stdout_chunks), b"".join(stderr_chunks), True, overflow
    except asyncio.CancelledError:
        _kill_process_group(proc)
        await _discard_and_reap_pipes(proc)
        raise
    overflow = bool(shared["overflow"])
    return b"".join(stdout_chunks), b"".join(stderr_chunks), False, overflow


async def run_process(  # noqa: PLR0913
    command: Sequence[str],
    options: RunProcessOptions | None = None,
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

    stdout_raw, stderr_raw, timed_out, output_limited = await _communicate_subprocess(
        proc, eff_timeout
    )
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
        output_limited=output_limited,
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
    if result.output_limited:
        return OutputLimit(
            detail=f"output limit exceeded ({MAX_OUTPUT_BYTES} bytes retained)"
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
        case OutputLimit(detail=detail):
            err(f"{action} output limit exceeded: {cmd_str} ({detail})")
        case _ as unreachable:
            assert_never(unreachable)
