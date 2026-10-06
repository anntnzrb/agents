# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Reclaim npm cache while holding lock on npm-tools caches."""

from __future__ import annotations

import contextlib
import fcntl
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

COMMAND_TIMEOUT_SECONDS = 600


def say(msg: str) -> None:
    """Report one line to the service log."""
    _ = sys.stdout.write(f"npm-cache-clean: {msg}\n")
    _ = sys.stdout.flush()


def size_mb(path: Path) -> int:
    """Return the allocated size of a tree in MiB, ignoring unreadable entries."""
    total = 0
    for root, _dirs, files in os.walk(path, onerror=lambda _e: None):
        for name in files:
            with contextlib.suppress(OSError):
                total += (Path(root) / name).lstat().st_blocks * 512
    return total // (1024 * 1024)


def acquire_npm_tool_locks(cache_home: Path) -> list[int] | None:
    """Lock every npm-tools cache; return the held fds, or None if any is busy."""
    held: list[int] = []
    for lock in sorted((cache_home / "npm-tools").glob("*/lock")):
        try:
            fd = os.open(lock, os.O_RDWR)
        except OSError:
            continue
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            release(held)
            return None
        held.append(fd)
    return held


def release(fds: Sequence[int]) -> None:
    """Close lock fds, which drops their flocks."""
    for fd in fds:
        with contextlib.suppress(OSError):
            os.close(fd)


def _execute_clean(
    run_cmd: Callable[[list[str]], int] | None,
) -> int:
    cmd = ["npm", "cache", "clean", "--force"]
    if run_cmd is not None:
        return run_cmd(cmd)
    result = subprocess.run(  # noqa: S603
        cmd,
        capture_output=True,
        text=True,
        check=False,
        timeout=COMMAND_TIMEOUT_SECONDS,
    )
    rc = result.returncode
    if rc != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()[-1:]
        say(f"npm cache clean --force exited {rc}: {' '.join(detail)}")
    return rc


def clean_npm_cache(
    *,
    home: Path | None = None,
    cache_home: Path | None = None,
    dry_run: bool = False,
    run_cmd: Callable[[list[str]], int] | None = None,
) -> int:
    """Empty npm's content cache unless a launcher is installing."""
    if shutil.which("npm") is None:
        say("skip npm: not installed")
        return 0
    h = home or Path.home()
    c_home = cache_home or Path(os.environ.get("XDG_CACHE_HOME") or h / ".cache")
    cache = h / ".npm" / "_cacache"
    if not cache.is_dir():
        say("skip npm: cache directory does not exist")
        return 0
    before = size_mb(cache)
    held = acquire_npm_tool_locks(c_home)
    if held is None:
        say("skip npm: a launcher holds an npm-tools lock")
        return 0
    try:
        if dry_run:
            say("would run: npm cache clean --force")
            return 0
        rc = _execute_clean(run_cmd)
        if rc != 0:
            say(f"npm cache clean --force failed with exit code {rc}")
            return rc
    finally:
        release(held)
    after = size_mb(cache) if cache.exists() else 0
    say(f"npm cache {before}M -> {after}M")
    return 0
