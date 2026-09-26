# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for sync-owned user services: declaration, reconcile, and pruning.

A declared unit is authoritative: sync writes it (adopting a hand-made file of
the same name), enables it, and restarts it only when its content changes.
Units sync owned but no longer declares are stopped and removed; unrelated
units are never touched.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from typing import TYPE_CHECKING

import pytest

from sync.core.harness import SyncEnv
from sync.core.services import (
    AMP_RUNNER_LABEL,
    AUTH_GATEWAY_ENV,
    LAUNCHD_LABEL,
    UserUnit,
    declared_launch_agents,
    declared_user_units,
    reconcile_services,
    reconcile_user_units,
)
from sync.runtime.process import ProcessResult

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

LONG_RUNNING = UserUnit(
    name="demo.service",
    content="[Service]\nExecStart=/bin/true\n\n[Install]\nWantedBy=default.target\n",
)
ONESHOT = UserUnit(name="job.service", content="[Service]\nType=oneshot\n")
TIMER = UserUnit(
    name="job.timer",
    content="[Timer]\nOnBootSec=1min\n\n[Install]\nWantedBy=timers.target\n",
)


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Record service-manager commands instead of running them."""
    recorded: list[list[str]] = []

    async def _run(
        argv: Sequence[str], *_args: object, **_kwargs: object
    ) -> ProcessResult:
        recorded.append(list(argv))
        return ProcessResult(exit_code=0, stdout="", stderr="", timed_out=False)

    async def _exists(*_args: object, **_kwargs: object) -> bool:
        return True

    monkeypatch.setattr("sync.core.services.run_process", _run)
    monkeypatch.setattr("sync.core.services.command_exists", _exists)
    return recorded


def _linux(home: Path) -> SyncEnv:
    return SyncEnv.from_home(str(home), platform="linux")


def _unit_dir(home: Path) -> Path:
    return home / ".config" / "systemd" / "user"


def _reconcile(home: Path, units: Sequence[UserUnit]) -> None:
    asyncio.run(reconcile_user_units(_linux(home), units))


def test_reconcile_enables_and_restarts_long_running_units_once(
    home: Path, calls: list[list[str]]
) -> None:
    """New units are written and started; an unchanged rerun runs nothing."""
    _reconcile(home, [LONG_RUNNING, TIMER])

    assert (_unit_dir(home) / "demo.service").read_text() == LONG_RUNNING.content
    assert ["systemctl", "--user", "daemon-reload"] in calls
    assert ["systemctl", "--user", "enable", "demo.service"] in calls
    assert ["systemctl", "--user", "restart", "demo.service"] in calls
    assert ["systemctl", "--user", "enable", "--now", "job.timer"] in calls

    calls.clear()
    _reconcile(home, [LONG_RUNNING, TIMER])
    assert calls == []


def test_reconcile_leaves_units_without_install_section_to_their_trigger(
    home: Path, calls: list[list[str]]
) -> None:
    """A oneshot started by a timer is written but never enabled or restarted."""
    _reconcile(home, [ONESHOT])

    assert (_unit_dir(home) / "job.service").is_file()
    assert not any("job.service" in call for call in calls)


def test_reconcile_prunes_units_it_owned_but_no_longer_declares(
    home: Path, calls: list[list[str]]
) -> None:
    """Dropping a declaration stops, disables, and removes the owned unit."""
    _reconcile(home, [LONG_RUNNING, TIMER])
    calls.clear()

    _reconcile(home, [TIMER])

    assert not (_unit_dir(home) / "demo.service").exists()
    assert ["systemctl", "--user", "disable", "--now", "demo.service"] in calls


def test_reconcile_adopts_hand_made_unit_and_ignores_unrelated_ones(
    home: Path, calls: list[list[str]]
) -> None:
    """A same-named hand-made unit is replaced; other hand-made units survive."""
    unit_dir = _unit_dir(home)
    unit_dir.mkdir(parents=True)
    _ = (unit_dir / "demo.service").write_text("[Service]\nExecStart=/old\n")
    _ = (unit_dir / "mine.service").write_text("[Service]\nExecStart=/mine\n")

    _reconcile(home, [LONG_RUNNING])
    _reconcile(home, [])

    assert (unit_dir / "mine.service").read_text() == "[Service]\nExecStart=/mine\n"
    assert not any("mine.service" in call for call in calls)


def test_reconcile_restarts_a_unit_whose_content_changed(
    home: Path, calls: list[list[str]]
) -> None:
    """Changing a declared unit restarts it; unchanged ones stay untouched."""
    _reconcile(home, [LONG_RUNNING, TIMER])
    calls.clear()
    changed = UserUnit(name="demo.service", content=LONG_RUNNING.content + "#\n")

    _reconcile(home, [changed, TIMER])

    assert ["systemctl", "--user", "restart", "demo.service"] in calls
    assert not any("job.timer" in call for call in calls)


def _git_checkout(home: Path) -> None:
    ssot = home / ".config" / "agents"
    ssot.mkdir(parents=True, exist_ok=True)
    _ = subprocess.run(  # noqa: S603 - fixed git invocation in tests
        ["git", "init", "-q", str(ssot)],  # noqa: S607 - git from PATH
        check=True,
    )


def _names(units: Sequence[UserUnit]) -> set[str]:
    return {unit.name for unit in units}


def test_updater_units_need_a_git_checkout(home: Path) -> None:
    """Without a git checkout there is nothing to pull, so no updater."""
    (home / ".config" / "agents").mkdir(parents=True)
    assert _names(declared_user_units(_linux(home), gateway_host=False)) == set()

    _git_checkout(home)
    units = {u.name: u for u in declared_user_units(_linux(home), gateway_host=False)}
    assert set(units) == {"agents-update.service", "agents-update.timer"}
    service = units["agents-update.service"].content
    assert "sync-current/.venv/bin/python -m sync.cli update" in service
    assert "Nice=19" in service
    assert "IOSchedulingClass=idle" in service
    assert f"PATH={home}/.local/bin:" in service
    assert "[Install]" not in service


def test_gateway_units_only_on_gateway_host(home: Path) -> None:
    """The gateway runs on its host; the Funnel auth gateway needs its env file."""
    (home / ".config" / "agents").mkdir(parents=True)
    assert _names(declared_user_units(_linux(home), gateway_host=False)) == set()

    names = _names(declared_user_units(_linux(home), gateway_host=True))
    assert names == {"cliproxyapi.service"}

    env_file = home / ".cli-proxy-api" / AUTH_GATEWAY_ENV
    env_file.parent.mkdir(parents=True)
    _ = env_file.write_text("GATEWAY_SECRET=x\n")
    units = {u.name: u for u in declared_user_units(_linux(home), gateway_host=True)}
    assert set(units) == {"cliproxyapi.service", "cliproxy-auth-gateway.service"}
    gateway = units["cliproxy-auth-gateway.service"].content
    assert f"EnvironmentFile={env_file}" in gateway
    assert "auth-gateway.py" in gateway
    assert f"ExecStart={home}/.local/bin/cli-proxy-api" in (
        units["cliproxyapi.service"].content
    )


def test_auth_gateway_unit_changes_when_its_env_changes(home: Path) -> None:
    """A rotated token must restart the gateway, so the unit tracks its env."""
    (home / ".config" / "agents").mkdir(parents=True)
    env_file = home / ".cli-proxy-api" / AUTH_GATEWAY_ENV
    env_file.parent.mkdir(parents=True)

    def auth_unit() -> str:
        units = declared_user_units(_linux(home), gateway_host=True)
        return next(u.content for u in units if u.name.startswith("cliproxy-auth"))

    _ = env_file.write_text("GATEWAY_SECRET=old\n")
    before = auth_unit()
    _ = env_file.write_text("GATEWAY_SECRET=new\n")

    assert auth_unit() != before
    assert "GATEWAY_SECRET" not in auth_unit()


def test_auth_gateway_unit_changes_when_its_script_changes(home: Path) -> None:
    """New gateway code must restart the gateway, so the unit tracks its script."""
    env_file = home / ".cli-proxy-api" / AUTH_GATEWAY_ENV
    env_file.parent.mkdir(parents=True)
    _ = env_file.write_text("GATEWAY_SECRET=x\n")
    script = home / ".config" / "agents" / "tools" / "cliproxyapi" / "auth-gateway.py"
    script.parent.mkdir(parents=True)

    def auth_unit() -> str:
        units = declared_user_units(_linux(home), gateway_host=True)
        return next(u.content for u in units if u.name.startswith("cliproxy-auth"))

    _ = script.write_text("old = 1\n")
    before = auth_unit()
    _ = script.write_text("new = 2\n")

    assert auth_unit() != before


def test_services_skip_systemd_on_darwin(home: Path, calls: list[list[str]]) -> None:
    """On macOS the updater is a launch agent; no systemd units are written."""
    _git_checkout(home)
    asyncio.run(
        reconcile_services(
            SyncEnv.from_home(str(home), platform="darwin"), gateway_host=True
        )
    )

    assert not _unit_dir(home).exists()
    plist = (home / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist").read_text()
    assert "<string>update</string>" in plist
    assert "<key>ProcessType</key><string>Background</string>" in plist
    assert "<key>LowPriorityIO</key><true/>" in plist
    assert "/.nix-profile/bin" in plist
    assert any(call[:2] == ["launchctl", "bootstrap"] for call in calls)


def _declare_runner_hosts(home: Path, hosts: Sequence[str]) -> None:
    deployment = home / ".config" / "agents" / "tools" / "amp-runner"
    deployment.mkdir(parents=True, exist_ok=True)
    _ = (deployment / "deployment.json").write_text(json.dumps({"hosts": list(hosts)}))


def test_amp_runner_unit_only_on_declared_hosts(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The runner serves repos and the SSOT from a neutral working directory."""
    monkeypatch.setattr("socket.gethostname", lambda: "munich")
    _declare_runner_hosts(home, ["oulu"])
    assert _names(declared_user_units(_linux(home), gateway_host=False)) == set()

    _declare_runner_hosts(home, ["oulu", "munich"])
    units = {u.name: u for u in declared_user_units(_linux(home), gateway_host=False)}
    runner = units["amp-runner-agents.service"].content
    assert "WorkingDirectory=%h" in runner
    assert f"ExecStart={home}/.local/bin/amp --no-tui --runner-id munich " in runner
    assert f"--discover-dirs={home}/repos" in runner
    assert f"--dir {home}/.config/agents" in runner
    assert "[Install]" in runner


def test_darwin_declares_updater_and_runner_launch_agents(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MacOS gets the same services as launch agents, keyed by label."""
    monkeypatch.setattr("socket.gethostname", lambda: "beirut.local")
    _git_checkout(home)
    _declare_runner_hosts(home, ["beirut"])
    darwin = SyncEnv.from_home(str(home), platform="darwin")

    agents = {a.name: a.content for a in declared_launch_agents(darwin)}

    assert set(agents) == {LAUNCHD_LABEL, AMP_RUNNER_LABEL}
    runner = agents[AMP_RUNNER_LABEL]
    assert "<string>--runner-id</string><string>beirut</string>" in runner
    assert "<key>KeepAlive</key><true/>" in runner
    assert f"<key>WorkingDirectory</key><string>{home}</string>" in runner


def test_darwin_reconcile_reloads_changed_agents_and_prunes_owned_ones(
    home: Path, calls: list[list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Changed agents are reloaded once; dropped owned agents are unloaded."""
    monkeypatch.setattr("socket.gethostname", lambda: "beirut")
    _git_checkout(home)
    _declare_runner_hosts(home, ["beirut"])
    darwin = SyncEnv.from_home(str(home), platform="darwin")
    agents_dir = home / "Library" / "LaunchAgents"
    agents_dir.mkdir(parents=True)
    _ = (agents_dir / "hand.made.plist").write_text("<plist/>")

    asyncio.run(reconcile_services(darwin, gateway_host=False))
    bootstrapped = [c[3] for c in calls if c[:2] == ["launchctl", "bootstrap"]]
    assert sorted(
        p.rsplit("/", 1)[1].removesuffix(".plist") for p in bootstrapped
    ) == sorted([LAUNCHD_LABEL, AMP_RUNNER_LABEL])

    calls.clear()
    asyncio.run(reconcile_services(darwin, gateway_host=False))
    assert calls == []

    _declare_runner_hosts(home, [])
    asyncio.run(reconcile_services(darwin, gateway_host=False))
    assert not (agents_dir / f"{AMP_RUNNER_LABEL}.plist").exists()
    assert any(
        c[:2] == ["launchctl", "bootout"] and AMP_RUNNER_LABEL in c[2] for c in calls
    )
    assert (agents_dir / "hand.made.plist").exists()
