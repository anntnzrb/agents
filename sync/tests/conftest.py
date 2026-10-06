# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Pytest configuration, shared caches, and environment fixtures."""

from __future__ import annotations

import atexit
import os
import shutil
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

# Git exports GIT_DIR (and friends) to hooks run from linked worktrees. Scrub
# every repository-locating variable so fixtures that shell out to git never
# operate on this repository instead of their temporary one.
for _git_env_var in subprocess.check_output(  # noqa: S603 - fixed git query
    [shutil.which("git") or "git", "rev-parse", "--local-env-vars"], text=True
).split():
    _ = os.environ.pop(_git_env_var, None)

# Resolve uv's configured paths before fixtures replace HOME/XDG_CACHE_HOME.
# Workers share dependency caches, not test homes or installed releases.
UV_BIN = shutil.which("uv") or "uv"
shared_tool_cache_env: dict[str, str] = {
    "UV_CACHE_DIR": subprocess.check_output(  # noqa: S603 - fixed uv query
        [UV_BIN, "--color", "never", "cache", "dir"], text=True
    ).strip(),
    "UV_PYTHON_INSTALL_DIR": subprocess.check_output(  # noqa: S603 - fixed uv query
        [UV_BIN, "--color", "never", "python", "dir"], text=True
    ).strip(),
}

PRISTINE_PATH: str = os.environ.get("PATH", "")

# Tests run real sync reconciles, which call `systemctl --user`. That client
# finds the live user manager through XDG_RUNTIME_DIR (or D-Bus), so a test home
# alone would still reload and restart the developer's real services. Point the
# whole session, and every subprocess it spawns, at a manager that does not exist.
_TEST_RUNTIME_DIR = tempfile.mkdtemp(prefix="agents-test-runtime-")
_ = atexit.register(shutil.rmtree, _TEST_RUNTIME_DIR, ignore_errors=True)
os.environ["XDG_RUNTIME_DIR"] = _TEST_RUNTIME_DIR
os.environ["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=/nonexistent-agents-test-bus"
_ = os.environ.pop("DBUS_SYSTEM_BUS_ADDRESS", None)


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


def ssot_root(home: Path) -> Path:
    """Return the SSOT checkout root under the given home directory."""
    return home / "src" / "agents"


_ = atexit.register(_cleanup_shared_caches)


def _build_shared_release() -> SharedRelease:
    template_home = Path(tempfile.mkdtemp(prefix="agents-shared-release-"))
    source = ssot_root(template_home) / "sync"
    source.mkdir(parents=True, exist_ok=True)
    _ = shutil.copytree(SYNC_ROOT / "src", source / "src")
    for filename in ("pyproject.toml", "uv.lock", "README.md"):
        file_path = SYNC_ROOT / filename
        if file_path.is_file():
            _ = shutil.copyfile(file_path, source / filename)

    # Sync aborts on missing agents settings before reaching the runtime
    # install job, so write minimal settings.
    _ = (ssot_root(template_home) / "agents.toml").write_text(
        '[gateway]\nbase_url = "http://127.0.0.1:1/v1"\n',
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
