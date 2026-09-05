# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for extension dependency installation and runner."""

from __future__ import annotations

import asyncio
import json
import os
from typing import TYPE_CHECKING

from sync.extensions.install import (
    install_extension_deps,
    iter_extension_packages,
)

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

_EXECUTABLE_MODE = 0o755
_TIMEOUT_MS = 5000


def test_iter_extension_packages_finds_nested_package_jsons(
    tmp_path: Path,
) -> None:
    """iter_extension_packages finds package.json dirs excluding node_modules."""
    ext1 = tmp_path / "ext1"
    ext1.mkdir(parents=True, exist_ok=True)
    (ext1 / "package.json").write_text("{}", encoding="utf-8")

    ext2 = tmp_path / "nested" / "ext2"
    ext2.mkdir(parents=True, exist_ok=True)
    (ext2 / "package.json").write_text("{}", encoding="utf-8")

    ignored = tmp_path / "node_modules" / "ignored"
    ignored.mkdir(parents=True, exist_ok=True)
    (ignored / "package.json").write_text("{}", encoding="utf-8")

    packages = asyncio.run(iter_extension_packages(str(tmp_path)))
    assert sorted(packages) == [str(ext1), str(ext2)]


def test_install_extension_deps_runs_bun_install_for_package_dirs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """install_extension_deps invokes bun install on discovered extension dirs."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    log_file = tmp_path / "installs.log"
    fake_bun = bin_dir / "bun"

    script = f"""#!/bin/sh
if [ "$1" = "install" ]; then
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

    ext = tmp_path / "ext"
    ext.mkdir(parents=True, exist_ok=True)
    (ext / "node_modules").mkdir(parents=True, exist_ok=True)
    (ext / "package.json").write_text(
        json.dumps({"name": "ext", "dependencies": {"chalk": "^5"}}) + "\n",
        encoding="utf-8",
    )

    result = asyncio.run(
        install_extension_deps(str(tmp_path), str(tmp_path), _TIMEOUT_MS)
    )
    assert result is True

    calls = [line for line in log_file.read_text(encoding="utf-8").split("\n") if line]
    assert len(calls) == 1
    assert f"{ext} install" in calls[0]
