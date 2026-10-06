# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the npm cache cleaner and npm-tools lock handling."""

from __future__ import annotations

import fcntl
import os
import shutil
from typing import TYPE_CHECKING

import pytest

from sync.maintenance.npm_cache import clean_npm_cache

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("dry_run", [False, True])
def test_npm_clean_skipped_when_npm_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, dry_run: bool
) -> None:
    """If npm is not on PATH, skip with exit code 0."""

    def fake_which(_prog: str) -> str | None:
        return None

    monkeypatch.setattr(shutil, "which", fake_which)
    assert clean_npm_cache(home=tmp_path, dry_run=dry_run) == 0


def test_npm_clean_skipped_when_no_cache_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If .npm/_cacache does not exist, skip with exit code 0."""

    def fake_which(_prog: str) -> str | None:
        return "/usr/bin/npm"

    monkeypatch.setattr(shutil, "which", fake_which)
    assert clean_npm_cache(home=tmp_path) == 0


def test_npm_is_skipped_while_a_launcher_holds_an_npm_tools_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A launcher mid-install keeps npm's cache; a free lock lets it clean."""

    def fake_which(_prog: str) -> str | None:
        return "/usr/bin/npm"

    monkeypatch.setattr(shutil, "which", fake_which)
    home = tmp_path / "home"
    (home / ".npm" / "_cacache").mkdir(parents=True)
    lock = tmp_path / "cache" / "npm-tools" / "claude" / "lock"
    lock.parent.mkdir(parents=True)
    lock.touch()
    ran: list[list[str]] = []

    def record(argv: list[str]) -> int:
        ran.append(argv)
        return 0

    fd = os.open(lock, os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        rc = clean_npm_cache(
            home=home, cache_home=tmp_path / "cache", dry_run=False, run_cmd=record
        )
        assert rc == 0
        assert ran == []
    finally:
        os.close(fd)

    rc = clean_npm_cache(
        home=home, cache_home=tmp_path / "cache", dry_run=False, run_cmd=record
    )
    assert rc == 0
    assert ran == [["npm", "cache", "clean", "--force"]]
