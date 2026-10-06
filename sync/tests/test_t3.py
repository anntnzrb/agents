# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for T3 Code service operations, model sync, and auto-update."""

from __future__ import annotations

import argparse
import json
import sqlite3
from typing import TYPE_CHECKING

from sync.core.harness import SyncEnv
from sync.maintenance.t3 import (
    JsonObject,
    busy_threads,
    cmd_auto_update,
    cmd_pair,
    cmd_refresh_models,
    service_restart,
    service_start,
    sync_binary_paths,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    import pytest

EXPECTED_LIVE_RUNS = 2


def test_pinned_auto_update_is_a_noop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If channel is pinned to a numeric version, auto-update is disabled."""
    home = tmp_path / "home"
    ssot = home / "src" / "agents"
    (ssot / "tools" / "t3").mkdir(parents=True)
    _ = (ssot / "tools" / "t3" / "deployment.json").write_text(
        json.dumps({"channel": "0.1.2"}), encoding="utf-8"
    )
    env = SyncEnv.from_home(str(home), platform="linux")
    out_msgs: list[str] = []
    monkeypatch.setattr("sync.maintenance.t3.out", out_msgs.append)

    rc = cmd_auto_update(argparse.Namespace(), env)
    assert rc == 0
    assert any("automatic updates disabled" in m for m in out_msgs)


def test_auto_update_installs_when_t3_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Auto-update triggers install when active version is None."""
    home = tmp_path / "home"
    ssot = home / "src" / "agents"
    (ssot / "tools" / "t3").mkdir(parents=True)
    _ = (ssot / "tools" / "t3" / "deployment.json").write_text(
        json.dumps({"channel": "nightly"}), encoding="utf-8"
    )
    env = SyncEnv.from_home(str(home), platform="linux")

    installed: list[bool] = []

    def fake_install(_args: argparse.Namespace, _env: SyncEnv) -> int:
        installed.append(True)
        return 0

    monkeypatch.setattr("sync.maintenance.t3.cmd_install", fake_install)

    rc = cmd_auto_update(argparse.Namespace(), env)
    assert rc == 0
    assert installed == [True]


def test_refresh_models_waits_for_a_fresh_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Before T3 writes settings, the scheduled refresh has nothing to do."""
    env = SyncEnv.from_home(str(tmp_path / "home"), platform="linux")
    out_msgs: list[str] = []
    monkeypatch.setattr("sync.maintenance.t3.out", out_msgs.append)

    assert cmd_refresh_models(argparse.Namespace(), env) == 0
    assert any("not installed" in m for m in out_msgs)


def test_refresh_models_rejects_corrupt_settings(tmp_path: Path) -> None:
    """Settings that exist but are not a JSON object are a real failure."""
    home = tmp_path / "home"
    settings = home / ".t3" / "userdata" / "settings.json"
    settings.parent.mkdir(parents=True)
    _ = settings.write_text("[]", encoding="utf-8")
    env = SyncEnv.from_home(str(home), platform="linux")

    assert cmd_refresh_models(argparse.Namespace(), env) == 1


def test_counts_live_v2_runs(tmp_path: Path) -> None:
    """Verify busy_threads queries live orchestration_v2_projection_runs."""
    home = tmp_path / "home"
    db_dir = home / ".t3" / "userdata"
    db_dir.mkdir(parents=True)
    db_path = db_dir / "statev2.sqlite"

    conn = sqlite3.connect(db_path)
    _ = conn.execute(
        "CREATE TABLE orchestration_v2_projection_runs (thread_id TEXT, status TEXT)"
    )
    _ = conn.execute(
        "INSERT INTO orchestration_v2_projection_runs VALUES ('t1', 'running')"
    )
    _ = conn.execute(
        "INSERT INTO orchestration_v2_projection_runs VALUES ('t2', 'starting')"
    )
    _ = conn.execute(
        "INSERT INTO orchestration_v2_projection_runs VALUES ('t3', 'completed')"
    )
    conn.commit()
    conn.close()

    env = SyncEnv.from_home(str(home), platform="linux")
    assert busy_threads(env) == EXPECTED_LIVE_RUNS


def test_sync_binary_paths_points_at_installed_wrappers(tmp_path: Path) -> None:
    """Enabled provider instances receive absolute path to ~/.local/bin wrapper."""
    home = tmp_path / "home"
    bin_dir = home / ".local" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "pi").touch(mode=0o755)
    (bin_dir / "codex").touch(mode=0o755)
    (bin_dir / "claude").touch(mode=0o755)

    live: JsonObject = {
        "providerInstances": {
            "pi": {"enabled": True},
            "codex": {"enabled": True},
            "claudeAgent": {"enabled": True},
        }
    }
    env = SyncEnv.from_home(str(home), platform="linux")
    sync_binary_paths(live, env)

    instances = live["providerInstances"]
    assert isinstance(instances, dict)
    pi_conf = instances["pi"]
    assert isinstance(pi_conf, dict)
    assert pi_conf.get("config") == {"binaryPath": str(bin_dir / "pi")}
    codex_conf = instances["codex"]
    assert isinstance(codex_conf, dict)
    assert codex_conf.get("config") == {"binaryPath": str(bin_dir / "codex")}
    claude_conf = instances["claudeAgent"]
    assert isinstance(claude_conf, dict)
    assert claude_conf.get("config") == {"binaryPath": str(bin_dir / "claude")}


def test_pair_forwards_extra_args_without_automatic_tailscale_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pair command passes forwarded args verbatim to ops_cli."""
    home = tmp_path / "home"
    env = SyncEnv.from_home(str(home), platform="linux")

    ran: list[list[str]] = []

    def fake_ops(_env: SyncEnv) -> list[str]:
        return ["/bin/t3"]

    def fake_run(argv: Sequence[str]) -> int:
        ran.append(list(argv))
        return 0

    monkeypatch.setattr("sync.maintenance.t3.ops_cli", fake_ops)
    monkeypatch.setattr("sync.maintenance.t3.run_cmd", fake_run)

    args = argparse.Namespace(rest=["--tailscale", "--tailscale-serve-port", "8443"])
    rc = cmd_pair(args, env)
    assert rc == 0
    assert ran == [["/bin/t3", "pair", "--tailscale", "--tailscale-serve-port", "8443"]]


def test_service_commands_darwin_and_linux(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Service start, stop, restart dispatch according to platform."""
    home = tmp_path / "home"
    darwin_env = SyncEnv.from_home(str(home), platform="darwin")
    linux_env = SyncEnv.from_home(str(home), platform="linux")

    ran: list[list[str]] = []

    def fake_run(argv: Sequence[str]) -> int:
        ran.append(list(argv))
        return 0

    monkeypatch.setattr("sync.maintenance.t3.run_cmd", fake_run)

    rc = service_restart(darwin_env)
    assert rc == 0
    assert ran[-1][:2] == ["launchctl", "kickstart"]

    rc = service_restart(linux_env)
    assert rc == 0
    assert ran[-1] == ["systemctl", "--user", "restart", "t3code.service"]

    rc = service_start(darwin_env)
    assert rc == 0
    assert ran[-1][:2] == ["launchctl", "bootstrap"]

    rc = service_start(linux_env)
    assert rc == 0
    assert ran[-1] == ["systemctl", "--user", "start", "t3code.service"]
