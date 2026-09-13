# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the launch entrypoint: target resolution and best-effort pre-launch sync.

The launcher must reach a cached install even when the SSOT is missing, and a
failed, timed-out, or lock-contended pre-launch sync must never block the launch.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import pytest

from sync.core.index import EXIT_ERROR, EXIT_OK, EXIT_UNSUPPORTED, launch_main

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from sync.core.harness import Harness, SyncEnv
    from sync.core.launcher import NpmPackageSpec

TOOL_EXIT_STATUS: Final[int] = 7


def _make_ssot(home: Path, harness_ids: Sequence[str] = ()) -> None:
    """Create an SSOT tree with the given harness source directories."""
    harnesses = home / ".config" / "agents" / "harnesses"
    harnesses.mkdir(parents=True, exist_ok=True)
    for harness_id in harness_ids:
        (harnesses / harness_id).mkdir(parents=True, exist_ok=True)


async def _fail_if_sync_runs(*_args: object, **_kwargs: object) -> bool:
    """Raise when the pre-launch sync runs, proving it was skipped."""
    message = "pre-launch sync must not run"
    raise AssertionError(message)


async def _noop_launch(*_args: object, **_kwargs: object) -> int:
    """Return a successful launch status without executing anything."""
    return EXIT_OK


async def _raise_launch_error(*_args: object, **_kwargs: object) -> int:
    """Raise a launch failure to exercise the launch error handler."""
    message = "package download failed"
    raise RuntimeError(message)


def _no_lock(_env: SyncEnv) -> None:
    """Report lock contention: the caller treats None as 'lock unavailable'."""


@pytest.mark.usefixtures("home")
def test_launch_main_reports_unsupported_target(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An unknown launch target fails with the unsupported exit code."""
    exit_code = launch_main("definitely-not-a-target", [])

    assert exit_code == EXIT_UNSUPPORTED
    assert "unsupported launch target" in capsys.readouterr().err


@pytest.mark.usefixtures("home")
def test_launch_main_uses_adapter_when_ssot_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Without the SSOT, a known harness launches from its adapter and warns."""
    launched: list[tuple[str, tuple[str, ...]]] = []

    async def _record(
        _env: SyncEnv,
        harness: Harness,
        args: Sequence[str],
    ) -> int:
        launched.append((harness.source_name, tuple(args)))
        return EXIT_OK

    monkeypatch.setattr("sync.core.index.launch_harness", _record)
    monkeypatch.setattr("sync.core.index.run_sync", _fail_if_sync_runs)

    exit_code = launch_main("codex", ["--version"])

    assert exit_code == EXIT_OK
    assert launched == [("codex", ("--version",))]
    assert "continuing with installed runtime" in capsys.readouterr().err


@pytest.mark.usefixtures("home")
def test_launch_main_resolves_registered_tool_without_ssot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A registered tool resolves by name and forwards its exit status."""
    specs: list[tuple[str, str]] = []

    async def _record(
        _env: SyncEnv,
        spec: NpmPackageSpec,
        _args: Sequence[str],
    ) -> int:
        specs.append((spec.tool, spec.package))
        return TOOL_EXIT_STATUS

    monkeypatch.setattr("sync.core.index.launch_npm_package", _record)

    assert launch_main("mcporter", []) == TOOL_EXIT_STATUS
    assert specs == [("mcporter", "mcporter")]


@pytest.mark.usefixtures("home")
def test_launch_main_reports_launch_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A launch failure is reported as an error exit instead of propagating."""
    monkeypatch.setattr("sync.core.index.launch_harness", _raise_launch_error)

    exit_code = launch_main("codex", [])

    assert exit_code == EXIT_ERROR
    assert "launch failed: package download failed" in capsys.readouterr().err


def test_launch_main_syncs_before_launch_when_ssot_is_available(
    home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A discovered harness syncs first, then launches, in that order."""
    _make_ssot(home, ["codex"])
    executed: list[str] = []

    async def _sync(_env: SyncEnv, **_kwargs: object) -> bool:
        executed.append("sync")
        return True

    async def _record(_env: SyncEnv, harness: Harness, _args: Sequence[str]) -> int:
        executed.append(f"launch:{harness.source_name}")
        return EXIT_OK

    monkeypatch.setattr("sync.core.index.run_sync", _sync)
    monkeypatch.setattr("sync.core.index.launch_harness", _record)

    assert launch_main("codex", []) == EXIT_OK
    assert executed == ["sync", "launch:codex"]


def test_launch_main_continues_when_lock_is_held(
    home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A held sync lock skips the pre-launch sync and still launches."""
    _make_ssot(home, ["codex"])
    monkeypatch.setattr("sync.core.index.try_acquire_sync_lock", _no_lock)
    monkeypatch.setattr("sync.core.index.run_sync", _fail_if_sync_runs)
    monkeypatch.setattr("sync.core.index.launch_harness", _noop_launch)

    assert launch_main("codex", []) == EXIT_OK
    assert "already running; continuing launch" in capsys.readouterr().err


def test_launch_main_warns_when_lock_acquisition_fails(
    home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An unusable lock reports unavailability and still launches."""
    _make_ssot(home, ["codex"])

    def _boom(_env: SyncEnv) -> object:
        message = "state directory is not writable"
        raise RuntimeError(message)

    monkeypatch.setattr("sync.core.index.try_acquire_sync_lock", _boom)
    monkeypatch.setattr("sync.core.index.run_sync", _fail_if_sync_runs)
    monkeypatch.setattr("sync.core.index.launch_harness", _noop_launch)

    assert launch_main("codex", []) == EXIT_OK
    assert "sync before launch unavailable" in capsys.readouterr().err


def test_launch_main_warns_when_pre_launch_sync_times_out(
    home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A pre-launch sync timeout warns and continues to the cached launch."""
    _make_ssot(home, ["codex"])

    async def _timed_out(_env: SyncEnv, **_kwargs: object) -> bool:
        raise TimeoutError

    monkeypatch.setattr("sync.core.index.run_sync", _timed_out)
    monkeypatch.setattr("sync.core.index.launch_harness", _noop_launch)

    assert launch_main("codex", []) == EXIT_OK
    assert "timed out; continuing launch" in capsys.readouterr().err


def test_launch_main_warns_when_pre_launch_sync_fails(
    home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A failed pre-launch sync warns and continues to the cached launch."""
    _make_ssot(home, ["codex"])

    async def _failed(_env: SyncEnv, **_kwargs: object) -> bool:
        return False

    monkeypatch.setattr("sync.core.index.run_sync", _failed)
    monkeypatch.setattr("sync.core.index.launch_harness", _noop_launch)

    assert launch_main("codex", []) == EXIT_OK
    assert "continuing launch without completed sync" in capsys.readouterr().err
