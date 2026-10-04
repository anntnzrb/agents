#!/usr/bin/env python3
# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Restart the Paseo daemon onto the newest release while it is idle.

The `paseo` wrapper resolves the newest release on every launch, but the
long-lived daemon keeps the version it started with. The daemon reports its
own version; the wrapper's `--version` reports the newest release. The service
restarts only when they differ and no agent is mid-turn. An unreadable status
or agent listing never restarts.

The running version comes from the daemon, not from the executable path: the
service launches through the package cache's `current` link, which any CLI
call moves to the newest release.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Literal, cast

# Must match PASEO_UNIT in sync/src/sync/core/services.py.
UNIT = "paseo.service"
WRAPPER = Path.home() / ".local" / "bin" / "paseo"
BUSY_STATUSES = frozenset({"initializing", "running"})

Action = Literal["absent", "unknown", "current", "postpone", "restart"]


def say(msg: str) -> None:
    """Write one journal line."""
    print(f"paseo-update: {msg}", flush=True)  # noqa: T201 - stdout is the journal


def _json(text: str) -> object:
    """Parse JSON, mapping malformed input to None."""
    try:
        return cast("object", json.loads(text))
    except ValueError:
        return None


def daemon_version(status: str) -> str | None:
    """`daemonVersion` from `paseo daemon status --json` while the daemon runs."""
    fields = _json(status)
    if not isinstance(fields, dict):
        return None
    report = cast("dict[str, object]", fields)
    version = report.get("daemonVersion")
    running = report.get("localDaemon") == "running"
    return version if running and isinstance(version, str) and version else None


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
    if not isinstance(agents, list):
        return True
    for agent in cast("list[object]", agents):
        if not isinstance(agent, dict):
            return True
        if cast("dict[str, object]", agent).get("status") in BUSY_STATUSES:
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


def paseo(*args: str) -> subprocess.CompletedProcess[str]:
    """Run the managed wrapper and capture its output."""
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        [str(WRAPPER), *args], capture_output=True, text=True, check=False, timeout=600
    )


def main() -> int:
    """Restart the daemon when it is behind and idle."""
    status = paseo("daemon", "status", "--json")
    running = daemon_version(status.stdout)
    if running is None:
        say("the daemon is not running; nothing to update")
        return 0
    version = paseo("--version")
    latest = cli_version(version.stdout) if version.returncode == 0 else None
    listing = paseo("agent", "ls", "--global", "--json")
    busy = listing.returncode != 0 or busy_agents(listing.stdout)
    action = decide(running, latest, busy=busy)
    if action == "unknown":
        say("could not resolve the newest release; not restarting")
        return 1
    if action == "current":
        say(f"current at {running}")
        return 0
    if action == "postpone":
        say(f"agents are mid-turn; postponing {running} -> {latest}")
        return 0
    say(f"restarting {running} -> {latest}")
    # The unit PATH resolves systemctl; units hard-code no absolute paths.
    return subprocess.call(["systemctl", "--user", "restart", UNIT])  # noqa: S603, S607


if __name__ == "__main__":
    sys.exit(main())
