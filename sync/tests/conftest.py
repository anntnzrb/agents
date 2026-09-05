# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Pytest configuration, shared caches, and environment fixtures."""

from __future__ import annotations

import atexit
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

SYNC_ROOT: Path = Path(__file__).resolve().parent.parent

# Shared temporary cache directory for isolated test execution
SHARED_CACHE_DIR: Path = Path(tempfile.mkdtemp(prefix="agents-test-cache-"))

shared_tool_cache_env: dict[str, str] = {
    "UV_CACHE_DIR": os.environ.get("UV_CACHE_DIR", str(SHARED_CACHE_DIR / "uv")),
    "UV_PYTHON_INSTALL_DIR": os.environ.get(
        "UV_PYTHON_INSTALL_DIR", str(SHARED_CACHE_DIR / "uv-python")
    ),
}

PRISTINE_PATH: str = os.environ.get("PATH", "")


@dataclass(frozen=True, slots=True)
class SharedRelease:
    """Directory and metadata of the session-cached prebuilt release."""

    dir: Path
    template_home: Path
    id: str


class ReleaseCache:
    """Container holding the session-cached prebuilt release."""

    release: SharedRelease | None = None


_RELEASE_CACHE = ReleaseCache()


def _cleanup_shared_caches() -> None:
    if _RELEASE_CACHE.release is not None:
        shutil.rmtree(_RELEASE_CACHE.release.template_home, ignore_errors=True)
        _RELEASE_CACHE.release = None
    shutil.rmtree(SHARED_CACHE_DIR, ignore_errors=True)


_ = atexit.register(_cleanup_shared_caches)


def _build_shared_release() -> SharedRelease:
    template_home = Path(tempfile.mkdtemp(prefix="agents-shared-release-"))
    source = template_home / ".config" / "agents" / "sync"
    source.mkdir(parents=True, exist_ok=True)
    _ = shutil.copytree(SYNC_ROOT / "src", source / "src")
    for filename in ("pyproject.toml", "uv.lock", "README.md"):
        file_path = SYNC_ROOT / filename
        if file_path.is_file():
            _ = shutil.copyfile(file_path, source / filename)

    # Sync aborts on a missing deployment manifest before reaching the
    # runtime install job, so create a minimal dummy manifest.
    tools = template_home / ".config" / "agents" / "tools" / "cliproxyapi"
    tools.mkdir(parents=True, exist_ok=True)
    deployment = {
        "server": {"hostname": socket.gethostname()},
        "listen": {"host": "100.64.0.42", "port": 8317},
        "client": {"baseUrl": "http://127.0.0.1:1/v1"},
    }
    _ = (tools / "deployment.json").write_text(
        f"{json.dumps(deployment)}\n",
        encoding="utf-8",
    )

    env = {
        **os.environ,
        "HOME": str(template_home),
        "XDG_CACHE_HOME": str(template_home / ".cache"),
        "PATH": PRISTINE_PATH,
        **shared_tool_cache_env,
    }

    built = subprocess.run(
        [sys.executable, "-m", "sync.cli"],
        cwd=str(SYNC_ROOT),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )

    releases_root = template_home / ".local" / "share" / "agents" / "sync-releases"
    release_id: str | None = None
    if releases_root.is_dir():
        for entry in releases_root.iterdir():
            if entry.is_dir() and not entry.name.startswith(".stage-"):
                release_id = entry.name
                break

    if release_id is None:
        err_msg = built.stderr or built.stdout or "unknown failure"
        msg = f"shared test release was not produced: {err_msg}"
        raise RuntimeError(msg)

    return SharedRelease(
        dir=releases_root / release_id,
        template_home=template_home,
        id=release_id,
    )


def seed_runtime_release(home: Path) -> None:
    """Seed `home` with prebuilt release so SyncRuntimeInstall reuses it."""
    if _RELEASE_CACHE.release is None:
        _RELEASE_CACHE.release = _build_shared_release()
    release = _RELEASE_CACHE.release
    target = home / ".local" / "share" / "agents" / "sync-releases" / release.id
    target.mkdir(parents=True, exist_ok=True)
    _ = shutil.copytree(release.dir / "src", target / "src", dirs_exist_ok=True)
    for filename in (
        "pyproject.toml",
        "uv.lock",
        "README.md",
        ".release-complete",
    ):
        file_path = release.dir / filename
        if file_path.is_file():
            _ = shutil.copyfile(file_path, target / filename)
    venv_dir = release.dir / ".venv"
    target_venv = target / ".venv"
    if venv_dir.is_dir() and not target_venv.exists():
        target_venv.symlink_to(venv_dir, target_is_directory=True)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Yield temporary home with caches and paths pointed at test sandbox."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / ".cache"))
    monkeypatch.setenv("UV_CACHE_DIR", shared_tool_cache_env["UV_CACHE_DIR"])
    monkeypatch.setenv(
        "UV_PYTHON_INSTALL_DIR", shared_tool_cache_env["UV_PYTHON_INSTALL_DIR"]
    )
    monkeypatch.setenv("PATH", PRISTINE_PATH)
    yield tmp_path
    monkeypatch.undo()


@pytest.fixture
def seeded_home(home: Path) -> Path:
    """Yield temporary home seeded with prebuilt runtime release."""
    seed_runtime_release(home)
    return home
