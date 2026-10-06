# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Restart the Amp runner onto the newest cached release while it is idle."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from sync.runtime.jsonc import is_obj_dict

if TYPE_CHECKING:
    from collections.abc import Callable

LOG_TAIL_BYTES = 4 * 1024 * 1024
IDLE_MINUTES = 15
STUCK_MINUTES = 120


def say(msg: str) -> None:
    """Print one journal line to stdout."""
    _ = sys.stdout.write(f"amp-runner: {msg}\n")
    _ = sys.stdout.flush()


def output(*argv: str) -> str:
    """Run a command and return stripped stdout."""
    return subprocess.run(  # noqa: S603
        list(argv), capture_output=True, text=True, check=False, timeout=60
    ).stdout.strip()


def service_target(service: str) -> str:
    """Format launchd target identifier for this user."""
    return f"gui/{os.getuid()}/{service}"


def running_pid(service: str, *, platform: str = sys.platform) -> str | None:
    """Return the running process ID of the service if active."""
    if platform == "darwin":
        listing = output("launchctl", "print", service_target(service))
        pids = [
            line.split("=", 1)[1].strip()
            for line in listing.splitlines()
            if line.strip().startswith("pid =")
        ]
        pid = pids[0] if pids else ""
    else:
        pid = output("systemctl", "--user", "show", service, "-p", "MainPID", "--value")
    return pid if pid.isdigit() and pid != "0" else None


def running_exe(service: str, *, platform: str = sys.platform) -> Path | None:
    """Resolve the running binary path for the service PID."""
    pid = running_pid(service, platform=platform)
    if pid is None:
        return None
    if platform == "darwin":
        names = output("lsof", "-n", "-w", "-a", "-p", pid, "-d", "txt", "-Fn")
        paths = [line[1:] for line in names.splitlines() if line.startswith("n")]
        return Path(paths[0]) if paths else None
    try:
        return Path(f"/proc/{pid}/exe").readlink()
    except OSError:
        return None


def restart(service: str, *, platform: str = sys.platform) -> int:
    """Restart the service unit or launchd agent."""
    if platform == "darwin":
        cmd = ["launchctl", "kickstart", "-k", service_target(service)]
        return subprocess.call(cmd)  # noqa: S603
    cmd = ["systemctl", "--user", "restart", service]
    return subprocess.call(cmd)  # noqa: S603


def package_root(exe: Path) -> Path:
    """`.../packages/<hash>/versions/<v>/node_modules/@ampcode/cli/bin/amp` -> root."""
    for parent in exe.parents:
        if parent.name == "versions":
            return parent.parent
    return exe.parent


def cached_exe(running: Path, *, wrapper: Path | None = None) -> Path | None:
    """Launch wrapper once so it resolves newest release, then locate binary."""
    wrap = wrapper or (Path.home() / ".local" / "bin" / "amp")
    out = subprocess.run(  # noqa: S603
        [str(wrap), "--version"],
        capture_output=True,
        text=True,
        check=False,
        timeout=600,
    )
    if out.returncode != 0:
        return None
    current = package_root(running) / "current"
    target = current.resolve() / "node_modules" / "@ampcode" / "cli" / "bin" / "amp"
    return target if target.exists() else None


def busy_threads(now: datetime, log_path: Path) -> list[str]:
    """Return thread IDs with recent activity; raises OSError if log unreadable."""
    with log_path.open("rb") as f:
        _ = f.seek(max(0, log_path.stat().st_size - LOG_TAIL_BYTES))
        lines = f.read().decode(errors="replace").splitlines()
    last_seen: dict[str, datetime] = {}
    last_state: dict[str, str] = {}
    for line in lines:
        try:
            event: object = json.loads(line)  # pyright: ignore[reportAny]
        except ValueError:
            continue
        if not is_obj_dict(event):
            continue
        thread = event.get("threadId")
        stamp = event.get("@timestamp")
        if not isinstance(thread, str) or not isinstance(stamp, str):
            continue
        try:
            last_seen[thread] = datetime.fromisoformat(stamp)
        except ValueError:
            continue
        if event.get("message") == "[observer] onAgentState":
            last_state[thread] = str(event.get("subtype"))
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


def version_name(exe: Path) -> str:
    """Extract release version directory name from executable path."""
    for parent in exe.parents:
        if parent.parent.name == "versions":
            return parent.name
    return str(exe)


def _wait_for_restart(
    service: str,
    latest: Path,
    *,
    platform: str,
    sleep_fn: Callable[[float], None],
) -> int:
    after: Path | None = None
    for _ in range(30):
        after = running_exe(service, platform=platform)
        if after is not None and after.resolve() == latest.resolve():
            say(f"running {version_name(after)}")
            return 0
        sleep_fn(2.0)
    say(f"restart did not land on {version_name(latest)} (running {after})")
    return 1


def _check_running_state(running: Path | None, latest: Path | None) -> int | None:
    if running is None:
        say("the runner is not running; nothing to update")
        return 0
    if latest is None:
        say("could not resolve the newest cached release; not restarting")
        return 1
    if latest.resolve() == running.resolve():
        say(f"current at {version_name(running)}")
        return 0
    return None


def update_amp_runner(
    service: str,
    log_file: Path,
    *,
    wrapper: Path | None = None,
    platform: str = sys.platform,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> int:
    """Restart runner onto the newest cached release when behind and idle."""
    running = running_exe(service, platform=platform)
    latest = cached_exe(running, wrapper=wrapper) if running else None
    check_code = _check_running_state(running, latest)
    if check_code is not None:
        return check_code
    if running is None or latest is None:
        return 1
    try:
        busy = busy_threads(datetime.now(UTC), log_file)
    except OSError as error:
        say(f"cannot read {log_file} ({error}); not restarting")
        return 1
    if busy:
        postpone_msg = (
            f"{len(busy)} thread(s) active; postponing "
            f"{version_name(running)} -> {version_name(latest)}"
        )
        say(postpone_msg)
        return 0
    say(f"restarting {version_name(running)} -> {version_name(latest)}")
    rc = restart(service, platform=platform)
    if rc != 0:
        return rc
    return _wait_for_restart(service, latest, platform=platform, sleep_fn=sleep_fn)
