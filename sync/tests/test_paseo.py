# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the Paseo daemon update job and identifier handling."""

from __future__ import annotations

import json
import os
import subprocess
from typing import TYPE_CHECKING

import pytest

from sync.maintenance.paseo import (
    busy_agents,
    cli_version,
    daemon_version,
    decide,
    update_paseo,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_daemon_version_requires_a_running_daemon() -> None:
    """Only a running daemon reports the version the service executes."""
    status = {"localDaemon": "running", "daemonVersion": "0.10.3"}
    stopped = status | {"localDaemon": "stopped"}
    assert daemon_version(json.dumps(status)) == "0.10.3"
    assert daemon_version(json.dumps(stopped)) is None
    assert daemon_version(json.dumps({"localDaemon": "running"})) is None
    assert daemon_version("not json") is None


def test_cli_version_ignores_wrapper_warnings() -> None:
    """Wrapper warnings before the version line do not hide it."""
    noisy = "sync: warning: another sync is already running\n0.10.4\n"
    assert cli_version(noisy) == "0.10.4"
    assert cli_version("v0.11.0\n") == "0.11.0"
    assert cli_version("") is None
    assert cli_version("sync: warning: failed\n") is None


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ([], False),
        (["idle", "closed", "error"], False),
        (["idle", "running"], True),
        (["initializing"], True),
    ],
)
def test_busy_counts_agents_mid_turn(*, statuses: list[str], expected: bool) -> None:
    """Initializing and running agents postpone the restart."""
    listing = json.dumps([{"id": str(i), "status": s} for i, s in enumerate(statuses)])
    assert busy_agents(listing) == expected


def test_unreadable_agent_listing_counts_as_busy() -> None:
    """A listing the updater cannot interpret never permits a restart."""
    assert busy_agents("not json") is True
    assert busy_agents('{"agents": []}') is True
    assert busy_agents('["idle"]') is True


@pytest.mark.parametrize(
    ("running", "latest", "busy", "action"),
    [
        (None, "0.10.4", False, "absent"),
        ("0.10.3", None, False, "unknown"),
        ("0.10.3", "0.10.3", True, "current"),
        ("0.10.3", "0.10.4", True, "postpone"),
        ("0.10.3", "0.10.4", False, "restart"),
    ],
)
def test_decide(
    *, running: str | None, latest: str | None, busy: bool, action: str
) -> None:
    """Restart only a running daemon that is behind and idle."""
    assert decide(running, latest, busy=busy) == action


def test_update_paseo_service_restart_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    """Restart systemd user unit on Linux when behind and idle."""
    recorded: list[list[str]] = []

    def fake_paseo(_wrap: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
        if "daemon" in args:
            return subprocess.CompletedProcess(
                args,
                0,
                stdout=json.dumps({"localDaemon": "running", "daemonVersion": "1.0.0"}),
            )
        if "--version" in args:
            return subprocess.CompletedProcess(args, 0, stdout="1.1.0\n")
        if "agent" in args:
            return subprocess.CompletedProcess(args, 0, stdout="[]")
        return subprocess.CompletedProcess(args, 0, stdout="")

    def fake_call(argv: list[str]) -> int:
        recorded.append(argv)
        return 0

    monkeypatch.setattr("sync.maintenance.paseo.run_paseo", fake_paseo)
    monkeypatch.setattr("subprocess.call", fake_call)

    rc = update_paseo("paseo.service", platform="linux")
    assert rc == 0
    assert recorded == [["systemctl", "--user", "restart", "paseo.service"]]


def test_update_paseo_service_restart_darwin(monkeypatch: pytest.MonkeyPatch) -> None:
    """Restart launchd agent on macOS when behind and idle."""
    recorded: list[list[str]] = []

    def fake_paseo(_wrap: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
        if "daemon" in args:
            return subprocess.CompletedProcess(
                args,
                0,
                stdout=json.dumps({"localDaemon": "running", "daemonVersion": "1.0.0"}),
            )
        if "--version" in args:
            return subprocess.CompletedProcess(args, 0, stdout="1.1.0\n")
        if "agent" in args:
            return subprocess.CompletedProcess(args, 0, stdout="[]")
        return subprocess.CompletedProcess(args, 0, stdout="")

    def fake_call(argv: list[str]) -> int:
        recorded.append(argv)
        return 0

    monkeypatch.setattr(os, "getuid", lambda: 501)
    monkeypatch.setattr("sync.maintenance.paseo.run_paseo", fake_paseo)
    monkeypatch.setattr("subprocess.call", fake_call)

    rc = update_paseo("org.nix-community.home.paseo", platform="darwin")
    assert rc == 0
    assert recorded == [
        [
            "launchctl",
            "kickstart",
            "-k",
            "gui/501/org.nix-community.home.paseo",
        ]
    ]
