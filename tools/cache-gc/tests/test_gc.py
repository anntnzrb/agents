# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
# ruff: noqa: S101, INP001 - pytest asserts; tests load gc.py by path, not as a package
"""Behavior of the cache sweeper's scratch and lock rules."""

from __future__ import annotations

import fcntl
import os
import shutil
import socket
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING

import cache_gc

if TYPE_CHECKING:
    import pytest

gc = cache_gc
OLD = time.time() - 30 * 86400


def _age(path: Path, when: float = OLD) -> None:
    for root, dirs, files in os.walk(path):
        for name in (*dirs, *files):
            os.utime(Path(root, name), (when, when), follow_symlinks=False)
    os.utime(path, (when, when), follow_symlinks=False)


def test_scratch_removes_only_entries_idle_past_the_cutoff(tmp_path: Path) -> None:
    """Idle entries go; a fresh write anywhere inside keeps the whole entry."""
    stale = tmp_path / "agents-ci-old"
    (stale / "deep").mkdir(parents=True)
    _ = (stale / "deep" / "log").write_text("x")
    _age(stale)

    fresh_inside = tmp_path / "pytest-of-annt"
    (fresh_inside / "pytest-1").mkdir(parents=True)
    _age(fresh_inside)
    _ = (fresh_inside / "pytest-1" / "new").write_text("x")

    old_file = tmp_path / "report.json"
    _ = old_file.write_text("{}")
    _age(old_file)

    gc.clean_scratch(tmp_path, days=7, dry_run=False)

    assert not stale.exists()
    assert not old_file.exists()
    assert fresh_inside.is_dir(), "a recent write anywhere inside keeps the entry"


def test_scratch_keeps_runtime_state_and_sockets() -> None:
    """Runtime directories and sockets survive however old they are."""
    # macOS pytest paths exceed the AF_UNIX limit, so use a short root.
    tmp_path = Path(tempfile.mkdtemp(prefix="gc", dir="/tmp"))
    kept = [
        tmp_path / ".X11-unix",
        tmp_path / "tmux-1000",
        tmp_path / "systemd-private-abc-cliproxyapi.service-x",
        tmp_path / "nix-build-1",
    ]
    for path in kept:
        path.mkdir()
        _age(path)
    lock = tmp_path / "uv-28cc4b8c9dcd1219.lock"
    lock.touch()
    _age(lock)
    kept.append(lock)
    sock_path = tmp_path / "s"
    server = socket.socket(socket.AF_UNIX)
    server.bind(str(sock_path))
    try:
        os.utime(sock_path, (OLD, OLD))
        gc.clean_scratch(tmp_path, days=7, dry_run=False)
        assert sock_path.exists()
    finally:
        server.close()
    assert all(path.exists() for path in kept)
    shutil.rmtree(tmp_path)


def test_scratch_dry_run_removes_nothing(tmp_path: Path) -> None:
    """A dry run only reports."""
    stale = tmp_path / "old"
    stale.mkdir()
    _age(stale)
    gc.clean_scratch(tmp_path, days=7, dry_run=True)
    assert stale.is_dir()


def test_scratch_skips_entries_owned_by_another_user(tmp_path: Path) -> None:
    """Another user's files are never candidates."""
    stale = tmp_path / "old"
    stale.mkdir()
    _age(stale)
    assert gc.stale_scratch(tmp_path, os.getuid() + 1, time.time()) == []


def test_npm_is_skipped_while_a_launcher_holds_an_npm_tools_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A launcher mid-install keeps npm's cache; a free lock lets it clean."""
    home = tmp_path / "home"
    (home / ".npm" / "_cacache").mkdir(parents=True)
    lock = tmp_path / "cache" / "npm-tools" / "claude" / "lock"
    lock.parent.mkdir(parents=True)
    lock.touch()
    ran: list[list[str]] = []

    def record(argv: list[str], **_kwargs: object) -> bool:
        ran.append(argv)
        return True

    monkeypatch.setattr(gc, "run", record)

    fd = os.open(lock, os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        gc.clean_npm(home, tmp_path / "cache", dry_run=False)
        assert ran == []
    finally:
        os.close(fd)

    gc.clean_npm(home, tmp_path / "cache", dry_run=False)
    assert ran == [["npm", "cache", "clean", "--force"]]
