#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""t3ctl — deployment-driven operations for the T3 Code background service.

The deployment record (`deployment.json`, beside this script) declares the
host, release channel, and exposure modes. Desired non-secret server
settings live in `server-settings.json`. Everything else under ~/.t3 is
T3-owned runtime state and is never touched beyond what each command needs.

Run on the declared host for anything that mutates; `status`, `doctor`,
and `logs` are safe anywhere. Upstream CLI truth lives in the vendored
checkout: ~/src/vendored/github.com/pingdotgg/t3code (apps/server/src/cli/).
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import NoReturn, TypeAlias, cast

Json: TypeAlias = "str | int | float | bool | None | list[Json] | dict[str, Json]"
JsonObject: TypeAlias = "dict[str, Json]"

TOOLS_DIR = Path(__file__).resolve().parent
DEPLOYMENT_PATH = TOOLS_DIR / "deployment.json"
SETTINGS_PATH = TOOLS_DIR / "server-settings.json"
T3_HOME = Path(os.environ.get("T3CODE_HOME") or Path.home() / ".t3")
STATE_FILE = T3_HOME / "runtime" / "service-state.json"
RUNTIME_JSON = T3_HOME / "userdata" / "server-runtime.json"
SETTINGS_TARGET = T3_HOME / "userdata" / "settings.json"
BOOT_LOG = T3_HOME / "userdata" / "logs" / "boot-service.log"
UNIT = "t3code.service"
ENVIRONMENT_PATH = "/.well-known/t3/environment"

# Sync launch wrappers for the harnesses T3 drives, keyed by T3 provider instance.
WRAPPER_DIR = Path.home() / ".local" / "bin"
HARNESS_WRAPPERS: dict[str, str] = {"codex": "codex", "claudeAgent": "claude"}

# launchd uses the same label the T3 installer writes into its plist.
IS_MACOS = sys.platform == "darwin"
LAUNCHD_LABEL = "com.t3tools.t3code.service"
LAUNCHD_PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"


def die(msg: str) -> NoReturn:
    print(f"t3ctl: {msg}", file=sys.stderr)
    raise SystemExit(1)


def load_json_object(path: Path) -> JsonObject | None:
    try:
        data = cast(Json, json.loads(path.read_text()))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def load_deployment() -> JsonObject:
    data = load_json_object(DEPLOYMENT_PATH)
    if data is None:
        die(f"cannot read {DEPLOYMENT_PATH} as a JSON object")
    return data


def field(dotted: str) -> Json:
    cur: Json = DEPLOYMENT
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def str_field(dotted: str) -> str | None:
    value = field(dotted)
    return value if isinstance(value, str) else None


DEPLOYMENT = load_deployment()


def declared_host() -> str:
    return str_field("server.hostname") or die(
        "deployment.json is missing server.hostname"
    )


def current_host() -> str:
    return socket.gethostname()


def is_declared_host() -> bool:
    return current_host().strip().lower() == declared_host().strip().lower()


def require_declared_host() -> None:
    if not is_declared_host():
        die(
            f"declared host is '{declared_host()}'; this host is '{current_host()}'."
            + " Update tools/t3/deployment.json first if this host should run T3."
        )


def channel() -> str:
    return str_field("channel") or "latest"


def active_version() -> str | None:
    data = load_json_object(STATE_FILE)
    if data is None:
        return None
    version = data.get("activeVersion")
    return version if isinstance(version, str) else None


def resolved_version() -> str:
    return active_version() or channel()


def pinned_bin() -> Path | None:
    """The active runtime's self-contained executable (release-archive layout)."""
    version = active_version()
    if not version:
        return None
    path = T3_HOME / "runtime" / "versions" / version / "t3"
    return path if os.access(path, os.X_OK) else None


def package_runner(version: str, prefer_node: bool) -> list[str]:
    """Argv that runs the t3 CLI at `version` straight from the registry."""
    order = ["npx", "bunx"] if prefer_node else ["bunx", "npx"]
    for tool in order:
        if shutil.which(tool):
            args = [tool, "-y"] if tool == "npx" else [tool]
            return [*args, f"t3@{version}"]
    die("no JavaScript package runner found on PATH (npx or bunx)")


def ops_cli() -> list[str]:
    """Argv that runs the CLI version the service actually runs.

    Prefers the installed pinned runtime (fast, version-exact); falls back
    to a package runner.
    """
    pinned = pinned_bin()
    if pinned:
        return [str(pinned)]
    return package_runner(resolved_version(), prefer_node=True)


def install_cli() -> list[str]:
    """Argv for service install at the channel head.

    Whichever runner fetches the CLI, the service pins a self-contained
    release archive and never runs under the runner's interpreter.
    """
    return package_runner(channel(), prefer_node=True)


def run(argv: list[str]) -> int:
    print(f"+ {' '.join(argv)}", flush=True)
    return subprocess.call(argv)


def live_port() -> int | None:
    data = load_json_object(RUNTIME_JSON)
    if data is None:
        return None
    port = data.get("port")
    if isinstance(port, bool):
        return None
    if isinstance(port, int):
        return port
    if isinstance(port, str):
        try:
            return int(port)
        except ValueError:
            return None
    return None


def probe(port: int, timeout: float = 5.0) -> int | None:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        conn.request("GET", ENVIRONMENT_PATH)
        return conn.getresponse().status
    except (OSError, http.client.HTTPException):
        return None
    finally:
        conn.close()


def systemctl(*args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["systemctl", "--user", *args], capture_output=True, text=True, check=check
    )


def launchctl(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["launchctl", *args], capture_output=True, text=True, check=False
    )


def gui_target() -> str:
    return f"gui/{os.getuid()}"


def service_restart() -> int:
    if IS_MACOS:
        return run(["launchctl", "kickstart", "-k", f"{gui_target()}/{LAUNCHD_LABEL}"])
    return run(["systemctl", "--user", "restart", UNIT])


def service_stop() -> int:
    if IS_MACOS:
        return launchctl(
            "bootout", "--wait", f"{gui_target()}/{LAUNCHD_LABEL}"
        ).returncode
    return systemctl("stop", UNIT).returncode


def service_start() -> int:
    if IS_MACOS:
        return run(["launchctl", "bootstrap", gui_target(), str(LAUNCHD_PLIST)])
    return run(["systemctl", "--user", "start", UNIT])


def service_enabled_active() -> tuple[str, str]:
    if IS_MACOS:
        enabled = "enabled" if LAUNCHD_PLIST.exists() else "disabled"
        loaded = launchctl("print", f"{gui_target()}/{LAUNCHD_LABEL}").returncode == 0
        return enabled, ("active" if loaded else "inactive")
    return (
        systemctl("is-enabled", UNIT).stdout.strip() or "unknown",
        systemctl("is-active", UNIT).stdout.strip() or "unknown",
    )


def wait_for_endpoint(timeout_s: int = 30) -> int | None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        port = live_port()
        if port and probe(port, timeout=2) == 200:
            return port
        time.sleep(1)
    return None


def extra_args(args: argparse.Namespace) -> list[str]:
    rest: object = getattr(args, "rest", [])
    if not isinstance(rest, list):
        return []
    return [item for item in cast(list[object], rest) if isinstance(item, str)]


def lines_arg(args: argparse.Namespace, default: int = 30) -> int:
    value: object = getattr(args, "lines", default)
    return value if isinstance(value, int) else default


def cmd_status(_args: argparse.Namespace) -> int:
    match = "match" if is_declared_host() else "MISMATCH"
    print(f"declared host : {declared_host()}")
    print(f"this host     : {current_host()} ({match})")
    print(f"channel       : {channel()}")
    enabled, active = service_enabled_active()
    print(f"unit enabled  : {enabled}")
    print(f"unit active   : {active}")
    print(f"active version: {active_version() or 'none (service never installed)'}")
    port = live_port()
    if port:
        code = probe(port)
        print(f"bound port    : {port}")
        print(f"endpoint      : http://127.0.0.1:{port} -> {code or 'unreachable'}")
    else:
        print("bound port    : none (server not running)")
    print("--- tailscale serve ---")
    if shutil.which("tailscale"):
        _ = run(["tailscale", "serve", "status"])
    else:
        print("unavailable (tailscale not installed)")
    print("--- connect ---")
    try:
        _ = run([*ops_cli(), "connect", "status"])
    except SystemExit:
        print("  (no CLI runtime available)")
    return 0


def cmd_restart(_args: argparse.Namespace) -> int:
    require_declared_host()
    _ = service_restart()
    port = wait_for_endpoint()
    if port:
        print(f"t3code: active on http://127.0.0.1:{port}")
        return 0
    die("service restarted but the endpoint did not answer in time; try `doctor`")


def cmd_update(args: argparse.Namespace) -> int:
    require_declared_host()
    # `service install` at the channel head reconciles the unit, launcher, and
    # pinned runtime; `service update` is a deprecated alias upstream.
    rc = run([*install_cli(), "service", "install"])
    if rc == 0:
        return cmd_apply_settings(args)
    return rc


def cmd_install(_args: argparse.Namespace) -> int:
    require_declared_host()
    required = ("launchctl",) if IS_MACOS else ("systemctl", "loginctl")
    missing = [t for t in required if not shutil.which(t)]
    if missing:
        die(f"missing required tools: {', '.join(missing)} (need launchd or systemd)")
    if field("exposure.tailscaleServe") and not shutil.which("tailscale"):
        print(
            "t3ctl: warning — tailscaleServe is set but `tailscale` is not on PATH",
            file=sys.stderr,
        )
    if run([*install_cli(), "service", "install"]) != 0:
        return 1
    apply_settings()
    port = wait_for_endpoint()
    print(
        f"t3code: installed and active on http://127.0.0.1:{port}"
        if port
        else "t3code: installed; endpoint not answering yet — see `logs`"
    )
    if field("exposure.connect"):
        print("next: `t3ctl.py connect login`, `connect link`, then `restart`")
    return 0


def sync_binary_paths(live: JsonObject) -> None:
    """Point each harness driver at its sync wrapper by absolute path.

    The Claude driver spawns its binary without a shell, so a bare name is
    not reliably resolved against ~/.local/bin.
    """
    instances = live.get("providerInstances")
    if not isinstance(instances, dict):
        return
    for instance_id, bin_name in HARNESS_WRAPPERS.items():
        instance = instances.get(instance_id)
        if not isinstance(instance, dict):
            continue
        wrapper = WRAPPER_DIR / bin_name
        if not os.access(wrapper, os.X_OK):
            print(
                f"t3ctl: warning — {wrapper} missing; run sync on this host",
                file=sys.stderr,
            )
            continue
        config = instance.get("config")
        if not isinstance(config, dict):
            config = cast(JsonObject, {})
            cast(JsonObject, instance)["config"] = config
        cast(JsonObject, config)["binaryPath"] = str(wrapper)
        print(f"{instance_id} binaryPath -> {wrapper}")


def deep_merge(base: JsonObject, overlay: JsonObject) -> None:
    for key, value in overlay.items():
        existing = base.get(key)
        if isinstance(value, dict) and isinstance(existing, dict):
            deep_merge(existing, value)
        else:
            base[key] = value


def write_settings(live: JsonObject) -> None:
    fd, tmp = tempfile.mkstemp(dir=SETTINGS_TARGET.parent, suffix=".json")
    with os.fdopen(fd, "w") as f:
        json.dump(live, f, indent=2)
        _ = f.write("\n")
    os.replace(tmp, SETTINGS_TARGET)


def apply_settings() -> None:
    if not SETTINGS_TARGET.exists():
        die(f"{SETTINGS_TARGET} missing; is the service installed?")
    desired = load_json_object(SETTINGS_PATH)
    live = load_json_object(SETTINGS_TARGET)
    if desired is None or live is None:
        die("settings files must contain a JSON object")
    deep_merge(live, desired)
    sync_binary_paths(live)
    write_settings(live)
    print(f"applied {SETTINGS_PATH} -> {SETTINGS_TARGET}")


def cmd_apply_settings(_args: argparse.Namespace) -> int:
    require_declared_host()
    _ = service_stop()
    try:
        apply_settings()
    finally:
        _ = service_start()
    return 0 if wait_for_endpoint() else die("endpoint did not come back; try `doctor`")


def cmd_pair(args: argparse.Namespace) -> int:
    require_declared_host()
    port = field("exposure.tailscaleServePort")
    serve_port = ["--tailscale-serve-port", str(port)] if isinstance(port, int) else []
    return run([*ops_cli(), "pair", "--tailscale", *serve_port, *extra_args(args)])


def cmd_connect(args: argparse.Namespace) -> int:
    require_declared_host()
    return run([*ops_cli(), "connect", *extra_args(args)])


def cmd_logs(args: argparse.Namespace) -> int:
    n = str(lines_arg(args))
    if not IS_MACOS and shutil.which("journalctl"):
        print(f"=== journalctl --user -u {UNIT} ===")
        _ = subprocess.call(["journalctl", "--user", "-u", UNIT, "-n", n, "--no-pager"])
    print(f"=== {BOOT_LOG} ===")
    _ = subprocess.call(["tail", "-n", n, str(BOOT_LOG)])
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    _ = cmd_status(args)
    unit = (
        LAUNCHD_PLIST
        if IS_MACOS
        else Path.home() / ".config" / "systemd" / "user" / UNIT
    )
    print("--- unit ---")
    print(unit.read_text() if unit.exists() else f"{unit} missing")
    print("--- service-state ---")
    print(STATE_FILE.read_text() if STATE_FILE.exists() else "none")
    _ = cmd_logs(args)
    return 0


HANDLERS: dict[str, Callable[[argparse.Namespace], int]] = {
    "install": cmd_install,
    "status": cmd_status,
    "doctor": cmd_doctor,
    "restart": cmd_restart,
    "update": cmd_update,
    "apply-settings": cmd_apply_settings,
    "pair": cmd_pair,
    "connect": cmd_connect,
    "logs": cmd_logs,
}


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="t3ctl", description=(__doc__ or "t3ctl").splitlines()[0]
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name, help_text in [
        ("install", "bootstrap the service on the declared host"),
        ("status", "declared vs. live state summary"),
        ("doctor", "status plus unit, state, and recent logs"),
        ("restart", "restart the service and wait for the endpoint"),
        ("update", "install/update/repair the service on the declared channel"),
        ("apply-settings", "merge server-settings.json offline, then restart"),
        ("pair", "mint a tailnet pairing link (extra args forwarded)"),
        ("connect", "T3 Connect management (args forwarded: login/link/publish/…)"),
        ("logs", "recent service journal and boot log [-n LINES]"),
    ]:
        p = sub.add_parser(name, help=help_text)
        if name in ("pair", "connect"):
            _ = p.add_argument("rest", nargs=argparse.REMAINDER)
        if name in ("logs", "doctor"):
            _ = p.add_argument("-n", "--lines", type=int, default=30)
    args = parser.parse_args()
    cmd: object = getattr(args, "cmd", "")
    if not isinstance(cmd, str) or cmd not in HANDLERS:
        parser.error("unknown command")
    return HANDLERS[cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
