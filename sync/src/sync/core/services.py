# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Sync-owned per-user services: systemd user units and launchd user agents.

A declared unit is authoritative: sync writes it, adopting a hand-made file of
the same name, and touches the service manager only when content changes.
Units sync owned but no longer declares are stopped and removed; unrelated
units are never touched. System-level services are out of scope.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from sync.core.cliproxy_config import AUTH_GATEWAY_ENV
from sync.runtime.errors import panic_message, warn
from sync.runtime.process import RunProcessOptions, command_exists, run_process

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sync.core.harness import SyncEnv

__all__ = [
    "AUTH_GATEWAY_ENV",
    "LAUNCHD_LABEL",
    "UserUnit",
    "declared_user_units",
    "reconcile_services",
    "reconcile_user_units",
]

UPDATE_UNIT = "agents-update"
LAUNCHD_LABEL = "dev.agents.update"
UPDATE_INTERVAL_SECONDS = 300
OWNED_STATE_FILE = "services.json"
AUTH_GATEWAY_SCRIPT = "auth-gateway.py"
SERVICE_TIMEOUT_MS = 30_000

# Services start with a bare PATH; every unit declares one so it never depends
# on hand-made service-manager environment. Missing directories are harmless.
_PATH_DIRS = (
    "{home}/.local/bin",
    "{home}/.nix-profile/bin",
    "/etc/profiles/per-user/{user}/bin",
    "/run/current-system/sw/bin",
    "/nix/var/nix/profiles/default/bin",
    "/opt/homebrew/bin",
    "/usr/local/bin",
    "/usr/bin",
    "/bin",
    "/usr/sbin",
    "/sbin",
)


@dataclass(frozen=True, slots=True)
class UserUnit:
    """A systemd user unit sync declares, by file name and rendered content."""

    name: str
    content: str


def _service_path(home: str) -> str:
    user = Path(home).name
    return ":".join(d.format(home=home, user=user) for d in _PATH_DIRS)


def _runtime_python(sync_env: SyncEnv) -> str:
    return str(
        Path(sync_env.runtime_home) / "sync-current" / ".venv" / "bin" / "python"
    )


def _is_git_checkout(sync_env: SyncEnv) -> bool:
    return (Path(sync_env.ssot_home) / ".git").exists()


def _updater_units(sync_env: SyncEnv) -> list[UserUnit]:
    service = f"""\
[Unit]
Description=Fast-forward the agents SSOT and reconcile it

[Service]
Type=oneshot
Environment=PATH={_service_path(sync_env.home)}
ExecStart={_runtime_python(sync_env)} -m sync.cli update
Nice=19
IOSchedulingClass=idle
"""
    timer = f"""\
[Unit]
Description=Periodic agents SSOT update

[Timer]
OnBootSec=2min
OnUnitActiveSec={UPDATE_INTERVAL_SECONDS}s

[Install]
WantedBy=timers.target
"""
    return [
        UserUnit(f"{UPDATE_UNIT}.service", service),
        UserUnit(f"{UPDATE_UNIT}.timer", timer),
    ]


def _gateway_units(sync_env: SyncEnv) -> list[UserUnit]:
    home = sync_env.home
    state = Path(home) / ".cli-proxy-api"
    gateway = f"""\
[Unit]
Description=CLIProxyAPI gateway
StartLimitIntervalSec=300
StartLimitBurst=10

[Service]
Type=simple
WorkingDirectory=%h
Environment=PATH={_service_path(home)}
ExecStart={home}/.local/bin/cli-proxy-api
KillMode=mixed
Restart=always
RestartSec=5
UMask=0077
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=default.target
"""
    units = [UserUnit("cliproxyapi.service", gateway)]
    env_file = state / AUTH_GATEWAY_ENV
    if env_file.is_file():
        auth = f"""\
[Unit]
Description=CLIProxyAPI public Funnel auth gateway
After=cliproxyapi.service

[Service]
Type=simple
EnvironmentFile={env_file}
ExecStart={_runtime_python(sync_env)} {state / AUTH_GATEWAY_SCRIPT}
Restart=always
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=default.target
"""
        units.append(UserUnit("cliproxy-auth-gateway.service", auth))
    return units


def declared_user_units(sync_env: SyncEnv, *, gateway_host: bool) -> list[UserUnit]:
    """Return the systemd user units this host should run."""
    units = _updater_units(sync_env) if _is_git_checkout(sync_env) else []
    if gateway_host:
        units.extend(_gateway_units(sync_env))
    return units


def _owned_state_path(sync_env: SyncEnv) -> Path:
    return Path(sync_env.managed_state_home) / OWNED_STATE_FILE


def _read_owned(sync_env: SyncEnv) -> set[str]:
    try:
        data = cast("object", json.loads(_owned_state_path(sync_env).read_text()))
    except (OSError, ValueError):
        return set()
    units = (
        cast("dict[str, object]", data).get("units") if isinstance(data, dict) else None
    )
    if not isinstance(units, list):
        return set()
    return {name for name in cast("list[object]", units) if isinstance(name, str)}


def _record_owned(sync_env: SyncEnv, names: set[str]) -> None:
    path = _owned_state_path(sync_env)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    _ = tmp.write_text(json.dumps({"units": sorted(names)}) + "\n")
    _ = tmp.replace(path)


async def _service(*argv: str) -> bool:
    result = await run_process(
        list(argv), RunProcessOptions(timeout_ms=SERVICE_TIMEOUT_MS)
    )
    if result.exit_code != 0 or result.timed_out:
        warn(f"services: {' '.join(argv)} failed ({result.stderr.strip()})")
        return False
    return True


def _write_declared(unit_dir: Path, units: Sequence[UserUnit]) -> list[UserUnit]:
    """Write units whose content differs; return the ones that changed."""
    changed: list[UserUnit] = []
    for unit in units:
        path = unit_dir / unit.name
        if path.is_file() and path.read_text() == unit.content:
            continue
        unit_dir.mkdir(parents=True, exist_ok=True)
        _ = path.write_text(unit.content)
        changed.append(unit)
    return changed


async def _apply_with_systemd(
    changed: Sequence[UserUnit], stale: Sequence[str]
) -> None:
    """Stop pruned units, reload, and enable or restart changed installable units."""
    for name in stale:
        _ = await _service("systemctl", "--user", "disable", "--now", name)
    if not await _service("systemctl", "--user", "daemon-reload"):
        return
    for unit in changed:
        if "[Install]" not in unit.content:
            continue  # started by its timer, never directly
        if unit.name.endswith(".timer"):
            _ = await _service("systemctl", "--user", "enable", "--now", unit.name)
        elif await _service("systemctl", "--user", "enable", unit.name):
            _ = await _service("systemctl", "--user", "restart", unit.name)


async def reconcile_user_units(sync_env: SyncEnv, units: Sequence[UserUnit]) -> None:
    """Write declared units, prune owned stale ones, and apply only changes."""
    unit_dir = Path(sync_env.home) / ".config" / "systemd" / "user"
    owned = _read_owned(sync_env)
    declared = {unit.name for unit in units}
    changed = _write_declared(unit_dir, units)
    stale = sorted(owned - declared)
    if (changed or stale) and await command_exists("systemctl"):
        await _apply_with_systemd(changed, stale)
    for name in stale:
        (unit_dir / name).unlink(missing_ok=True)
    if owned != declared:
        _record_owned(sync_env, declared)


def _launchd_plist(sync_env: SyncEnv) -> tuple[Path, str]:
    home = sync_env.home
    command = [_runtime_python(sync_env), "-m", "sync.cli", "update"]
    args = "".join(f"<string>{arg}</string>" for arg in command)
    log = f"{home}/Library/Logs/{UPDATE_UNIT}.log"
    plist = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>{LAUNCHD_LABEL}</string>
    <key>ProgramArguments</key><array>{args}</array>
    <key>EnvironmentVariables</key><dict><key>PATH</key><string>{_service_path(home)}</string></dict>
    <key>StartInterval</key><integer>{UPDATE_INTERVAL_SECONDS}</integer>
    <key>RunAtLoad</key><true/>
    <key>ProcessType</key><string>Background</string>
    <key>LowPriorityIO</key><true/>
    <key>Nice</key><integer>19</integer>
    <key>StandardOutPath</key><string>{log}</string>
    <key>StandardErrorPath</key><string>{log}</string>
</dict>
</plist>
"""
    return Path(home) / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist", plist


async def _reconcile_launch_agent(sync_env: SyncEnv) -> None:
    if not _is_git_checkout(sync_env):
        return
    plist, content = _launchd_plist(sync_env)
    if plist.is_file() and plist.read_text() == content:
        return
    plist.parent.mkdir(parents=True, exist_ok=True)
    _ = plist.write_text(content)
    if not await command_exists("launchctl"):
        return
    target = f"gui/{os.getuid()}"
    _ = await run_process(
        ["launchctl", "bootout", f"{target}/{LAUNCHD_LABEL}"],
        RunProcessOptions(timeout_ms=SERVICE_TIMEOUT_MS),
    )
    _ = await _service("launchctl", "bootstrap", target, str(plist))


async def reconcile_services(sync_env: SyncEnv, *, gateway_host: bool) -> None:
    """Reconcile this host's declared services; best-effort, warnings only."""
    try:
        if sync_env.platform == "darwin":
            await _reconcile_launch_agent(sync_env)
        else:
            await reconcile_user_units(
                sync_env, declared_user_units(sync_env, gateway_host=gateway_host)
            )
    except OSError as error:
        warn(f"services: {panic_message(error)}")
