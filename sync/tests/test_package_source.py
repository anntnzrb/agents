# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for package source resolution, FNV-1a64 hashing, and replacement."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sync.packages.source import (
    clone_package_with_runner,
    fnv1a64,
    replace_dir_atomically,
)

if TYPE_CHECKING:
    from collections.abc import Sequence


def test_fnv1a64_matches_golden_vectors() -> None:
    """Verify fnv1a64 produces expected 16-hex hashes against golden vectors."""
    vectors_path = Path(__file__).parent / "golden" / "fnv-vectors.json"
    data = json.loads(vectors_path.read_text(encoding="utf-8"))
    for case in data["cases"]:
        assert fnv1a64(case["input"]) == case["fnv"]


def test_gh_fallback_removes_partial_files_and_leaves_expected_checkout(
    tmp_path: Path,
) -> None:
    """clone_package_with_runner falls back from gh to git and clears partial state."""
    target = tmp_path / "out"
    target.mkdir(parents=True, exist_ok=True)
    attempts: list[list[str]] = []
    first = True

    async def runner(command: Sequence[str]) -> bool:
        nonlocal first
        attempts.append(list(command))
        target.mkdir(parents=True, exist_ok=True)
        if first:
            first = False
            (target / "partial.txt").write_text("partial", encoding="utf-8")
            return False
        (target / "expected.txt").write_text("expected", encoding="utf-8")
        return True

    async def run_test() -> None:
        result = await clone_package_with_runner(
            "https://github.com/owner/repo",
            str(target),
            gh_available=True,
            runner=runner,
        )
        assert result is True

    asyncio.run(run_test())

    assert attempts[0][0] == "gh"
    assert attempts[1][0] == "git"
    assert not (target / "partial.txt").exists()
    assert (target / "expected.txt").read_text(encoding="utf-8") == "expected"


def test_final_failure_removes_all_partial_state(
    tmp_path: Path,
) -> None:
    """clone_package_with_runner clears target directory when all commands fail."""
    target = tmp_path / "out"
    target.mkdir(parents=True, exist_ok=True)
    attempts: list[list[str]] = []

    async def runner(command: Sequence[str]) -> bool:
        attempts.append(list(command))
        target.mkdir(parents=True, exist_ok=True)
        (target / "partial.txt").write_text("partial", encoding="utf-8")
        return False

    async def run_test() -> None:
        result = await clone_package_with_runner(
            "https://github.com/owner/repo",
            str(target),
            gh_available=True,
            runner=runner,
        )
        assert result is False

    asyncio.run(run_test())

    assert attempts[0][0] == "gh"
    assert attempts[1][0] == "git"
    assert not (target / "partial.txt").exists()


def test_replace_dir_atomically_cleans_up_backup_directories_on_success(
    tmp_path: Path,
) -> None:
    """replace_dir_atomically moves src to dst and removes temporary backups."""
    dst = tmp_path / "my-package"
    src = tmp_path / "my-package.staging-123-456"
    dst.mkdir(parents=True, exist_ok=True)
    (dst / "file.txt").write_text("old-version", encoding="utf-8")
    src.mkdir(parents=True, exist_ok=True)
    (src / "file.txt").write_text("new-version", encoding="utf-8")

    legacy_backup = tmp_path / "my-package.backup"
    legacy_backup.mkdir(parents=True, exist_ok=True)
    (legacy_backup / "file.txt").write_text("legacy", encoding="utf-8")

    asyncio.run(replace_dir_atomically(str(src), str(dst)))

    assert not src.exists()
    assert dst.exists()
    assert (dst / "file.txt").read_text(encoding="utf-8") == "new-version"

    entries = [p.name for p in tmp_path.iterdir()]
    assert entries == ["my-package"]


def test_replace_dir_atomically_restores_previous_content_on_failure(
    tmp_path: Path,
) -> None:
    """replace_dir_atomically rolls back backup to dst when src replacement fails."""
    dst = tmp_path / "my-package"
    non_existent_src = tmp_path / "non-existent-src"
    dst.mkdir(parents=True, exist_ok=True)
    (dst / "file.txt").write_text("preserved-content", encoding="utf-8")

    with pytest.raises(FileNotFoundError):
        asyncio.run(replace_dir_atomically(str(non_existent_src), str(dst)))

    assert dst.exists()
    assert (dst / "file.txt").read_text(encoding="utf-8") == "preserved-content"

    entries = [p.name for p in tmp_path.iterdir()]
    assert entries == ["my-package"]
