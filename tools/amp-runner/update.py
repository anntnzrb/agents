#!/usr/bin/env python3
"""Restart the Amp runner onto the newest cached release while it is idle.

The `amp` wrapper downloads new releases on every launch, but a long-lived
runner keeps executing the version it started with. This script refreshes the
wrapper's cache, compares it with the running executable, and restarts the
systemd unit only when the runner is behind and no thread shows activity.

Busy evidence comes from the runner's JSON log: any thread event in the last
IDLE_MINUTES, or a thread whose last agent state is not idle and that moved
within STUCK_MINUTES. Unknown state never restarts.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

UNIT = "amp-runner-agents.service"
WRAPPER = Path.home() / ".local" / "bin" / "amp"
LOG = Path.home() / ".cache" / "amp" / "logs" / "runner-agents.log"
LOG_TAIL_BYTES = 4 * 1024 * 1024
IDLE_MINUTES = 15
STUCK_MINUTES = 120


def say(msg: str) -> None:
    print(f"amp-runner: {msg}", flush=True)


def systemctl(*args: str) -> str:
    return subprocess.run(
        ["systemctl", "--user", *args], capture_output=True, text=True, check=False
    ).stdout.strip()


def running_exe() -> Path | None:
    pid = systemctl("show", UNIT, "-p", "MainPID", "--value")
    if not pid.isdigit() or pid == "0":
        return None
    try:
        return Path(os.readlink(f"/proc/{pid}/exe"))
    except OSError:
        return None


def cached_exe(running: Path) -> Path | None:
    """Launch the wrapper once so it resolves the newest release, then locate it.

    Every wrapper launch moves the package cache's `current` link to the newest
    release; the runner's own executable lives in that same cache.
    """
    out = subprocess.run(
        [str(WRAPPER), "--version"],
        capture_output=True,
        text=True,
        check=False,
        timeout=600,
    )
    if out.returncode != 0:
        return None
    current = _package_root(running) / "current"
    target = current.resolve() / "node_modules" / "@ampcode" / "cli" / "bin" / "amp"
    return target if target.exists() else None


def _package_root(exe: Path) -> Path:
    """`…/packages/<hash>/versions/<v>/node_modules/@ampcode/cli/bin/amp` -> `…/<hash>`."""
    for parent in exe.parents:
        if parent.name == "versions":
            return parent.parent
    return exe.parent


def busy_threads(now: datetime) -> list[str]:
    """Thread ids with recent activity; raises OSError when the log is unreadable."""
    with LOG.open("rb") as f:
        _ = f.seek(max(0, LOG.stat().st_size - LOG_TAIL_BYTES))
        lines = f.read().decode(errors="replace").splitlines()
    last_seen: dict[str, datetime] = {}
    last_state: dict[str, str] = {}
    for line in lines:
        try:
            event = cast(object, json.loads(line))
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        fields = cast("dict[str, object]", event)
        thread, stamp = fields.get("threadId"), fields.get("@timestamp")
        if not isinstance(thread, str) or not isinstance(stamp, str):
            continue
        try:
            last_seen[thread] = datetime.fromisoformat(stamp)
        except ValueError:
            continue
        if fields.get("message") == "[observer] onAgentState":
            last_state[thread] = str(fields.get("subtype"))
    busy: list[str] = []
    for thread, seen in last_seen.items():
        age = now - seen
        recent = age < timedelta(minutes=IDLE_MINUTES)
        mid_turn = last_state.get(thread, "idle") != "idle" and age < timedelta(
            minutes=STUCK_MINUTES
        )
        if recent or mid_turn:
            busy.append(thread)
    return busy


def main() -> int:
    running = running_exe()
    if running is None:
        say(f"{UNIT} is not running; nothing to update")
        return 0
    latest = cached_exe(running)
    if latest is None:
        say("could not resolve the newest cached release; not restarting")
        return 1
    if latest.resolve() == running.resolve():
        say(f"current at {_version(running)}")
        return 0
    try:
        busy = busy_threads(datetime.now(UTC))
    except OSError as error:
        say(f"cannot read {LOG} ({error}); not restarting")
        return 1
    if busy:
        say(
            f"{len(busy)} thread(s) active; postponing {_version(running)} -> {_version(latest)}"
        )
        return 0
    say(f"restarting {_version(running)} -> {_version(latest)}")
    rc = subprocess.call(["systemctl", "--user", "restart", UNIT])
    if rc != 0:
        return rc
    # The wrapper execs into the cached binary shortly after systemd starts it.
    after = None
    for _ in range(30):
        after = running_exe()
        if after is not None and after.resolve() == latest.resolve():
            break
        time.sleep(2)
    if after is None or after.resolve() != latest.resolve():
        say(f"restart did not land on {_version(latest)} (running {after})")
        return 1
    say(f"running {_version(after)}")
    return 0


def _version(exe: Path) -> str:
    for parent in exe.parents:
        if parent.parent.name == "versions":
            return parent.name
    return str(exe)


if __name__ == "__main__":
    sys.exit(main())
