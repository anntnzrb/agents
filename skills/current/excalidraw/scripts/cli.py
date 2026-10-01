# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""Run the mcp-excalidraw-server CLI and stop its canvas server when idle.

Every argument passes through unchanged to the latest upstream release. After each
command, the wrapper makes sure one detached watchdog follows the running canvas
server. The watchdog exports the scene and stops the server once nothing has used
the canvas for the idle timeout.
"""

import hashlib
import http.client
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum, auto
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Sequence

UPSTREAM = ("bun", "x", "mcp-excalidraw-server@latest")
SERVICE_NAME = "mcp-excalidraw-canvas"
WATCHDOG_COMMAND = "__watchdog"
DEFAULT_URL = "http://127.0.0.1:3000"
DEFAULT_IDLE_SECONDS = 1800.0
MAX_POLL_SECONDS = 30.0
HTTP_TIMEOUT_SECONDS = 2.0
UPSTREAM_TIMEOUT_SECONDS = 120.0
EXPORT_ATTEMPTS = 2

HELP = """excalidraw skill wrapper

Usage:
  uv run --script <skill-dir>/scripts/cli.py <mcp-excalidraw-server-args>...

Delegates to:
  bun x mcp-excalidraw-server@latest <args>...

Idle shutdown:
  A detached watchdog stops the canvas server after EXCALIDRAW_IDLE_TIMEOUT
  seconds (default 1800) without activity. Activity is an open browser tab, a
  scene change, or any command run through this wrapper. Before stopping, it
  exports a non-empty scene to <state-dir>/recovery/. Set the timeout to 0 to
  disable idle shutdown.

State directory:
  EXCALIDRAW_SKILL_STATE_DIR, else $XDG_STATE_HOME/excalidraw-skill,
  else ~/.local/state/excalidraw-skill.
"""


class Action(StrEnum):
    """What the watchdog does after one observation."""

    KEEP = auto()
    STOP = auto()
    EXIT = auto()


@dataclass(frozen=True, slots=True, kw_only=True)
class Health:
    """The canvas server's `/health` payload, narrowed to the fields we use."""

    pid: int
    browser_tabs: int
    elements: int


@dataclass(frozen=True, slots=True, kw_only=True)
class Observation:
    """One poll of the canvas server and the wrapper's last-use marker."""

    server_pid: int
    browser_tabs: int
    elements: int
    scene_hash: str
    last_used: float


@dataclass(frozen=True, slots=True, kw_only=True)
class WatchState:
    """What the watchdog remembers between polls."""

    server_pid: int
    scene_hash: str
    last_activity: float


@dataclass(frozen=True, slots=True, kw_only=True)
class Heartbeat:
    """The live watchdog's claim on one server."""

    watchdog_pid: int
    server_pid: int
    refreshed_at: float


def decide(
    state: WatchState,
    seen: Observation | None,
    *,
    now: float,
    idle_seconds: float,
) -> tuple[Action, WatchState]:
    """Return the watchdog's next action and its updated state."""
    if seen is None or seen.server_pid != state.server_pid:
        return Action.EXIT, state
    active = seen.browser_tabs > 0 or seen.scene_hash != state.scene_hash
    last_activity = max(now if active else state.last_activity, seen.last_used)
    updated = WatchState(
        server_pid=state.server_pid,
        scene_hash=seen.scene_hash,
        last_activity=last_activity,
    )
    if idle_seconds > 0 and now - last_activity >= idle_seconds:
        return Action.STOP, updated
    return Action.KEEP, updated


def idle_timeout() -> float:
    """Read the idle timeout in seconds; 0 disables idle shutdown."""
    raw = os.environ.get("EXCALIDRAW_IDLE_TIMEOUT")
    if raw is None:
        return DEFAULT_IDLE_SECONDS
    try:
        value = float(raw)
    except ValueError as err:
        msg = f"EXCALIDRAW_IDLE_TIMEOUT must be a number of seconds, got {raw!r}"
        raise SystemExit(msg) from err
    return max(value, 0.0)


def poll_seconds(idle_seconds: float) -> float:
    """Poll often enough to stop within a quarter of the idle timeout."""
    if idle_seconds <= 0:
        return MAX_POLL_SECONDS
    return min(MAX_POLL_SECONDS, max(idle_seconds / 4, 1.0))


def state_dir() -> Path:
    """Return the directory for the watchdog heartbeat, log, and recovery exports."""
    if explicit := os.environ.get("EXCALIDRAW_SKILL_STATE_DIR"):
        return Path(explicit)
    base = os.environ.get("XDG_STATE_HOME")
    root = Path(base) if base else Path.home() / ".local" / "state"
    return root / "excalidraw-skill"


def canvas_url() -> str:
    """Return the canvas server URL the upstream CLI uses."""
    return os.environ.get("EXPRESS_SERVER_URL", DEFAULT_URL).rstrip("/")


def fetch(path: str) -> bytes | None:
    """GET a canvas endpoint body; return None when the server is unreachable."""
    request = urllib.request.Request(f"{canvas_url()}{path}")  # noqa: S310 - URL comes from canvas config
    try:
        # typeshed types urlopen() as Any; an http URL always yields HTTPResponse.
        response = cast(
            "http.client.HTTPResponse",
            urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS),  # noqa: S310 - URL comes from canvas config
        )
        with response:
            return response.read()
    except OSError, http.client.HTTPException:
        return None


def decode(body: bytes | None) -> object:
    """Decode a JSON body into an unvalidated value for pattern matching."""
    if body is None:
        return None
    try:
        value: object = json.loads(body)  # pyright: ignore[reportAny] - narrowed by match
    except ValueError:
        return None
    return value


def parse_health(raw: object) -> Health | None:
    """Narrow a `/health` body; None unless it is this package's canvas server."""
    match raw:
        case {
            "service": str(service),
            "pid": int(pid),
            "websocket_clients": int(tabs),
            "elements_count": int(elements),
        } if service == SERVICE_NAME and not any(
            isinstance(value, bool) for value in (pid, tabs, elements)
        ):
            return Health(pid=pid, browser_tabs=tabs, elements=elements)
        case _:
            return None


def read_health() -> Health | None:
    """Return the running canvas server's health, or None when absent."""
    return parse_health(decode(fetch("/health")))


def scene_hash() -> str:
    """Hash the raw scene body so the watchdog can spot edits from any source."""
    return hashlib.sha256(fetch("/api/elements") or b"").hexdigest()


@dataclass(frozen=True, slots=True, kw_only=True)
class Paths:
    """Files the wrapper and watchdog share."""

    root: Path

    @property
    def marker(self) -> Path:
        """Touched on every wrapper command."""
        return self.root / "last-used"

    @property
    def heartbeat(self) -> Path:
        """Owned by the live watchdog."""
        return self.root / "watchdog.json"

    @property
    def log(self) -> Path:
        """Watchdog decisions and failures."""
        return self.root / "watchdog.log"

    @property
    def recovery(self) -> Path:
        """Exports written before an idle stop."""
        return self.root / "recovery"


def last_used(paths: Paths) -> float:
    """Return when a wrapper command last ran, or 0 when never."""
    try:
        return paths.marker.stat().st_mtime
    except FileNotFoundError:
        return 0.0


def observe(paths: Paths) -> Observation | None:
    """Poll the canvas server; return None when it is gone."""
    health = read_health()
    if health is None:
        return None
    return Observation(
        server_pid=health.pid,
        browser_tabs=health.browser_tabs,
        elements=health.elements,
        scene_hash=scene_hash(),
        last_used=last_used(paths),
    )


def log(paths: Paths, message: str) -> None:
    """Append a timestamped line to the watchdog log."""
    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    with paths.log.open("a", encoding="utf-8") as handle:
        _ = handle.write(f"{stamp} {message}\n")


def read_heartbeat(paths: Paths) -> Heartbeat | None:
    """Return the current heartbeat, or None when absent or unreadable."""
    try:
        raw: object = json.loads(paths.heartbeat.read_text(encoding="utf-8"))  # pyright: ignore[reportAny] - narrowed by match
    except FileNotFoundError, ValueError:
        return None
    match raw:
        case {
            "watchdog_pid": int(owner),
            "server_pid": int(server),
            "refreshed_at": int() | float() as refreshed,
        }:
            return Heartbeat(
                watchdog_pid=owner, server_pid=server, refreshed_at=float(refreshed)
            )
        case _:
            return None


def write_heartbeat(paths: Paths, server_pid: int) -> None:
    """Claim the heartbeat for this watchdog process."""
    payload = {
        "watchdog_pid": os.getpid(),
        "server_pid": server_pid,
        "refreshed_at": time.time(),
    }
    tmp = paths.heartbeat.with_name(f"watchdog.{os.getpid()}.tmp")
    _ = tmp.write_text(json.dumps(payload), encoding="utf-8")
    _ = tmp.replace(paths.heartbeat)


def watchdog_alive(paths: Paths, server_pid: int, idle_seconds: float) -> bool:
    """Report whether a watchdog with a fresh heartbeat follows this server."""
    heartbeat = read_heartbeat(paths)
    if heartbeat is None or heartbeat.server_pid != server_pid:
        return False
    return time.time() - heartbeat.refreshed_at < 3 * poll_seconds(idle_seconds)


def spawn_watchdog(server_pid: int) -> None:
    """Start a detached watchdog that outlives the agent and its terminal."""
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        WATCHDOG_COMMAND,
        str(server_pid),
    ]
    if sys.platform == "win32":
        _ = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        return
    _ = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def ensure_watchdog(paths: Paths) -> None:
    """Start a watchdog for the running server unless one already follows it."""
    idle_seconds = idle_timeout()
    if idle_seconds <= 0:
        return
    health = read_health()
    if health is None or watchdog_alive(paths, health.pid, idle_seconds):
        return
    spawn_watchdog(health.pid)


def upstream(*args: str) -> subprocess.CompletedProcess[str]:
    """Run an upstream CLI command and capture its output."""
    try:
        return subprocess.run(
            [*UPSTREAM, *args],
            shell=False,
            check=False,
            capture_output=True,
            text=True,
            timeout=UPSTREAM_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(
            [*UPSTREAM, *args],
            124,
            "",
            f"timed out after {UPSTREAM_TIMEOUT_SECONDS:g}s",
        )


def export_and_stop(paths: Paths, elements: int) -> bool:
    """Export a non-empty scene, then stop the server; return True on stop."""
    if elements > 0:
        paths.recovery.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        target = paths.recovery / f"canvas-{stamp}.excalidraw"
        for _ in range(EXPORT_ATTEMPTS):
            exported = upstream("export", "--out", str(target))
            if exported.returncode == 0:
                break
            log(paths, f"export failed: {exported.stderr.strip()}")
        else:
            log(paths, "keeping server; retrying next idle window")
            return False
        log(paths, f"exported {elements} elements to {target}")
    stopped = upstream("stop")
    log(paths, f"stop exit={stopped.returncode} {stopped.stdout.strip()}")
    return stopped.returncode == 0


def run_watchdog(server_pid: int) -> int:
    """Follow one canvas server until it stops or goes idle."""
    paths = Paths(root=state_dir())
    paths.root.mkdir(parents=True, exist_ok=True)
    idle_seconds = idle_timeout()
    first = observe(paths)
    if first is None or first.server_pid != server_pid:
        return 0
    write_heartbeat(paths, server_pid)
    log(paths, f"watching server pid={server_pid} idle={idle_seconds:g}s")
    state = WatchState(
        server_pid=server_pid,
        scene_hash=first.scene_hash,
        last_activity=max(time.time(), first.last_used),
    )
    interval = poll_seconds(idle_seconds)
    while True:
        time.sleep(interval)
        heartbeat = read_heartbeat(paths)
        if heartbeat is not None and heartbeat.watchdog_pid != os.getpid():
            return 0
        seen = observe(paths)
        action, state = decide(state, seen, now=time.time(), idle_seconds=idle_seconds)
        if action is Action.EXIT:
            log(paths, f"server pid={server_pid} gone, watchdog exiting")
            return 0
        if action is Action.STOP:
            if export_and_stop(paths, 0 if seen is None else seen.elements):
                return 0
            state = WatchState(
                server_pid=server_pid,
                scene_hash=state.scene_hash,
                last_activity=time.time(),
            )
        write_heartbeat(paths, server_pid)


def run(argv: Sequence[str]) -> int:
    """Delegate to the upstream CLI and keep a watchdog on the canvas server."""
    if argv and argv[0] == WATCHDOG_COMMAND:
        match argv[1:]:
            case [pid] if pid.isdigit():
                return run_watchdog(int(pid))
            case _:
                print(f"usage: {WATCHDOG_COMMAND} <server-pid>", file=sys.stderr)
                return 2
    if argv and argv[0] == "--":
        argv = argv[1:]
    if not argv or argv[0] in {"-h", "--help"}:
        print(HELP)
        return 0
    if shutil.which("bun") is None:
        print("error: required executable not found: bun", file=sys.stderr)
        print("Install bun: https://bun.sh", file=sys.stderr)
        return 127
    paths = Paths(root=state_dir())
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.marker.touch()
    completed = subprocess.run([*UPSTREAM, *argv], shell=False, check=False)
    paths.marker.touch()
    ensure_watchdog(paths)
    return completed.returncode


def main() -> int:
    """Run the wrapper with the process arguments."""
    return run(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
