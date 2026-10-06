# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Restart the Paseo daemon onto the newest release while it is idle."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from sync.runtime.jsonc import is_obj_dict, is_obj_list

if TYPE_CHECKING:
    from collections.abc import Sequence

BUSY_STATUSES: frozenset[str] = frozenset({"initializing", "running"})

type Action = Literal["absent", "unknown", "current", "postpone", "restart"]


def say(msg: str) -> None:
    """Write one journal line to stdout."""
    _ = sys.stdout.write(f"paseo-update: {msg}\n")
    _ = sys.stdout.flush()


def _json(text: str) -> object:
    """Parse JSON, mapping malformed input to None."""
    try:
        val: object = json.loads(text)  # pyright: ignore[reportAny]
    except ValueError:
        return None
    else:
        return val


def daemon_version(status: str) -> str | None:
    """Extract `daemonVersion` from `paseo daemon status --json` while running."""
    fields = _json(status)
    if not is_obj_dict(fields):
        return None
    raw_status = fields.get("localDaemon")
    raw_version = fields.get("daemonVersion")
    if raw_status == "running" and isinstance(raw_version, str) and raw_version:
        return raw_version
    return None


def cli_version(output: str) -> str | None:
    """Return the last token of `paseo --version`, ignoring wrapper warnings."""
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        return None
    token = lines[-1].split()[-1].removeprefix("v")
    return token if token[:1].isdigit() else None


def busy_agents(listing: str) -> bool:
    """Report whether any agent is mid-turn or the listing cannot be read."""
    agents = _json(listing)
    if not is_obj_list(agents):
        return True
    for agent in agents:
        if not is_obj_dict(agent):
            return True
        status = agent.get("status")
        if isinstance(status, str) and status in BUSY_STATUSES:
            return True
    return False


def decide(running: str | None, latest: str | None, *, busy: bool) -> Action:
    """Choose what to do with the daemon."""
    if running is None:
        return "absent"
    if latest is None:
        return "unknown"
    if latest == running:
        return "current"
    return "postpone" if busy else "restart"


def run_paseo(wrapper: Path, args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """Run the managed wrapper and capture its output."""
    return subprocess.run(  # noqa: S603
        [str(wrapper), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=600,
    )


def _restart_service(service: str, *, platform: str) -> int:
    if platform == "darwin":
        cmd_launch = [
            "launchctl",
            "kickstart",
            "-k",
            f"gui/{os.getuid()}/{service}",
        ]
        return subprocess.call(cmd_launch)  # noqa: S603
    cmd_sys = ["systemctl", "--user", "restart", service]
    return subprocess.call(cmd_sys)  # noqa: S603


def update_paseo(
    service: str,
    *,
    wrapper: Path | None = None,
    platform: str = sys.platform,
) -> int:
    """Restart the daemon when it is behind and idle."""
    wrap = wrapper or (Path.home() / ".local" / "bin" / "paseo")
    status = run_paseo(wrap, ["daemon", "status", "--json"])
    running = daemon_version(status.stdout)
    if running is None:
        say("the daemon is not running; nothing to update")
        return 0
    version = run_paseo(wrap, ["--version"])
    latest = cli_version(version.stdout) if version.returncode == 0 else None
    listing = run_paseo(wrap, ["agent", "ls", "--global", "--json"])
    busy = listing.returncode != 0 or busy_agents(listing.stdout)
    action = decide(running, latest, busy=busy)
    match action:
        case "unknown":
            say("could not resolve the newest release; not restarting")
            return 1
        case "current":
            say(f"current at {running}")
            return 0
        case "postpone":
            say(f"agents are mid-turn; postponing {running} -> {latest}")
            return 0
        case "absent":
            say("the daemon is not running; nothing to update")
            return 0
        case "restart":
            say(f"restarting {running} -> {latest}")
            return _restart_service(service, platform=platform)
