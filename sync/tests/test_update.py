# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for ``sync update``: background fast-forward of the SSOT, then reconcile.

Every machine converges on ``origin/main``. The updater never blocks, merges,
stashes, or resets: a busy lock, a dirty checkout, another branch, or diverged
history leaves the checkout untouched. Reconcile runs only when the checked-out
commit has not been synced yet.
"""

from __future__ import annotations

import asyncio
import subprocess
from typing import TYPE_CHECKING

import pytest

from sync.core.harness import SyncEnv
from sync.core.index import EXIT_ERROR, EXIT_OK, update_main
from sync.core.update import (
    LAUNCHD_LABEL,
    UPDATE_UNIT,
    reconcile_update_schedule,
)
from sync.runtime.process import ProcessResult

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(  # noqa: S603 - fixed git invocation in tests
        ["git", "-C", str(cwd), *args],  # noqa: S607 - git from PATH
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _commit(repo: Path, name: str) -> str:
    _ = (repo / name).write_text(name)
    _ = _git(repo, "add", name)
    _ = _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", name)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repos(home: Path, tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """Return (ssot checkout, peer clone) sharing a bare origin on ``main``."""
    root = tmp_path_factory.mktemp("remote")
    origin = root / "origin.git"
    _ = _git(root, "init", "-q", "--bare", "-b", "main", str(origin))
    peer = root / "peer"
    _ = _git(root, "clone", "-q", str(origin), str(peer))
    _ = _git(peer, "checkout", "-qb", "main")
    _ = _commit(peer, "base")
    _ = _git(peer, "push", "-q", "origin", "main")
    ssot = home / ".config" / "agents"
    ssot.parent.mkdir(parents=True, exist_ok=True)
    _ = _git(home, "clone", "-q", str(origin), str(ssot))
    return ssot, peer


def _push_new_commit(peer: Path, name: str) -> str:
    sha = _commit(peer, name)
    _ = _git(peer, "push", "-q", "origin", "main")
    return sha


def _no_lock(_env: SyncEnv) -> None:
    """Report lock contention: the caller treats None as 'lock unavailable'."""


@pytest.fixture
def syncs(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record reconcile runs instead of executing them."""
    calls: list[str] = []

    async def _sync(_env: SyncEnv, **_kwargs: object) -> bool:
        calls.append("sync")
        return True

    monkeypatch.setattr("sync.core.index.run_sync", _sync)
    return calls


def test_update_fast_forwards_clean_checkout_and_reconciles(
    repos: tuple[Path, Path], syncs: list[str]
) -> None:
    """A clean checkout behind origin fast-forwards, then reconciles once."""
    ssot, peer = repos
    new_head = _push_new_commit(peer, "change")

    assert update_main() == EXIT_OK
    assert _git(ssot, "rev-parse", "HEAD") == new_head
    assert syncs == ["sync"]


def test_update_skips_reconcile_when_head_already_synced(
    repos: tuple[Path, Path], syncs: list[str]
) -> None:
    """A second run with nothing new neither pulls nor reconciles."""
    _, peer = repos
    _ = _push_new_commit(peer, "change")

    assert update_main() == EXIT_OK
    assert update_main() == EXIT_OK
    assert syncs == ["sync"]


def test_update_retries_reconcile_after_failure(
    repos: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed reconcile is not recorded, so the next run retries it."""
    _, peer = repos
    _ = _push_new_commit(peer, "change")
    results = [False, True]
    calls: list[bool] = []

    async def _sync(_env: SyncEnv, **_kwargs: object) -> bool:
        calls.append(results[len(calls)])
        return calls[-1]

    monkeypatch.setattr("sync.core.index.run_sync", _sync)

    assert update_main() == EXIT_ERROR
    assert update_main() == EXIT_OK
    assert calls == [False, True]


def test_update_leaves_dirty_checkout_untouched(
    repos: tuple[Path, Path], syncs: list[str]
) -> None:
    """Uncommitted tracked changes mean someone is working here: do nothing."""
    ssot, peer = repos
    before = _git(ssot, "rev-parse", "HEAD")
    _ = _push_new_commit(peer, "change")
    _ = (ssot / "base").write_text("local edit")

    assert update_main() == EXIT_OK
    assert _git(ssot, "rev-parse", "HEAD") == before
    assert (ssot / "base").read_text() == "local edit"
    assert syncs == []


def test_update_ignores_checkouts_on_other_branches(
    repos: tuple[Path, Path], syncs: list[str]
) -> None:
    """Only ``main`` follows origin; a feature branch is left alone."""
    ssot, peer = repos
    _ = _git(ssot, "checkout", "-qb", "feature")
    before = _git(ssot, "rev-parse", "HEAD")
    _ = _push_new_commit(peer, "change")

    assert update_main() == EXIT_OK
    assert _git(ssot, "rev-parse", "HEAD") == before
    assert syncs == []


def test_update_never_merges_diverged_history(
    repos: tuple[Path, Path], syncs: list[str]
) -> None:
    """Local unpushed commits are never merged; the local commit is reconciled."""
    ssot, peer = repos
    local = _commit(ssot, "local")
    _ = _push_new_commit(peer, "remote")

    assert update_main() == EXIT_OK
    assert _git(ssot, "rev-parse", "HEAD") == local
    assert syncs == ["sync"]


def test_update_reconciles_local_head_when_fetch_fails(
    repos: tuple[Path, Path], syncs: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    """Offline: warn, keep the checkout, still reconcile an unsynced commit."""
    ssot, _ = repos
    _ = _git(ssot, "remote", "set-url", "origin", str(ssot.parent / "missing.git"))

    assert update_main() == EXIT_OK
    assert syncs == ["sync"]
    assert "fetch" in capsys.readouterr().err


def test_update_skips_when_sync_lock_is_held(
    repos: tuple[Path, Path], syncs: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A running sync means skip this round, never wait for it."""
    ssot, peer = repos
    before = _git(ssot, "rev-parse", "HEAD")
    _ = _push_new_commit(peer, "change")
    monkeypatch.setattr("sync.core.index.try_acquire_sync_lock", _no_lock)

    assert update_main() == EXIT_OK
    assert _git(ssot, "rev-parse", "HEAD") == before
    assert syncs == []


@pytest.fixture
def service_calls(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Record service-manager commands instead of running them."""
    calls: list[list[str]] = []

    async def _run(
        argv: Sequence[str], *_args: object, **_kwargs: object
    ) -> ProcessResult:
        calls.append(list(argv))
        return ProcessResult(exit_code=0, stdout="", stderr="", timed_out=False)

    async def _exists(*_args: object, **_kwargs: object) -> bool:
        return True

    monkeypatch.setattr("sync.core.update.run_process", _run)
    monkeypatch.setattr("sync.core.update.command_exists", _exists)
    return calls


@pytest.mark.usefixtures("repos")
def test_schedule_installs_idle_priority_systemd_timer_once(
    home: Path, service_calls: list[list[str]]
) -> None:
    """Linux gets a low-priority oneshot and a timer, enabled only on change."""
    env = SyncEnv.from_home(str(home), platform="linux")

    asyncio.run(reconcile_update_schedule(env))
    units = home / ".config" / "systemd" / "user"
    service = (units / f"{UPDATE_UNIT}.service").read_text()
    timer = (units / f"{UPDATE_UNIT}.timer").read_text()
    assert "sync-current/.venv/bin/python -m sync.cli update" in service
    assert "Nice=19" in service
    assert "IOSchedulingClass=idle" in service
    assert "OnUnitActiveSec=300s" in timer
    assert ["systemctl", "--user", "enable", "--now", f"{UPDATE_UNIT}.timer"] in (
        service_calls
    )

    service_calls.clear()
    asyncio.run(reconcile_update_schedule(env))
    assert service_calls == []


@pytest.mark.usefixtures("repos")
def test_schedule_installs_background_launchd_agent(
    home: Path, service_calls: list[list[str]]
) -> None:
    """The macOS agent is a background, low-IO launch agent with an explicit PATH."""
    env = SyncEnv.from_home(str(home), platform="darwin")

    asyncio.run(reconcile_update_schedule(env))
    plist = (home / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist").read_text()
    assert "<string>update</string>" in plist
    assert "<key>ProcessType</key><string>Background</string>" in plist
    assert "<key>LowPriorityIO</key><true/>" in plist
    assert "/.nix-profile/bin" in plist
    assert any(call[:2] == ["launchctl", "bootstrap"] for call in service_calls)


def test_schedule_skipped_without_git_checkout(
    home: Path, service_calls: list[list[str]]
) -> None:
    """Without a git checkout there is nothing to pull, so nothing is scheduled."""
    (home / ".config" / "agents").mkdir(parents=True)
    env = SyncEnv.from_home(str(home), platform="linux")

    asyncio.run(reconcile_update_schedule(env))
    assert not (home / ".config" / "systemd").exists()
    assert service_calls == []
