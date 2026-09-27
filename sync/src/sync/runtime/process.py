# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Asynchronous subprocess execution and command outcome management."""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Literal, NoReturn

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

from sync.runtime.errors import err

__all__ = [
    "CommandOutcome",
    "ExecPlan",
    "Failure",
    "MissingCommand",
    "OutputLimit",
    "ProcessResult",
    "RunProcessOptions",
    "Success",
    "TimedOut",
    "build_process_env",
    "command_exists",
    "exec_process",
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

    tag: ClassVar[Literal["Success"]] = "Success"


@dataclass(frozen=True, slots=True)
class MissingCommand:
    """Command executable was not found."""

    tag: ClassVar[Literal["MissingCommand"]] = "MissingCommand"


@dataclass(frozen=True, slots=True)
class Failure:
    """Command failed with non-zero exit code or error output."""

    detail: str
    tag: ClassVar[Literal["Failure"]] = "Failure"


@dataclass(frozen=True, slots=True)
class TimedOut:
    """Command execution timed out."""

    tag: ClassVar[Literal["TimedOut"]] = "TimedOut"


@dataclass(frozen=True, slots=True)
class OutputLimit:
    """Command output exceeded the retained-byte limit."""

    detail: str
    tag: ClassVar[Literal["OutputLimit"]] = "OutputLimit"


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


_PYTHON_IGNORED_SIGNALS = (signal.SIGPIPE, signal.SIGXFSZ)


@dataclass(frozen=True, slots=True)
class ExecPlan:
    """An executable that replaces the current process; see ``exec_process``."""

    executable: str
    args: tuple[str, ...]
    env: dict[str, str]


def exec_process(plan: ExecPlan) -> NoReturn:
    """Replace this process with the plan's executable; raises OSError on failure.

    The executable keeps this PID, session, process group, and controlling
    terminal, so terminal signals and supervisor stop signals reach it directly.
    """
    _ = sys.stdout.flush()
    _ = sys.stderr.flush()
    # Python ignores these at startup and ignored dispositions survive exec;
    # restore defaults as subprocess's restore_signals does.
    for signum in _PYTHON_IGNORED_SIGNALS:
        _ = signal.signal(signum, signal.SIG_DFL)
    os.execve(plan.executable, [plan.executable, *plan.args], plan.env)  # noqa: S606


def _detail_from_output(stdout: str, stderr: str) -> str:
    detail = stderr.strip() or stdout.strip() or "unknown error"
    if len(detail) > MAX_DETAIL_CHARS:
        return f"{detail[:MAX_DETAIL_CHARS]}…[truncated]"
    return detail


def _resolve_executable(
    command: str, cwd: str | Path | None, path_env: str | None
) -> str | None:
    if os.path.sep in command or "/" in command:
        candidate = Path(command)
        if cwd is not None and not candidate.is_absolute():
            candidate = Path(cwd) / candidate
        candidates = (candidate,)
        search_path = False
    else:
        candidates = (
            Path(part) / command for part in (path_env or "").split(os.pathsep) if part
        )
        search_path = True
    for candidate in candidates:
        try:
            mode = candidate.stat().st_mode
            if stat.S_ISDIR(mode) or (search_path and not mode & 0o111):
                continue
            if os.access(candidate, os.X_OK):
                return str(candidate)
        except OSError:
            continue
    return None


async def resolve_executable(
    command: str,
    cwd: str | Path | None = None,
    env: Mapping[str, str | None] | None = None,
) -> str | None:
    """Resolve an executable path either via PATH or direct file access."""
    path_env = (
        os.environ.get("PATH")
        if env is None
        else env.get("PATH", os.environ.get("PATH"))
    )
    return await asyncio.to_thread(_resolve_executable, command, cwd, path_env)


async def command_exists(
    command: str,
    cwd: str | Path | None = None,
) -> bool:
    """Check if a command executable is available and executable."""
    resolved = await resolve_executable(command, cwd)
    return resolved is not None


def build_process_env(
    effective_env: Mapping[str, str | None] | None,
) -> dict[str, str]:
    """Overlay env onto the parent environment; a None value removes the key."""
    resolved_env = dict(os.environ)
    if effective_env is not None:
        for key, value in effective_env.items():
            if value is None:
                _ = resolved_env.pop(key, None)
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
        _ = await proc.wait()


_READ_CHUNK_SIZE: int = 65536


@dataclass(slots=True)
class _StreamDrainState:
    """Shared retained-byte budget for both drain tasks."""

    total: int = 0
    overflow: bool = False


async def _drain(
    stream: asyncio.StreamReader,
    chunks: list[bytes],
    state: _StreamDrainState,
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
        if state.overflow:
            continue
        if state.total + len(data) > MAX_OUTPUT_BYTES:
            allowed = MAX_OUTPUT_BYTES - state.total
            if allowed > 0:
                chunks.append(data[:allowed])
            state.total = MAX_OUTPUT_BYTES
            state.overflow = True
            _kill_process_group(proc)
            continue
        chunks.append(data)
        state.total = state.total + len(data)


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
                _ = tg.create_task(_discard_stream(stdout))
            if stderr is not None:
                _ = tg.create_task(_discard_stream(stderr))
            _ = tg.create_task(_reap_process(proc))


async def _communicate_subprocess(
    proc: asyncio.subprocess.Process,
    timeout_ms: float | None,
) -> tuple[bytes, bytes, bool, bool]:
    if proc.stdout is None or proc.stderr is None:
        message = "captured subprocess is missing a pipe"
        raise RuntimeError(message)
    stdout_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []
    shared = _StreamDrainState()
    timeout_sec = (
        max(timeout_ms / MILLISECONDS_PER_SECOND, TIMEOUT_MIN_SECONDS)
        if timeout_ms is not None
        else None
    )
    try:
        async with asyncio.timeout(timeout_sec):
            async with asyncio.TaskGroup() as tg:
                _ = tg.create_task(_drain(proc.stdout, stdout_chunks, shared, proc))
                _ = tg.create_task(_drain(proc.stderr, stderr_chunks, shared, proc))
                _ = tg.create_task(proc.wait())
    except TimeoutError:
        _kill_process_group(proc)
        await _discard_and_reap_pipes(proc)
        overflow = shared.overflow
        return b"".join(stdout_chunks), b"".join(stderr_chunks), True, overflow
    except asyncio.CancelledError:
        _kill_process_group(proc)
        await _discard_and_reap_pipes(proc)
        raise
    overflow = shared.overflow
    return b"".join(stdout_chunks), b"".join(stderr_chunks), False, overflow


async def run_process(
    command: Sequence[str],
    options: RunProcessOptions | None = None,
    *,
    cwd: str | Path | None = None,
    env: Mapping[str, str | None] | None = None,
    timeout_ms: float | None = None,
) -> ProcessResult:
    """Run a command in its own session with captured output and optional timeout."""
    if not command or not command[0]:
        return ProcessResult(
            exit_code=EXIT_MISSING_COMMAND,
            stdout="",
            stderr="",
            timed_out=False,
        )

    eff_cwd = options.cwd if options is not None and options.cwd is not None else cwd
    eff_env = options.env if options is not None and options.env is not None else env
    eff_timeout = (
        options.timeout_ms
        if options is not None and options.timeout_ms is not None
        else timeout_ms
    )
    resolved_env = build_process_env(eff_env)
    executable = await asyncio.to_thread(
        _resolve_executable, command[0], eff_cwd, resolved_env.get("PATH")
    )
    if executable is None:
        return ProcessResult(
            exit_code=EXIT_MISSING_COMMAND,
            stdout="",
            stderr="",
            timed_out=False,
        )

    proc = await asyncio.create_subprocess_exec(
        executable,
        *command[1:],
        cwd=str(eff_cwd) if eff_cwd is not None else None,
        env=resolved_env,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )

    stdout_raw, stderr_raw, timed_out, output_limited = await _communicate_subprocess(
        proc, eff_timeout
    )
    exit_code = proc.returncode if proc.returncode is not None else EXIT_GENERAL_ERROR
    return ProcessResult(
        exit_code=exit_code,
        stdout=stdout_raw.decode("utf-8", errors="replace"),
        stderr=stderr_raw.decode("utf-8", errors="replace"),
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
