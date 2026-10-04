# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
# ruff: noqa: S101, INP001 - pytest asserts; tests load update.py by path, not as a package
"""Decision logic for the nightly Paseo daemon update."""

from __future__ import annotations

import json

import pytest
import update


def test_daemon_version_requires_a_running_daemon() -> None:
    """Only a running daemon reports the version the service executes."""
    status = {"localDaemon": "running", "daemonVersion": "0.10.3"}
    stopped = status | {"localDaemon": "stopped"}
    assert update.daemon_version(json.dumps(status)) == "0.10.3"
    assert update.daemon_version(json.dumps(stopped)) is None
    assert update.daemon_version(json.dumps({"localDaemon": "running"})) is None
    assert update.daemon_version("not json") is None


def test_cli_version_ignores_wrapper_warnings() -> None:
    """Wrapper warnings before the version line do not hide it."""
    noisy = "sync: warning: another sync is already running\n0.10.4\n"
    assert update.cli_version(noisy) == "0.10.4"
    assert update.cli_version("v0.11.0\n") == "0.11.0"
    assert update.cli_version("") is None
    assert update.cli_version("sync: warning: failed\n") is None


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
    assert update.busy_agents(listing) == expected


def test_unreadable_agent_listing_counts_as_busy() -> None:
    """A listing the updater cannot interpret never permits a restart."""
    assert update.busy_agents("not json") is True
    assert update.busy_agents('{"agents": []}') is True
    assert update.busy_agents('["idle"]') is True


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
    assert update.decide(running, latest, busy=busy) == action
