# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the Amp runner update job and service identifier semantics."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from sync.maintenance.amp_runner import (
    busy_threads,
    package_root,
    restart,
    running_pid,
    service_target,
    update_amp_runner,
    version_name,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_service_target_formats_user_gui(monkeypatch: pytest.MonkeyPatch) -> None:
    """Target contains current uid and service label on macOS."""
    monkeypatch.setattr(os, "getuid", lambda: 501)
    assert service_target("org.nix-community.home.amp-runner") == (
        "gui/501/org.nix-community.home.amp-runner"
    )


def test_running_pid_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    """Parse pid from launchctl print output on macOS."""
    output_lines = "state = running\npid = 45123\npath = /tmp/amp"

    def fake_output(*args: str) -> str:
        return output_lines if args and args[0] == "launchctl" else ""

    monkeypatch.setattr("sync.maintenance.amp_runner.output", fake_output)
    assert running_pid("org.nix-community.home.amp-runner", platform="darwin") == (
        "45123"
    )


def test_running_pid_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    """Parse pid from systemctl show MainPID output on Linux."""

    def fake_output(*args: str) -> str:
        return "8899" if args and args[0] == "systemctl" else ""

    monkeypatch.setattr("sync.maintenance.amp_runner.output", fake_output)
    assert running_pid("amp-runner.service", platform="linux") == "8899"


def test_running_pid_zero_or_invalid_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Zero or non-digit pid indicates an inactive service."""

    def fake_output(*_args: str) -> str:
        return "0"

    monkeypatch.setattr("sync.maintenance.amp_runner.output", fake_output)
    assert running_pid("amp-runner.service", platform="linux") is None


def test_restart_calls_correct_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    """Launchctl is invoked on Darwin, systemctl on Linux."""
    recorded: list[list[str]] = []

    def fake_call(argv: list[str]) -> int:
        recorded.append(argv)
        return 0

    monkeypatch.setattr(os, "getuid", lambda: 501)
    monkeypatch.setattr("subprocess.call", fake_call)

    assert restart("org.nix-community.home.amp-runner", platform="darwin") == 0
    assert recorded == [
        [
            "launchctl",
            "kickstart",
            "-k",
            "gui/501/org.nix-community.home.amp-runner",
        ]
    ]

    recorded.clear()
    assert restart("amp-runner.service", platform="linux") == 0
    assert recorded == [["systemctl", "--user", "restart", "amp-runner.service"]]


def test_package_root_and_version_name(tmp_path: Path) -> None:
    """Traverse directories to locate versions root and extract version."""
    pkg = (
        tmp_path
        / "packages"
        / "abc1234"
        / "versions"
        / "1.2.3"
        / "node_modules"
        / "@ampcode"
        / "cli"
        / "bin"
        / "amp"
    )
    pkg.parent.mkdir(parents=True)
    pkg.touch()

    assert package_root(pkg) == tmp_path / "packages" / "abc1234"
    assert version_name(pkg) == "1.2.3"


def test_busy_threads_identifies_recent_and_mid_turn(tmp_path: Path) -> None:
    """Detect active threads within idle and stuck thresholds."""
    log_file = tmp_path / "runner.log"
    now = datetime.now(UTC)
    recent = (now - timedelta(minutes=5)).isoformat()
    old = (now - timedelta(minutes=30)).isoformat()
    stuck = (now - timedelta(minutes=60)).isoformat()

    lines = [
        json.dumps(
            {
                "threadId": "t-recent",
                "@timestamp": recent,
                "message": "other",
            }
        ),
        json.dumps(
            {
                "threadId": "t-old-idle",
                "@timestamp": old,
                "message": "[observer] onAgentState",
                "subtype": "idle",
            }
        ),
        json.dumps(
            {
                "threadId": "t-mid-turn",
                "@timestamp": stuck,
                "message": "[observer] onAgentState",
                "subtype": "thinking",
            }
        ),
    ]
    _ = log_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    active = busy_threads(now, log_file)
    assert set(active) == {"t-recent", "t-mid-turn"}


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_update_amp_runner_exits_0_when_not_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, platform: str
) -> None:
    """If runner is not active, updater reports and exits 0."""

    def fake_running(_svc: str, platform: str = "") -> Path | None:
        del platform
        return None

    monkeypatch.setattr("sync.maintenance.amp_runner.running_exe", fake_running)
    log_file = tmp_path / "log.txt"
    assert update_amp_runner("amp-runner.service", log_file, platform=platform) == 0


def test_update_amp_runner_exits_0_when_already_current(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If current executable matches newest cached, updater exits 0."""
    exe = tmp_path / "bin" / "amp"
    exe.parent.mkdir(parents=True)
    exe.touch()

    def fake_running(_svc: str, platform: str = "") -> Path | None:
        del platform
        return exe

    def fake_cached(_running: Path, wrapper: Path | None = None) -> Path | None:
        del wrapper
        return exe

    monkeypatch.setattr("sync.maintenance.amp_runner.running_exe", fake_running)
    monkeypatch.setattr("sync.maintenance.amp_runner.cached_exe", fake_cached)

    assert update_amp_runner("amp-runner.service", tmp_path / "log.txt") == 0


def test_update_amp_runner_postpones_when_busy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Postpone update if any thread is active."""
    old_exe = tmp_path / "v1" / "amp"
    new_exe = tmp_path / "v2" / "amp"
    old_exe.parent.mkdir(parents=True)
    new_exe.parent.mkdir(parents=True)
    old_exe.touch()
    new_exe.touch()

    def fake_running(_svc: str, platform: str = "") -> Path | None:
        del platform
        return old_exe

    def fake_cached(_running: Path, wrapper: Path | None = None) -> Path | None:
        del wrapper
        return new_exe

    def fake_busy(_now: datetime, _path: Path) -> list[str]:
        return ["t-1"]

    monkeypatch.setattr("sync.maintenance.amp_runner.running_exe", fake_running)
    monkeypatch.setattr("sync.maintenance.amp_runner.cached_exe", fake_cached)
    monkeypatch.setattr("sync.maintenance.amp_runner.busy_threads", fake_busy)

    assert update_amp_runner("amp-runner.service", tmp_path / "log.txt") == 0
