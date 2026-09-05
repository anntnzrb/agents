# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""File-based advisory locking for single-instance sync execution."""

from __future__ import annotations

import contextlib
import errno
import fcntl
import os
from dataclasses import dataclass
from pathlib import Path

from sync.runtime.errors import panic_message

__all__ = [
    "SyncLock",
    "release_sync_lock",
    "try_acquire_sync_lock",
]

LOCK_FILE_MODE: int = 0o644
FILE_START_OFFSET: int = 0
TRUNCATE_SIZE: int = 0
WOULD_BLOCK_ERRNOS: frozenset[int] = frozenset({errno.EAGAIN, errno.EWOULDBLOCK})


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
    lock_path_path = Path(lock_path)
    state_dir_str = str(state_dir_path)
    lock_path_str = str(lock_path_path)

    try:
        state_dir_path.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        message = f"create sync state dir {state_dir_str} ({panic_message(error)})"
        raise RuntimeError(message) from error

    try:
        fd = os.open(
            lock_path_str,
            os.O_CREAT | os.O_RDWR,
            LOCK_FILE_MODE,
        )
    except OSError as error:
        message = f"open sync lock {lock_path_str} ({panic_message(error)})"
        raise RuntimeError(message) from error

    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError) as error:
        with contextlib.suppress(OSError):
            os.close(fd)
        if isinstance(error, BlockingIOError) or error.errno in WOULD_BLOCK_ERRNOS:
            return None
        message = f"lock sync {lock_path_str} ({panic_message(error)})"
        raise RuntimeError(message) from error

    try:
        os.ftruncate(fd, TRUNCATE_SIZE)
        _ = os.lseek(fd, FILE_START_OFFSET, os.SEEK_SET)
    except OSError as error:
        with contextlib.suppress(OSError):
            os.close(fd)
        message = f"clear sync lock {lock_path_str} ({panic_message(error)})"
        raise RuntimeError(message) from error

    try:
        pid_payload = f"pid={os.getpid()}\n".encode()
        _ = os.write(fd, pid_payload)
        os.fsync(fd)
    except OSError as error:
        with contextlib.suppress(OSError):
            os.close(fd)
        message = f"write sync lock {lock_path_str} ({panic_message(error)})"
        raise RuntimeError(message) from error

    return SyncLock(fd=fd)


def release_sync_lock(lock: SyncLock) -> None:
    """Release an acquired sync lock by closing its file descriptor."""
    with contextlib.suppress(OSError):
        os.close(lock.fd)
