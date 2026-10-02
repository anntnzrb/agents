# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Sync-owned per-user services: systemd user units and launchd user agents.

A declared unit is authoritative: sync writes it, adopting a hand-made file of
the same name, and touches the service manager only when content changes.
Units sync owned but no longer declares are stopped and removed; unrelated
units are never touched. System-level services are out of scope.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from sync.core.cliproxy_config import AUTH_GATEWAY_ENV
from sync.core.cliproxy_deployment import CLI_PROXY_SOURCE_DIR
from sync.runtime.errors import panic_message, warn
from sync.runtime.fs import sync_text_file
from sync.runtime.jsonc import is_obj_dict, is_obj_list
from sync.runtime.process import RunProcessOptions, command_exists, run_process

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sync.core.harness import SyncEnv

__all__ = [
    "AMP_RUNNER_LABEL",
    "AUTH_GATEWAY_ENV",
    "LAUNCHD_LABEL",
    "UserUnit",
    "declared_launch_agents",
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
# Existing names, so sync adopts the hand-made runner in place instead of
# starting a second one that would crash-loop on the working-directory lock.
AMP_RUNNER_UNIT = "amp-runner-agents.service"
AMP_RUNNER_LABEL = "com.amp.runner.agents"
AMP_RUNNER_UPDATE_LABEL = "dev.agents.amp-runner-update"
AMP_RUNNER_DEPLOYMENT = ("tools", "amp-runner", "deployment.json")
CODEX_SERVER_DEPLOYMENT = ("tools", "codex-server", "deployment.json")
T3_DEPLOYMENT = ("tools", "t3", "deployment.json")
T3_REFRESH_UNIT = "t3-refresh-models"
T3_REFRESH_INTERVAL_SECONDS = 900
T3_REFRESH_LABEL = "dev.agents.t3-refresh-models"
T3_UPDATE_LABEL = "dev.agents.t3-update"
# Nightly attempts for restarting long-lived servers onto new releases; an
# attempt that finds the server busy or current is a no-op, so a busy night
# still gets later chances.
NIGHTLY_UPDATE_HOURS = (3, 4, 5)
NIGHTLY_UPDATE_CALENDAR = (
    f"*-*-* {NIGHTLY_UPDATE_HOURS[0]}..{NIGHTLY_UPDATE_HOURS[-1]}:00:00"
)

# Services start with a bare PATH; every unit declares one so it never depends
# on hand-made service-manager environment. Missing directories are harmless.
_PATH_DIRS = (
    "{home}/.local/bin",
    "{home}/.bun/bin",
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
    # The launcher pins the release; its digest in the unit makes a version
    # bump change the unit, which is what triggers a restart.
    launcher = Path(home) / ".local" / "bin" / "cli-proxy-api"
    launcher_digest = (
        hashlib.sha256(launcher.read_bytes()).hexdigest()[:16]
        if launcher.is_file()
        else "none"
    )
    gateway = f"""\
# launcher sha256 {launcher_digest}
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
        # The env file carries the token and the script is the gateway's code;
        # their digests in the unit make a token rotation or a code change
        # change the unit, which is what triggers a restart.
        env_digest = hashlib.sha256(env_file.read_bytes()).hexdigest()[:16]
        script = Path(sync_env.ssot_home) / CLI_PROXY_SOURCE_DIR / AUTH_GATEWAY_SCRIPT
        script_digest = (
            hashlib.sha256(script.read_bytes()).hexdigest()[:16]
            if script.is_file()
            else "none"
        )
        auth = f"""\
# env sha256 {env_digest}
# script sha256 {script_digest}
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


def _short_hostname() -> str:
    return socket.gethostname().split(".", 1)[0].strip().lower()


def _is_deployment_host(sync_env: SyncEnv, deployment: tuple[str, ...]) -> bool:
    """Return True if the service deployment's hosts list includes this host."""
    path = Path(sync_env.ssot_home).joinpath(*deployment)
    try:
        data = cast("object", json.loads(path.read_text()))
    except FileNotFoundError:
        return False
    except (OSError, ValueError) as error:
        warn(f"services: unreadable {path} ({panic_message(error)})")
        return False
    hosts = data.get("hosts") if is_obj_dict(data) else None
    if not is_obj_list(hosts):
        warn(f"services: {path} needs a hosts list")
        return False
    names = {h.lower() for h in hosts if isinstance(h, str)}
    return _short_hostname() in names


def _amp_runner_command(sync_env: SyncEnv) -> list[str]:
    """Serve ~/repos checkouts and the hidden SSOT checkout from a neutral cwd."""
    home = sync_env.home
    return [
        f"{home}/.local/bin/amp",
        "--no-tui",
        "--runner-id",
        _short_hostname(),
        "--no-notifications",
        f"--discover-dirs={home}/repos",
        "--discover-depth",
        "3",
        "--dir",
        sync_env.ssot_home,
        "--log-file",
        f"{home}/.cache/amp/logs/runner-agents.log",
    ]


def _amp_runner_unit(sync_env: SyncEnv) -> UserUnit:
    content = f"""\
[Unit]
Description=Amp runner
After=network-online.target

[Service]
Type=simple
WorkingDirectory=%h
Environment=PATH={_service_path(sync_env.home)}
ExecStart={" ".join(_amp_runner_command(sync_env))}
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
"""
    return UserUnit(AMP_RUNNER_UNIT, content)


def _nightly_update_units(
    sync_env: SyncEnv, name: str, what: str, command: str
) -> list[UserUnit]:
    """Restart a long-lived server onto its newest release while it is idle."""
    service = f"""\
[Unit]
Description=Update {what} when idle

[Service]
Type=oneshot
Environment=PATH={_service_path(sync_env.home)}
ExecStart={_runtime_python(sync_env)} {command}
TimeoutStartSec=15min
"""
    timer = f"""\
[Unit]
Description=Nightly {what} update

[Timer]
OnCalendar={NIGHTLY_UPDATE_CALENDAR}
RandomizedDelaySec=20min
Persistent=true

[Install]
WantedBy=timers.target
"""
    return [UserUnit(f"{name}.service", service), UserUnit(f"{name}.timer", timer)]


def _codex_server_units(sync_env: SyncEnv) -> list[UserUnit]:
    # Native Codex owns the detached daemon and its updater. The timer repairs
    # missing processes; starting an already-running daemon is idempotent.
    service = f"""\
[Unit]
Description=Ensure the native Codex app server and updater are running
After=network-online.target

[Service]
Type=oneshot
WorkingDirectory=%h
Environment=PATH={_service_path(sync_env.home)}
ExecStart={sync_env.home}/.local/bin/codex app-server daemon start
UMask=0077
# Detached native processes must survive the health-check command exiting.
KillMode=process
TimeoutStartSec=5min
"""
    timer = """\
[Unit]
Description=Periodic native Codex app-server health check

[Timer]
OnBootSec=10s
OnUnitActiveSec=300s

[Install]
WantedBy=timers.target
"""
    return [
        UserUnit("codex-app-server.service", service),
        UserUnit("codex-app-server.timer", timer),
    ]


def _t3_refresh_units(sync_env: SyncEnv) -> list[UserUnit]:
    """Keep T3's Claude model list in step with the gateway catalog.

    The catalog changes with upstream discovery, not with commits, so this
    runs on its own timer instead of inside sync.
    """
    t3ctl = Path(sync_env.ssot_home) / "tools" / "t3" / "t3ctl.py"
    service = f"""\
[Unit]
Description=Refresh T3 Code's Claude models from the gateway catalog

[Service]
Type=oneshot
Environment=PATH={_service_path(sync_env.home)}
ExecStart={_runtime_python(sync_env)} {t3ctl} refresh-models
Nice=19
IOSchedulingClass=idle
"""
    timer = f"""\
[Unit]
Description=Periodic T3 Code model refresh

[Timer]
OnBootSec=5min
OnUnitActiveSec={T3_REFRESH_INTERVAL_SECONDS}s

[Install]
WantedBy=timers.target
"""
    return [
        UserUnit(f"{T3_REFRESH_UNIT}.service", service),
        UserUnit(f"{T3_REFRESH_UNIT}.timer", timer),
    ]


def declared_user_units(sync_env: SyncEnv, *, gateway_host: bool) -> list[UserUnit]:
    """Return the systemd user units this host should run."""
    units = _updater_units(sync_env) if _is_git_checkout(sync_env) else []
    if gateway_host:
        units.extend(_gateway_units(sync_env))
    if _is_deployment_host(sync_env, AMP_RUNNER_DEPLOYMENT):
        units.append(_amp_runner_unit(sync_env))
        updater = Path(sync_env.ssot_home) / "tools" / "amp-runner" / "update.py"
        units.extend(
            _nightly_update_units(
                sync_env, "amp-runner-update", "the Amp runner", str(updater)
            )
        )
    if _is_deployment_host(sync_env, CODEX_SERVER_DEPLOYMENT):
        units.extend(_codex_server_units(sync_env))
    if _is_deployment_host(sync_env, T3_DEPLOYMENT):
        units.extend(_t3_refresh_units(sync_env))
        t3ctl = Path(sync_env.ssot_home) / "tools" / "t3" / "t3ctl.py"
        units.extend(
            _nightly_update_units(
                sync_env, "t3-update", "T3 Code", f"{t3ctl} auto-update"
            )
        )
    return units


def _owned_state_path(sync_env: SyncEnv) -> Path:
    return Path(sync_env.managed_state_home) / OWNED_STATE_FILE


def _read_owned(sync_env: SyncEnv) -> set[str]:
    try:
        data = cast("object", json.loads(_owned_state_path(sync_env).read_text()))
    except (OSError, ValueError):
        return set()
    units = data.get("units") if is_obj_dict(data) else None
    if not is_obj_list(units):
        return set()
    return {name for name in units if isinstance(name, str)}


def _record_owned(sync_env: SyncEnv, names: set[str]) -> None:
    content = json.dumps({"units": sorted(names)}) + "\n"
    sync_text_file(_owned_state_path(sync_env), content)


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


def _plist(label: str, body: str) -> str:
    return f"""\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>{label}</string>
{body}</dict>
</plist>
"""


def _plist_args(command: Sequence[str]) -> str:
    return "".join(f"<string>{arg}</string>" for arg in command)


def _updater_agent(sync_env: SyncEnv) -> UserUnit:
    home = sync_env.home
    command = [_runtime_python(sync_env), "-m", "sync.cli", "update"]
    log = f"{home}/Library/Logs/{UPDATE_UNIT}.log"
    body = f"""\
    <key>ProgramArguments</key><array>{_plist_args(command)}</array>
    <key>EnvironmentVariables</key><dict><key>PATH</key><string>{_service_path(home)}</string></dict>
    <key>StartInterval</key><integer>{UPDATE_INTERVAL_SECONDS}</integer>
    <key>RunAtLoad</key><true/>
    <key>ProcessType</key><string>Background</string>
    <key>LowPriorityIO</key><true/>
    <key>Nice</key><integer>19</integer>
    <key>StandardOutPath</key><string>{log}</string>
    <key>StandardErrorPath</key><string>{log}</string>
"""
    return UserUnit(LAUNCHD_LABEL, _plist(LAUNCHD_LABEL, body))


def _amp_runner_agent(sync_env: SyncEnv) -> UserUnit:
    home = sync_env.home
    body = f"""\
    <key>ProgramArguments</key><array>{_plist_args(_amp_runner_command(sync_env))}</array>
    <key>WorkingDirectory</key><string>{home}</string>
    <key>EnvironmentVariables</key><dict><key>PATH</key><string>{_service_path(home)}</string></dict>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>ThrottleInterval</key><integer>5</integer>
"""
    return UserUnit(AMP_RUNNER_LABEL, _plist(AMP_RUNNER_LABEL, body))


def _python_job_agent(
    sync_env: SyncEnv, label: str, args: Sequence[str], *, nightly: bool
) -> UserUnit:
    """Run a runtime-Python job from launchd, nightly or every refresh interval."""
    home = sync_env.home
    command = _plist_args([_runtime_python(sync_env), *args])
    log = f"{home}/Library/Logs/{label.removeprefix('dev.agents.')}.log"
    if nightly:
        minute = "<key>Minute</key><integer>0</integer>"
        hours = "".join(
            f"<dict><key>Hour</key><integer>{h}</integer>{minute}</dict>"
            for h in NIGHTLY_UPDATE_HOURS
        )
        schedule = f"<key>StartCalendarInterval</key><array>{hours}</array>"
    else:
        interval = T3_REFRESH_INTERVAL_SECONDS
        schedule = f"<key>StartInterval</key><integer>{interval}</integer>"
    body = f"""\
    <key>ProgramArguments</key><array>{command}</array>
    <key>EnvironmentVariables</key><dict><key>PATH</key><string>{_service_path(home)}</string></dict>
    {schedule}
    <key>ProcessType</key><string>Background</string>
    <key>StandardOutPath</key><string>{log}</string>
    <key>StandardErrorPath</key><string>{log}</string>
"""
    return UserUnit(label, _plist(label, body))


def _codex_server_agent(sync_env: SyncEnv) -> UserUnit:
    home = sync_env.home
    label = "dev.agents.codex-server"
    command = [f"{home}/.local/bin/codex", "app-server", "daemon", "start"]
    log = f"{home}/Library/Logs/codex-app-server-health.log"
    body = f"""\
    <key>ProgramArguments</key><array>{_plist_args(command)}</array>
    <key>WorkingDirectory</key><string>{home}</string>
    <key>EnvironmentVariables</key><dict><key>PATH</key><string>{_service_path(home)}</string></dict>
    <key>StartInterval</key><integer>300</integer>
    <key>RunAtLoad</key><true/>
    <key>AbandonProcessGroup</key><true/>
    <key>StandardOutPath</key><string>{log}</string>
    <key>StandardErrorPath</key><string>{log}</string>
"""
    return UserUnit(label, _plist(label, body))


def declared_launch_agents(sync_env: SyncEnv) -> list[UserUnit]:
    """Return the launchd user agents this host should run, keyed by label."""
    agents = [_updater_agent(sync_env)] if _is_git_checkout(sync_env) else []
    if _is_deployment_host(sync_env, AMP_RUNNER_DEPLOYMENT):
        agents.append(_amp_runner_agent(sync_env))
        updater = str(Path(sync_env.ssot_home) / "tools" / "amp-runner" / "update.py")
        agents.append(
            _python_job_agent(
                sync_env, AMP_RUNNER_UPDATE_LABEL, [updater], nightly=True
            )
        )
    if _is_deployment_host(sync_env, CODEX_SERVER_DEPLOYMENT):
        agents.append(_codex_server_agent(sync_env))
    if _is_deployment_host(sync_env, T3_DEPLOYMENT):
        t3ctl = str(Path(sync_env.ssot_home) / "tools" / "t3" / "t3ctl.py")
        agents.extend(
            [
                _python_job_agent(
                    sync_env, T3_REFRESH_LABEL, [t3ctl, "refresh-models"], nightly=False
                ),
                _python_job_agent(
                    sync_env, T3_UPDATE_LABEL, [t3ctl, "auto-update"], nightly=True
                ),
            ]
        )
    return agents


async def _reconcile_launch_agents(
    sync_env: SyncEnv, agents: Sequence[UserUnit]
) -> None:
    """Write declared agents, reload changed ones, and unload owned stale ones."""
    agent_dir = Path(sync_env.home) / "Library" / "LaunchAgents"
    owned = _read_owned(sync_env)
    declared = {agent.name for agent in agents}
    changed = _write_declared(
        agent_dir, [UserUnit(f"{a.name}.plist", a.content) for a in agents]
    )
    stale = sorted(owned - declared)
    if (changed or stale) and await command_exists("launchctl"):
        target = f"gui/{os.getuid()}"
        reload = [unit.name.removesuffix(".plist") for unit in changed]
        for label in [*stale, *reload]:
            _ = await run_process(
                ["launchctl", "bootout", f"{target}/{label}"],
                RunProcessOptions(timeout_ms=SERVICE_TIMEOUT_MS),
            )
        for label in reload:
            _ = await _service(
                "launchctl", "bootstrap", target, str(agent_dir / f"{label}.plist")
            )
    for label in stale:
        (agent_dir / f"{label}.plist").unlink(missing_ok=True)
    if owned != declared:
        _record_owned(sync_env, declared)


async def reconcile_services(sync_env: SyncEnv, *, gateway_host: bool) -> None:
    """Reconcile this host's declared services; best-effort, warnings only."""
    try:
        if sync_env.platform == "darwin":
            await _reconcile_launch_agents(sync_env, declared_launch_agents(sync_env))
        else:
            await reconcile_user_units(
                sync_env, declared_user_units(sync_env, gateway_host=gateway_host)
            )
    except OSError as error:
        warn(f"services: {panic_message(error)}")
