# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for package dependency installation and build processes."""

from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING

from sync.packages.process import install_package_deps
from sync.packages.validate import package_is_healthy

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

_EXECUTABLE_MODE = 0o755
_TIMEOUT_MS = 5000


def test_manifestless_conventional_package_with_no_imports_needs_no_install(
    tmp_path: Path,
) -> None:
    """Conventional package directory without external imports completes cleanly."""
    skills_sub = tmp_path / "skills" / "sub"
    skills_sub.mkdir(parents=True, exist_ok=True)
    (skills_sub / "noop.ts").write_text("const x = 1;\n", encoding="utf-8")

    result = asyncio.run(install_package_deps(str(tmp_path), _TIMEOUT_MS))
    assert result is True
    assert package_is_healthy(str(tmp_path)) is True


def test_manifestless_package_triggers_bun_add_for_missing_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Inferred imports are installed via bun add --no-save when missing."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    log_file = tmp_path / "bun.log"
    fake_bun = bin_dir / "bun"

    script = f"""#!/bin/sh
if [ "$1" = "add" ] && [ "$2" = "--no-save" ]; then
  mkdir -p "node_modules/$3"
  echo "$PWD $*" >> "{log_file}"
  exit 0
fi
echo "unexpected $*" >&2
exit 1
"""
    fake_bun.write_text(script, encoding="utf-8")
    fake_bun.chmod(_EXECUTABLE_MODE)

    current_path = os.environ.get("PATH", "")
    monkeypatch.setenv("PATH", f"{bin_dir}:{current_path}")

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    (skills_dir / "main.ts").write_text('import "some-pkg";\n', encoding="utf-8")

    result = asyncio.run(install_package_deps(str(tmp_path), _TIMEOUT_MS))
    assert result is True

    calls = [line for line in log_file.read_text(encoding="utf-8").split("\n") if line]
    assert len(calls) == 1
    assert "add --no-save some-pkg" in calls[0]
    assert package_is_healthy(str(tmp_path)) is True


def test_install_package_deps_fails_when_source_file_is_corrupt(
    tmp_path: Path,
) -> None:
    """install_package_deps returns False when dependency scan fails on corrupt file."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    bad_file = skills_dir / "invalid.ts"
    bad_file.write_bytes(b"\xff\xfe\x00\x00")

    result = asyncio.run(install_package_deps(str(tmp_path), _TIMEOUT_MS))
    assert result is False
