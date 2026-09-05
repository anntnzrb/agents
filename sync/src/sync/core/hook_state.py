# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Extension hook state tracking, tree fingerprinting, and cache preservation."""

from __future__ import annotations

import contextlib
import errno
import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, TypedDict

from pydantic import TypeAdapter, ValidationError

from sync.runtime.errors import warn
from sync.runtime.fs import is_ignored_sync_entry, sync_text_file
from sync.runtime.jsonc import strip_jsonc

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sync.core.plan import ExtensionDepsHookPlan

__all__ = [
    "GENERATED_EXTENSION_ENTRY_NAMES",
    "PreparedExtensionHookState",
    "clear_extension_hook_state",
    "find_generated_extension_entries",
    "fingerprint_tree",
    "prepare_extension_hook_state",
    "record_extension_hook_state",
    "should_skip_entry",
]

GENERATED_EXTENSION_ENTRY_NAMES: tuple[str, ...] = (
    "package.json",
    "node_modules",
    "bun.lock",
    "bun.lockb",
)
_GENERATED_EXTENSION_ENTRY_SET: frozenset[str] = frozenset(
    GENERATED_EXTENSION_ENTRY_NAMES
)


class _TreeHasher(Protocol):
    def update(self, data: bytes, /) -> None: ...


class _HookStatePayload(TypedDict):
    fingerprint: str
    generatedEntries: list[str]


@dataclass(frozen=True, slots=True)
class PreparedExtensionHookState:
    """Prepared state for extension hook execution."""

    fingerprint: str
    generated_entries: list[str]
    preserve_paths: list[str]
    should_skip: bool
    should_refresh_state: bool


@dataclass(frozen=True, slots=True)
class _LoadedExtensionHookState:
    fingerprint: str
    generated_entries: list[str]
    should_refresh_state: bool


def fingerprint_tree(root: str | os.PathLike[str]) -> str:
    """Compute deterministic SHA-256 fingerprint for a directory tree."""
    root_str = str(root)
    hasher = hashlib.sha256()
    if not _exists(root_str):
        hasher.update(b"missing")
        return hasher.hexdigest()
    _walk_tree(root_str, root_str, hasher)
    return hasher.hexdigest()


def _hash_symlink_entry(
    entry_path: str,
    relative_path: str,
    hasher: _TreeHasher,
) -> bool:
    """Hash symlink and check if it targets a directory. Return True if handled."""
    try:
        target_stat = Path(entry_path).stat()
        if stat.S_ISDIR(target_stat.st_mode):
            message = f"refusing source directory symlink: {entry_path}"
            raise ValueError(message)
    except FileNotFoundError:
        hasher.update(f"broken:{relative_path}\n".encode())
        return True
    except OSError as error:
        if error.errno == errno.ENOENT:
            hasher.update(f"broken:{relative_path}\n".encode())
            return True
        raise
    return False


def _hash_file_content(
    entry_path: str,
    relative_path: str,
    hasher: _TreeHasher,
) -> None:
    hasher.update(f"file:{relative_path}\n".encode())
    try:
        with Path(entry_path).open("rb") as file_handle:
            hasher.update(file_handle.read())
    except OSError as error:
        if error.errno == errno.ENOENT:
            hasher.update(f"broken:{relative_path}\n".encode())
            return
        raise
    hasher.update(b"\n")


def _walk_tree(root: str, current: str, hasher: _TreeHasher) -> None:
    try:
        with os.scandir(current) as it:
            entries = sorted(it, key=lambda e: e.name)
    except OSError as error:
        if error.errno == errno.ENOENT:
            return
        raise

    for entry in entries:
        if should_skip_entry(entry.name):
            continue

        absolute = entry.path
        relative_path = _normalize_relative_path(os.path.relpath(absolute, root))
        if entry.is_dir(follow_symlinks=False):
            hasher.update(f"dir:{relative_path}\n".encode())
            _walk_tree(root, absolute, hasher)
            continue

        if entry.is_symlink() and _hash_symlink_entry(absolute, relative_path, hasher):
            continue

        if not entry.is_file(follow_symlinks=False) and not entry.is_symlink():
            continue

        _hash_file_content(absolute, relative_path, hasher)


def prepare_extension_hook_state(
    hook: ExtensionDepsHookPlan,
) -> PreparedExtensionHookState:
    """Evaluate current extension source fingerprint against recorded state."""
    fingerprint = fingerprint_tree(hook.source_root)
    previous_state = load_extension_hook_state(hook.state_path)
    if previous_state is None or previous_state.fingerprint != fingerprint:
        return PreparedExtensionHookState(
            fingerprint=fingerprint,
            generated_entries=[],
            preserve_paths=[],
            should_skip=False,
            should_refresh_state=False,
        )

    generated_entries = [
        entry_name
        for entry_name in previous_state.generated_entries
        if _exists(str(Path(hook.root) / entry_name))
    ]
    should_skip = len(generated_entries) == len(previous_state.generated_entries)
    should_refresh_state = previous_state.should_refresh_state
    preserve_paths = (
        [
            _join_relative(hook.relative_root, entry_name)
            for entry_name in generated_entries
        ]
        if should_skip
        else []
    )
    return PreparedExtensionHookState(
        fingerprint=fingerprint,
        generated_entries=generated_entries,
        preserve_paths=preserve_paths,
        should_skip=should_skip,
        should_refresh_state=should_refresh_state,
    )


def record_extension_hook_state(
    hook: ExtensionDepsHookPlan,
    prepared_state: PreparedExtensionHookState,
) -> None:
    """Record current extension fingerprint and generated entries."""
    state = {
        "fingerprint": prepared_state.fingerprint,
        "generatedEntries": find_generated_extension_entries(hook.root),
    }
    _write_hook_state_file(hook.state_path, state)


def clear_extension_hook_state(state_path: str | os.PathLike[str]) -> None:
    """Remove extension hook state file on best-effort basis."""
    with contextlib.suppress(OSError):
        Path(state_path).unlink(missing_ok=True)


def find_generated_extension_entries(
    root: str | os.PathLike[str],
) -> list[str]:
    """Find generated package management entries at root and one level deep."""
    root_path = Path(root)
    results: list[str] = [
        entry_name
        for entry_name in GENERATED_EXTENSION_ENTRY_NAMES
        if _exists(str(root_path / entry_name))
    ]

    try:
        for child in os.scandir(root_path):
            if child.is_dir(follow_symlinks=False) and not should_skip_entry(
                child.name
            ):
                for entry_name in GENERATED_EXTENSION_ENTRY_NAMES:
                    relative_path = f"{child.name}/{entry_name}"
                    if _exists(str(root_path / relative_path)):
                        results.append(relative_path)
    except OSError:
        pass

    return list(dict.fromkeys(results))


def should_skip_entry(entry_name: str) -> bool:
    """Check whether a directory entry should be ignored during tree fingerprinting."""
    return (
        entry_name in {"node_modules", ".git"}
        or entry_name.startswith(".")
        or is_ignored_sync_entry(entry_name)
    )


def _is_generated_extension_entry_name(entry_name: str) -> bool:
    base_name = entry_name.rsplit("/", 1)[-1] if "/" in entry_name else entry_name
    return base_name in _GENERATED_EXTENSION_ENTRY_SET


def _normalize_relative_path(path_value: str) -> str:
    return path_value.replace("\\", "/")


def _join_relative(left: str, right: str) -> str:
    return right if len(left) == 0 else f"{left}/{right}"


def _exists(target_path: str) -> bool:
    try:
        p = Path(target_path)
        return p.exists() or p.is_symlink()
    except OSError:
        return False


def load_extension_hook_state(path: str) -> _LoadedExtensionHookState | None:
    try:
        raw_content = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as error:
        warn(f"hook state read failed, ignoring {path} ({error})")
        return None

    try:
        cleaned = strip_jsonc(raw_content)
        parsed: object = json.loads(cleaned)  # pyright: ignore[reportAny]
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError, TypeError) as error:
        warn(f"hook state parse failed, ignoring {path} ({error})")
        return None

    if not isinstance(parsed, dict) or isinstance(parsed, list):
        warn(f"hook state parse failed, ignoring {path} (not an object)")
        return None

    try:
        payload = TypeAdapter(_HookStatePayload).validate_python(parsed)
    except ValidationError:
        warn(f"hook state parse failed, ignoring {path} (invalid shape)")
        return None

    fingerprint: str = payload["fingerprint"]
    raw_entries: list[str] = payload["generatedEntries"]
    normalized = sorted(set(raw_entries))
    filtered = [
        entry for entry in normalized if _is_generated_extension_entry_name(entry)
    ]
    should_refresh = len(filtered) != len(normalized)

    return _LoadedExtensionHookState(
        fingerprint=fingerprint,
        generated_entries=filtered,
        should_refresh_state=should_refresh,
    )


def _write_hook_state_file(path: str, state: Mapping[str, object]) -> None:
    payload = f"{json.dumps(state, indent=2)}\n"
    try:
        existing = Path(path).lstat()
        mode = existing.st_mode & 0o777 if stat.S_ISREG(existing.st_mode) else 0o600
    except OSError:
        mode = 0o600
    sync_text_file(path, payload, mode)
