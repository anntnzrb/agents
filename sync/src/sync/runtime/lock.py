# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""File-based advisory locking for single-instance sync execution."""

from __future__ import annotations

import asyncio
import contextlib
import errno
import fcntl
import os
import time
from dataclasses import dataclass
from pathlib import Path

from sync.runtime.errors import panic_message

__all__ = [
    "SyncLock",
    "acquire_cache_lock",
    "release_sync_lock",
    "try_acquire_sync_lock",
]

_LOCK_FILE_MODE: int = 0o644
_WOULD_BLOCK_ERRNOS: frozenset[int] = frozenset({errno.EAGAIN, errno.EWOULDBLOCK})


@dataclass(frozen=True, slots=True)
class SyncLock:
    """An acquired file-based exclusive lock."""

    fd: int


def try_acquire_sync_lock(
    state_dir: str | Path,
    lock_path: str | Path,
) -> SyncLock | None:
    """Attempt to acquire an exclusive lock on the sync state directory.

    Creates state_dir if missing, opens lock_path, and applies an exclusive
    non-blocking flock. Writes the current process PID to the lock file.
    Returns SyncLock on success, or None if the lock is held by another process.
    """
    state_dir_path = Path(state_dir)
    lock_path_str = str(Path(lock_path))

    try:
        state_dir_path.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        message = f"create sync state dir {state_dir} ({panic_message(error)})"
        raise RuntimeError(message) from error

    try:
        fd = os.open(lock_path_str, os.O_CREAT | os.O_RDWR, _LOCK_FILE_MODE)
    except OSError as error:
        message = f"open sync lock {lock_path_str} ({panic_message(error)})"
        raise RuntimeError(message) from error

    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.ftruncate(fd, 0)
        _ = os.lseek(fd, 0, os.SEEK_SET)
        _ = os.write(fd, f"pid={os.getpid()}\n".encode())
        os.fsync(fd)
    except (BlockingIOError, OSError) as error:
        with contextlib.suppress(OSError):
            os.close(fd)
        if isinstance(error, BlockingIOError) or error.errno in _WOULD_BLOCK_ERRNOS:
            return None
        message = f"lock sync {lock_path_str} ({panic_message(error)})"
        raise RuntimeError(message) from error

    return SyncLock(fd=fd)


def release_sync_lock(lock: SyncLock) -> None:
    """Release an acquired sync lock by closing its file descriptor."""
    with contextlib.suppress(OSError):
        os.close(lock.fd)


async def acquire_cache_lock(
    lock_root: str,
    lock_file: str,
    timeout_ms: int,
) -> SyncLock:
    """Acquire an exclusive cache lock, retrying until the timeout elapses."""
    started_at = time.monotonic()
    timeout_seconds = timeout_ms / 1000.0
    while True:
        lock = try_acquire_sync_lock(lock_root, lock_file)
        if lock is not None:
            return lock
        if time.monotonic() - started_at >= timeout_seconds:
            message = f"timed out waiting for cache lock: {lock_file}"
            raise TimeoutError(message)
        await asyncio.sleep(0.025)
