# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Background SSOT updates: fast-forward the checkout and schedule the updater.

Every machine converges on ``origin/main``. The updater only fast-forwards a
clean ``main`` checkout; anything else means someone is working there, so the
checkout is left untouched. A per-user timer (systemd) or launch agent
(launchd) runs ``sync update`` at idle priority.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, cast

from sync.runtime.errors import panic_message, warn
from sync.runtime.process import RunProcessOptions, command_exists, run_process

if TYPE_CHECKING:
    from sync.core.harness import SyncEnv

__all__ = [
    "LAUNCHD_LABEL",
    "UPDATE_UNIT",
    "fast_forward_ssot",
    "read_synced_commit",
    "reconcile_update_schedule",
    "record_synced_commit",
]

UPDATE_BRANCH = "main"
UPDATE_REMOTE = "origin"
UPDATE_INTERVAL_SECONDS = 300
UPDATE_UNIT = "agents-update"
LAUNCHD_LABEL = "dev.agents.update"
SYNCED_STATE_FILE = "update.json"
GIT_TIMEOUT_MS = 60_000
SERVICE_TIMEOUT_MS = 30_000

# launchd starts agents with a bare PATH; sync needs uv, git, and node from
# these. systemd user units inherit the user manager's PATH instead.
_DARWIN_PATH_DIRS = (
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


async def _git(ssot_home: str, *args: str) -> tuple[bool, str]:
    result = await run_process(
        ["git", "-C", ssot_home, *args], RunProcessOptions(timeout_ms=GIT_TIMEOUT_MS)
    )
    ok = result.exit_code == 0 and not result.timed_out and not result.output_limited
    return ok, (result.stdout if ok else result.stderr).strip()


async def fast_forward_ssot(ssot_home: str) -> str | None:
    """Fast-forward a clean ``main`` checkout; return HEAD, or None to skip.

    Never merges, stashes, or resets. A failed fetch (offline) keeps the
    current HEAD so an unsynced local commit is still reconciled.
    """
    ok, branch = await _git(ssot_home, "symbolic-ref", "--short", "-q", "HEAD")
    if not ok or branch != UPDATE_BRANCH:
        return None
    ok, changes = await _git(ssot_home, "status", "--porcelain", "--untracked-files=no")
    if not ok or changes:
        return None

    upstream = f"{UPDATE_REMOTE}/{UPDATE_BRANCH}"
    fetched, detail = await _git(
        ssot_home, "fetch", "--quiet", UPDATE_REMOTE, UPDATE_BRANCH
    )
    if not fetched:
        warn(f"update: fetch failed; keeping local checkout ({detail})")
    else:
        behind, _ = await _git(
            ssot_home, "merge-base", "--is-ancestor", "HEAD", upstream
        )
        if behind:
            merged, detail = await _git(
                ssot_home, "merge", "--ff-only", "--quiet", upstream
            )
            if not merged:
                warn(f"update: fast-forward failed; keeping local checkout ({detail})")

    ok, head = await _git(ssot_home, "rev-parse", "HEAD")
    return head if ok else None


def _synced_state_path(managed_state_home: str) -> Path:
    return Path(managed_state_home) / SYNCED_STATE_FILE


def read_synced_commit(managed_state_home: str) -> str | None:
    """Return the last commit ``sync update`` reconciled successfully."""
    try:
        data = cast(
            "object", json.loads(_synced_state_path(managed_state_home).read_text())
        )
    except (OSError, ValueError):
        return None
    commit = (
        cast("dict[str, object]", data).get("commit")
        if isinstance(data, dict)
        else None
    )
    return commit if isinstance(commit, str) else None


def record_synced_commit(managed_state_home: str, commit: str) -> None:
    """Persist the commit that was just reconciled."""
    path = _synced_state_path(managed_state_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    _ = tmp.write_text(json.dumps({"commit": commit}) + "\n")
    _ = tmp.replace(path)


def _update_command(sync_env: SyncEnv) -> list[str]:
    python = Path(sync_env.runtime_home) / "sync-current" / ".venv" / "bin" / "python"
    return [str(python), "-m", "sync.cli", "update"]


def _systemd_units(sync_env: SyncEnv) -> dict[Path, str]:
    unit_dir = Path(sync_env.home) / ".config" / "systemd" / "user"
    command = " ".join(_update_command(sync_env))
    service = f"""\
[Unit]
Description=Fast-forward the agents SSOT and reconcile it

[Service]
Type=oneshot
ExecStart={command}
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
    return {
        unit_dir / f"{UPDATE_UNIT}.service": service,
        unit_dir / f"{UPDATE_UNIT}.timer": timer,
    }


def _launchd_plist(sync_env: SyncEnv) -> tuple[Path, str]:
    home = sync_env.home
    user = Path(home).name
    path_value = ":".join(d.format(home=home, user=user) for d in _DARWIN_PATH_DIRS)
    args = "".join(f"<string>{arg}</string>" for arg in _update_command(sync_env))
    log = f"{home}/Library/Logs/{UPDATE_UNIT}.log"
    plist = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>{LAUNCHD_LABEL}</string>
    <key>ProgramArguments</key><array>{args}</array>
    <key>EnvironmentVariables</key><dict><key>PATH</key><string>{path_value}</string></dict>
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


def _write_changed(files: dict[Path, str]) -> bool:
    """Write files whose content differs; return True if any changed."""
    changed = False
    for path, content in files.items():
        if path.is_file() and path.read_text() == content:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        _ = path.write_text(content)
        changed = True
    return changed


async def _service(*argv: str) -> bool:
    result = await run_process(
        list(argv), RunProcessOptions(timeout_ms=SERVICE_TIMEOUT_MS)
    )
    if result.exit_code != 0 or result.timed_out:
        warn(f"update schedule: {' '.join(argv)} failed ({result.stderr.strip()})")
        return False
    return True


async def reconcile_update_schedule(sync_env: SyncEnv) -> None:
    """Install the periodic updater when the SSOT is a git checkout.

    Best-effort: a host without a user service manager only gets a warning.
    Unit files are rewritten and the service manager is touched only when the
    rendered content changes, so a steady-state sync costs no subprocess.
    """
    if not (Path(sync_env.ssot_home) / ".git").exists():
        return
    try:
        if sync_env.platform == "darwin":
            plist, content = _launchd_plist(sync_env)
            if not _write_changed({plist: content}) or not await command_exists(
                "launchctl"
            ):
                return
            target = f"gui/{os.getuid()}"
            _ = await run_process(
                ["launchctl", "bootout", f"{target}/{LAUNCHD_LABEL}"],
                RunProcessOptions(timeout_ms=SERVICE_TIMEOUT_MS),
            )
            _ = await _service("launchctl", "bootstrap", target, str(plist))
            return
        if not _write_changed(_systemd_units(sync_env)) or not await command_exists(
            "systemctl"
        ):
            return
        if await _service("systemctl", "--user", "daemon-reload"):
            _ = await _service(
                "systemctl", "--user", "enable", "--now", f"{UPDATE_UNIT}.timer"
            )
    except OSError as error:
        warn(f"update schedule: {panic_message(error)}")
