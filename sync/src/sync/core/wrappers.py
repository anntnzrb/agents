# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Wrapper generation, rendering, and reconciliation for harnesses and tools."""

from __future__ import annotations

import contextlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from sync.core.secret_template import strip_jsonc
from sync.core.tool_launchers import TOOL_LAUNCHERS, tool_launcher_default_args
from sync.runtime.errors import err, is_errno, panic_message, warn

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sync.core.harness import Harness, SyncEnv
    from sync.core.managed_tools import PreparedManagedTool

__all__ = [
    "UNIX_WRAPPER_DIR",
    "WRAPPER_MARKER",
    "WRAPPER_STATE_FILE",
    "HarnessWrapperDestination",
    "WrapperDestination",
    "WrapperReconcileResult",
    "WrapperRuntime",
    "WrapperState",
    "is_managed_wrapper",
    "managed_tool_wrapper_destination",
    "read_wrapper_state",
    "reconcile_wrapper_files",
    "reconcile_wrappers",
    "render_launch_wrapper",
    "render_managed_tool_wrapper",
    "shell_quote",
    "wrapper_destinations",
    "wrapper_directory",
    "wrapper_path",
]

UNIX_WRAPPER_DIR: tuple[str, str] = (".local", "bin")
WRAPPER_STATE_FILE: str = "wrappers.json"
WRAPPER_MARKER: str = "agents-managed-wrapper:v1"
WRAPPER_FILE_MODE: int = 0o755
PERM_MASK: int = 0o777


class WrapperState(BaseModel):
    """Persisted state of agent-managed wrapper scripts."""

    version: Literal[1] = 1
    entries: list[str] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class WrapperDestination:
    """Destination path and rendered shell script content for a wrapper."""

    path: str
    content: str


@dataclass(frozen=True, slots=True)
class HarnessWrapperDestination(WrapperDestination):
    """Destination wrapper specifically generated for a harness."""

    harness: Harness


@dataclass(frozen=True, slots=True)
class WrapperReconcileResult:
    """Result summary of wrapper reconciliation."""

    owned: list[str]
    conflicts: list[str]
    removed: list[str]


@dataclass(frozen=True, slots=True)
class WrapperRuntime:
    """Runtime options for wrapper reconciliation."""

    additional_destinations: tuple[WrapperDestination, ...] = ()


def wrapper_directory(sync_env: SyncEnv) -> str:
    """Return the absolute path to the user's wrapper binary directory."""
    return str(Path(sync_env.home).joinpath(*UNIX_WRAPPER_DIR))


def wrapper_path(sync_env: SyncEnv, harness: Harness) -> str:
    """Compute the wrapper script path for a given harness."""
    return str(Path(wrapper_directory(sync_env)) / harness.launcher.bin)


def wrapper_destinations(sync_env: SyncEnv) -> list[WrapperDestination]:
    """Compute all desired wrapper destinations for harnesses and tools."""
    harness_wrappers: list[WrapperDestination] = [
        HarnessWrapperDestination(
            harness=harness,
            path=wrapper_path(sync_env, harness),
            content=render_launch_wrapper(
                sync_env.runtime_home,
                harness.source_name,
                harness.launcher.default_args,
                harness.launcher.env,
            ),
        )
        for harness in sync_env.harnesses
    ]
    tool_wrappers: list[WrapperDestination] = [
        WrapperDestination(
            path=str(Path(wrapper_directory(sync_env)) / tool.bin),
            content=render_launch_wrapper(
                sync_env.runtime_home,
                tool.id,
                tool_launcher_default_args(sync_env, tool),
            ),
        )
        for tool in TOOL_LAUNCHERS
    ]
    return [*harness_wrappers, *tool_wrappers]


def render_launch_wrapper(
    runtime_home: str,
    source_name: str,
    default_args: Sequence[str] = (),
    env: Mapping[str, str] | None = None,
) -> str:
    """Render a POSIX shell script wrapper for launching a harness or tool."""
    sync_script = str(Path(runtime_home) / "sync-current" / "src" / "sync" / "cli.py")
    args_str = " ".join(shell_quote(arg) for arg in default_args)
    env_lines = (
        [f"export {key}={shell_quote(value)}" for key, value in env.items()]
        if env
        else []
    )
    launch_suffix = f" {args_str}" if args_str else ""
    quoted_script = shell_quote(sync_script)
    quoted_source = shell_quote(source_name)
    lines = [
        "#!/bin/sh",
        f"# {WRAPPER_MARKER}",
        "set -eu",
        f"if [ ! -f {quoted_script} ]; then",
        (
            "  echo 'agents: sync runtime is missing; "
            "run sync from the agents repository' >&2"
        ),
        "  exit 127",
        "fi",
        *env_lines,
        f'exec python3 {quoted_script} launch {quoted_source} --{launch_suffix} "$@"',
        "",
    ]
    return "\n".join(lines)


def managed_tool_wrapper_destination(
    sync_env: SyncEnv,
    tool: PreparedManagedTool,
) -> WrapperDestination:
    """Create a wrapper destination for a prepared managed tool."""
    return WrapperDestination(
        path=str(Path(wrapper_directory(sync_env)) / tool.command),
        content=render_managed_tool_wrapper(tool),
    )


def render_managed_tool_wrapper(tool: PreparedManagedTool) -> str:
    """Render a POSIX shell script wrapper for a managed tool binary."""
    quoted_exec = shell_quote(tool.executable)
    quoted_cfg = shell_quote(tool.config_path)
    lines = [
        "#!/bin/sh",
        f"# {WRAPPER_MARKER}",
        "set -eu",
        f'exec {quoted_exec} --config {quoted_cfg} "$@"',
        "",
    ]
    return "\n".join(lines)


def reconcile_wrappers(
    sync_env: SyncEnv,
    runtime: WrapperRuntime | None = None,
) -> bool:
    """Reconcile wrapper scripts on disk and warn on any unmanaged conflicts."""
    try:
        extra = runtime.additional_destinations if runtime else ()
        desired = [*wrapper_destinations(sync_env), *extra]
        result = reconcile_wrapper_files(sync_env, desired)
    except (RuntimeError, OSError) as error:
        message = panic_message(error)
        err(f"wrapper reconciliation failed: {message}")
        return False
    else:
        if result.conflicts:
            for conflict in result.conflicts:
                warn(f"preserving unmanaged wrapper conflict: {conflict}")
        return True


def reconcile_wrapper_files(
    sync_env: SyncEnv,
    desired: Sequence[WrapperDestination],
) -> WrapperReconcileResult:
    """Reconcile destination wrappers against persisted state, returning result."""
    state_path = str(Path(sync_env.managed_state_home) / WRAPPER_STATE_FILE)
    previous = read_wrapper_state(state_path)
    desired_by_path = {entry.path: entry for entry in desired}
    allowed_directories = {str(Path(entry.path).parent.resolve()) for entry in desired}
    if sync_env.home:
        allowed_directories.add(str(Path(wrapper_directory(sync_env)).resolve()))

    owned: list[str] = []
    conflicts: list[str] = []
    removed: list[str] = []

    for old_path in previous.entries:
        if old_path in desired_by_path:
            continue
        if str(Path(old_path).parent.resolve()) not in allowed_directories:
            conflicts.append(old_path)
            continue
        if is_managed_wrapper(old_path):
            remove_wrapper(old_path)
            removed.append(old_path)
        else:
            conflicts.append(old_path)

    for entry in desired:
        status = write_managed_wrapper(entry.path, entry.content)
        if status == "owned":
            owned.append(entry.path)
        else:
            conflicts.append(entry.path)

    Path(state_path).parent.mkdir(parents=True, exist_ok=True)
    unique_owned = sorted(set(owned))
    write_wrapper_state(
        state_path,
        WrapperState(version=1, entries=unique_owned),
    )

    return WrapperReconcileResult(
        owned=owned,
        conflicts=sorted(set(conflicts)),
        removed=removed,
    )


def read_wrapper_state(state_path: str) -> WrapperState:
    """Read and validate the persisted wrapper state file."""
    try:
        content = Path(state_path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return WrapperState(version=1, entries=[])
    except OSError as error:
        message = f"read {state_path} ({panic_message(error)})"
        raise RuntimeError(message) from error

    try:
        parsed: object = json.loads(strip_jsonc(content))
    except (json.JSONDecodeError, ValueError, TypeError) as error:
        message = panic_message(error)
        warn(f"wrapper state parse failed, ignoring {state_path} ({message})")
        return WrapperState(version=1, entries=[])

    try:
        raw_dict = TypeAdapter(dict[str, object]).validate_python(parsed)
        entries_raw = raw_dict.get("entries", [])
        raw_entries = TypeAdapter(list[object]).validate_python(entries_raw)
        entries = [
            entry
            for entry in raw_entries
            if isinstance(entry, str) and Path(entry).is_absolute()
        ]
        unique_entries = sorted(set(entries))
        return WrapperState(version=1, entries=unique_entries)
    except (ValidationError, TypeError, ValueError):
        warn(f"wrapper state parse failed, ignoring {state_path} (invalid shape)")
        return WrapperState(version=1, entries=[])


def write_wrapper_state(state_path: str, state: WrapperState) -> None:
    """Atomically write wrapper state as 2-space indented JSON with trailing newline."""
    content = f"{json.dumps(state.model_dump(), indent=2)}\n"
    state_file = Path(state_path)
    try:
        if state_file.exists() and state_file.read_text(encoding="utf-8") == content:
            return
    except OSError as error:
        if not is_errno(error, "ENOENT"):
            message = f"read {state_path} ({panic_message(error)})"
            raise RuntimeError(message) from error

    temp_path = Path(f"{state_path}.{os.getpid()}.tmp")
    try:
        with temp_path.open("w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        temp_path.replace(state_file)
    except OSError as error:
        with contextlib.suppress(OSError):
            if temp_path.exists():
                temp_path.unlink()
        message = f"replace {state_path} ({panic_message(error)})"
        raise RuntimeError(message) from error


def write_managed_wrapper(
    target_path: str,
    content: str,
) -> Literal["owned", "conflict"]:
    """Write wrapper file with 0755 permissions atomically, checking for conflicts."""
    target = Path(target_path)
    try:
        lstat = target.lstat()
        if stat.S_ISLNK(lstat.st_mode) or not stat.S_ISREG(lstat.st_mode):
            return "conflict"
        if not is_managed_wrapper(target_path):
            return "conflict"
        existing_content = target.read_text(encoding="utf-8")
        if existing_content == content:
            if (lstat.st_mode & PERM_MASK) != WRAPPER_FILE_MODE:
                target.chmod(WRAPPER_FILE_MODE)
            return "owned"
    except FileNotFoundError:
        pass
    except OSError as error:
        message = f"inspect wrapper {target_path} ({panic_message(error)})"
        raise RuntimeError(message) from error

    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path = Path(f"{target_path}.{os.getpid()}.tmp")
    try:
        with temp_path.open("w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        temp_path.chmod(WRAPPER_FILE_MODE)
        temp_path.replace(target)
    except OSError as error:
        with contextlib.suppress(OSError):
            if temp_path.exists():
                temp_path.unlink()
        message = f"replace wrapper {target_path} ({panic_message(error)})"
        raise RuntimeError(message) from error
    return "owned"


def is_managed_wrapper(target_path: str) -> bool:
    """Check if target file is a regular file containing the wrapper marker."""
    target = Path(target_path)
    try:
        lstat = target.lstat()
        if stat.S_ISLNK(lstat.st_mode) or not stat.S_ISREG(lstat.st_mode):
            return False
        return WRAPPER_MARKER in target.read_text(encoding="utf-8")
    except OSError:
        return False


def remove_wrapper(target_path: str) -> None:
    """Remove a wrapper file, raising on unexpected OS errors."""
    try:
        Path(target_path).unlink(missing_ok=True)
    except OSError as error:
        message = f"remove wrapper {target_path} ({panic_message(error)})"
        raise RuntimeError(message) from error


def shell_quote(value: str) -> str:
    """Quote a string using single-quotes for POSIX shell scripts."""
    escaped = value.replace("'", "'\"'\"'")
    return f"'{escaped}'"
