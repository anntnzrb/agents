#!/usr/bin/env python3
# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Reclaim package-manager caches and stale agent scratch on this host.

Sync's launchers resolve the newest release on every launch, and the package
managers behind them keep every download forever: npm's content cache, bun's
install cache, and uv's archive cache only grow. Agents also leave scratch
directories in /tmp. This script trims those, and nothing else:

- npm: `npm cache clean --force`, only while holding every npm-tools cache lock,
  so a launcher install never loses its cache mid-flight. A held lock skips npm.
- uv: `uv cache prune`, which keeps entries in use and skips a locked cache.
- bun: empty the legacy ~/.bun and XDG install caches (tarballs only).
- /tmp: top-level entries this user owns whose newest modification is older than
  SCRATCH_DAYS. Sockets, multiplexer and service-private directories are kept.

Harness homes (sessions, runtimes, browsers) are owned by their harnesses and are
never touched. Every step is best-effort: a failure is reported and the rest run.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import os
import shutil
import stat
import subprocess
import time
from pathlib import Path

SCRATCH_DAYS = 7
COMMAND_TIMEOUT_SECONDS = 600
SCRATCH_ROOT = Path("/tmp")  # noqa: S108 - the shared scratch root is the target
# Live runtime state that other processes find by name; never removed.
KEEP_PREFIXES = (
    ".",
    "tmux-",
    "zellij-",
    "systemd-private-",
    "ssh-",
    "com.apple.",
    "launchd-",
    "nix-",
)


def say(message: str) -> None:
    """Report one line to the service log."""
    print(f"cache-gc: {message}", flush=True)  # noqa: T201 - stdout is the journal


def size_mb(path: Path) -> int:
    """Return the allocated size of a tree in MiB, ignoring unreadable entries."""
    total = 0
    for root, _dirs, files in os.walk(path, onerror=lambda _e: None):
        for name in files:
            with contextlib.suppress(OSError):
                total += (Path(root) / name).lstat().st_blocks * 512
    return total // (1024 * 1024)


def run(argv: list[str], *, dry_run: bool, cwd: Path | None = None) -> bool:
    """Run one fixed cleanup command; report and return False on any failure."""
    if shutil.which(argv[0]) is None:
        say(f"skip {argv[0]}: not installed")
        return False
    if dry_run:
        say(f"would run: {' '.join(argv)}")
        return True
    try:
        result = subprocess.run(  # noqa: S603 - fixed argv, no shell
            argv,
            capture_output=True,
            text=True,
            check=False,
            timeout=COMMAND_TIMEOUT_SECONDS,
            cwd=cwd,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        say(f"{argv[0]} failed: {error}")
        return False
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()[-1:]
        say(f"{' '.join(argv)} exited {result.returncode}: {' '.join(detail)}")
        return False
    return True


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


def release(fds: list[int]) -> None:
    """Close lock fds, which drops their flocks."""
    for fd in fds:
        with contextlib.suppress(OSError):
            os.close(fd)


def clean_npm(home: Path, cache_home: Path, *, dry_run: bool) -> None:
    """Empty npm's content cache unless a launcher is installing."""
    cache = home / ".npm" / "_cacache"
    if not cache.is_dir():
        return
    before = size_mb(cache)
    held = acquire_npm_tool_locks(cache_home)
    if held is None:
        say("skip npm: a launcher holds an npm-tools lock")
        return
    try:
        _ = run(["npm", "cache", "clean", "--force"], dry_run=dry_run)
    finally:
        release(held)
    say(f"npm cache {before}M -> {size_mb(cache) if cache.exists() else 0}M")


def clean_uv(home: Path, cache_home: Path, *, dry_run: bool) -> None:
    """Prune uv's unreferenced archives and environments."""
    cache = Path(os.environ.get("UV_CACHE_DIR") or cache_home / "uv")
    if not cache.is_dir():
        return
    before = size_mb(cache)
    _ = run(["uv", "cache", "prune"], dry_run=dry_run, cwd=home)
    say(f"uv cache {before}M -> {size_mb(cache)}M")


def clean_bun(home: Path, cache_home: Path, *, dry_run: bool) -> None:
    """Empty every bun install cache.

    Bun moved its default cache from ~/.bun to the XDG cache home, and
    `bun pm cache rm` clears only the one it currently resolves, so the legacy
    cache would grow forever. Both hold re-downloadable tarballs only.
    """
    for cache in (
        home / ".bun" / "install" / "cache",
        cache_home / ".bun" / "install" / "cache",
    ):
        if not cache.is_dir():
            continue
        before = size_mb(cache)
        for entry in list(cache.iterdir()):
            if dry_run:
                continue
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry, ignore_errors=True)
            else:
                with contextlib.suppress(OSError):
                    entry.unlink()
        say(f"bun cache {cache}: {before}M -> {size_mb(cache)}M")


def newest_mtime(path: Path) -> float:
    """Newest modification time of an entry and everything beneath it."""
    try:
        newest = path.lstat().st_mtime
    except OSError:
        return time.time()
    if not path.is_dir() or path.is_symlink():
        return newest
    for root, dirs, files in os.walk(path, onerror=lambda _e: None):
        for name in (*dirs, *files):
            with contextlib.suppress(OSError):
                newest = max(newest, (Path(root) / name).lstat().st_mtime)
    return newest


def stale_scratch(root: Path, uid: int, cutoff: float) -> list[Path]:
    """List top-level entries this user owns that went untouched since cutoff."""
    stale: list[Path] = []
    try:
        entries = list(root.iterdir())
    except OSError:
        return stale
    for entry in entries:
        # Lock files are flock targets; unlinking a held one breaks exclusion.
        if entry.name.startswith(KEEP_PREFIXES) or entry.name.endswith(".lock"):
            continue
        try:
            info = entry.lstat()
        except OSError:
            continue
        if info.st_uid != uid or stat.S_ISSOCK(info.st_mode):
            continue
        if newest_mtime(entry) < cutoff:
            stale.append(entry)
    return stale


def clean_scratch(root: Path, *, days: int, dry_run: bool) -> None:
    """Remove scratch entries idle for more than ``days`` days."""
    cutoff = time.time() - days * 86400
    stale = stale_scratch(root, os.getuid(), cutoff)
    freed = 0
    for entry in stale:
        freed += size_mb(entry) if entry.is_dir() else 0
        if dry_run:
            say(f"would remove {entry}")
            continue
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry, ignore_errors=True)
        else:
            with contextlib.suppress(OSError):
                entry.unlink()
    say(f"{root}: {len(stale)} entries idle >{days}d, ~{freed}M")


def main() -> int:
    """Run every cleanup step once."""
    parser = argparse.ArgumentParser(description="Reclaim caches and stale scratch.")
    _ = parser.add_argument("--dry-run", action="store_true", help="report only")
    _ = parser.add_argument("--scratch-days", type=int, default=SCRATCH_DAYS)
    args = parser.parse_args()
    dry_run = bool(args.dry_run)  # pyright: ignore[reportAny] - argparse namespace
    days = int(args.scratch_days)  # pyright: ignore[reportAny] - argparse namespace
    home = Path.home()
    cache_home = Path(os.environ.get("XDG_CACHE_HOME") or home / ".cache")
    clean_npm(home, cache_home, dry_run=dry_run)
    clean_uv(home, cache_home, dry_run=dry_run)
    clean_bun(home, cache_home, dry_run=dry_run)
    clean_scratch(SCRATCH_ROOT, days=days, dry_run=dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
