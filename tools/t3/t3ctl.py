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
import urllib.parse
from collections.abc import Callable
from pathlib import Path
from typing import NoReturn, TypeAlias, cast

Json: TypeAlias = "str | int | float | bool | None | list[Json] | dict[str, Json]"
JsonObject: TypeAlias = "dict[str, Json]"

TOOLS_DIR = Path(__file__).resolve().parent
DEPLOYMENT_PATH = TOOLS_DIR / "deployment.json"
SETTINGS_PATH = TOOLS_DIR / "server-settings.json"
CLIPROXY_DEPLOYMENT_PATH = TOOLS_DIR.parent / "cliproxyapi" / "deployment.json"
T3_HOME = Path(os.environ.get("T3CODE_HOME") or Path.home() / ".t3")
STATE_FILE = T3_HOME / "runtime" / "service-state.json"
RUNTIME_JSON = T3_HOME / "userdata" / "server-runtime.json"
SETTINGS_TARGET = T3_HOME / "userdata" / "settings.json"
BOOT_LOG = T3_HOME / "userdata" / "logs" / "boot-service.log"
UNIT = "t3code.service"
ENVIRONMENT_PATH = "/.well-known/t3/environment"

# launchd uses the same label the T3 installer writes into its plist.
IS_MACOS = sys.platform == "darwin"
LAUNCHD_LABEL = "com.t3tools.t3code.service"
LAUNCHD_PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"
MODEL_SYNC_LABEL = "dev.agents.t3-models-sync"


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
    version = active_version()
    if not version:
        return None
    path = (
        T3_HOME
        / "runtime"
        / "versions"
        / version
        / "node_modules"
        / "t3"
        / "dist"
        / "bin.mjs"
    )
    return path if path.exists() else None


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
        for rt in ("node", "bun"):
            if shutil.which(rt):
                return [rt, str(pinned)]
    return package_runner(resolved_version(), prefer_node=True)


def install_cli() -> list[str]:
    """Argv for service install/update.

    The generated unit inherits the invoking interpreter as its ExecStart
    runtime, so node is preferred for the long-running server (node-pty).
    """
    if shutil.which("npx") or shutil.which("node"):
        return package_runner(channel(), prefer_node=True)
    print(
        "t3ctl: note — installing via bunx; the service will run under bun",
        file=sys.stderr,
    )
    return package_runner(channel(), prefer_node=False)


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


MODEL_SYNC_UNITS: dict[str, str] = {
    "t3-models-sync.service": f"""\
[Unit]
Description=Refresh T3 codex customModels from the CLIProxyAPI catalog
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
ExecStart={Path(__file__).resolve()} sync-models
NoNewPrivileges=true
PrivateTmp=true
""",
    "t3-models-sync.timer": """\
[Unit]
Description=Periodic refresh of T3 codex customModels from the CLIProxyAPI catalog

[Timer]
OnCalendar=hourly
RandomizedDelaySec=10m
Persistent=true
Unit=t3-models-sync.service

[Install]
WantedBy=timers.target
""",
}


def install_model_sync_schedule() -> None:
    """Reconcile the periodic customModels refresh job so the codex picker
    tracks the gateway catalog without restarts.

    systemd user timer on Linux, launchd agent on macOS; elsewhere we warn
    and leave `sync-models` available as a manual command.
    """
    script = str(Path(__file__).resolve())
    if IS_MACOS:
        plist_dir = Path.home() / "Library" / "LaunchAgents"
        plist = plist_dir / f"{MODEL_SYNC_LABEL}.plist"
        content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>{MODEL_SYNC_LABEL}</string>
    <key>ProgramArguments</key>
    <array><string>{script}</string><string>sync-models</string></array>
    <key>StartInterval</key><integer>3600</integer>
    <key>RunAtLoad</key><true/>
</dict>
</plist>
"""
        plist_dir.mkdir(parents=True, exist_ok=True)
        if not plist.exists() or plist.read_text() != content:
            _ = plist.write_text(content)
        target = f"{gui_target()}/{MODEL_SYNC_LABEL}"
        _ = launchctl("bootout", "--wait", target)  # optional: may not be loaded
        _ = launchctl("enable", target)
        rc = launchctl("bootstrap", gui_target(), str(plist)).returncode
        if rc == 0:
            print(f"{MODEL_SYNC_LABEL} reconciled (hourly customModels refresh)")
        else:
            print(
                "t3ctl: warning — could not bootstrap the model-sync agent",
                file=sys.stderr,
            )
        return
    if not shutil.which("systemctl"):
        msg = "t3ctl: warning — no systemd or launchd; run `sync-models` manually or schedule it yourself"
        print(msg, file=sys.stderr)
        return
    unit_dir = Path.home() / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    for name, content in MODEL_SYNC_UNITS.items():
        unit = unit_dir / name
        if not unit.exists() or unit.read_text() != content:
            _ = unit.write_text(content)
    _ = run(["systemctl", "--user", "daemon-reload"])
    _ = run(["systemctl", "--user", "enable", "--now", "t3-models-sync.timer"])
    print("t3-models-sync.timer reconciled (hourly customModels refresh)")


def cmd_update(_args: argparse.Namespace) -> int:
    require_declared_host()
    rc = run([*install_cli(), "service", "update"])
    if rc == 0:
        install_model_sync_schedule()
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
    install_model_sync_schedule()
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


def fetch_json(url: str, timeout: float = 5.0) -> Json | None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None
    conn_cls = (
        http.client.HTTPSConnection
        if parsed.scheme == "https"
        else http.client.HTTPConnection
    )
    conn = conn_cls(parsed.hostname, parsed.port, timeout=timeout)
    try:
        conn.request("GET", parsed.path or "/")
        resp = conn.getresponse()
        if resp.status != 200:
            return None
        return cast(Json, json.loads(resp.read().decode()))
    except (OSError, http.client.HTTPException, json.JSONDecodeError):
        return None
    finally:
        conn.close()


def cliproxy_custom_models() -> list[Json]:
    """Live picker entries served by the repo-declared CLIProxyAPI gateway.

    Multi-segment ids stay bare slugs (the pool segment already names the
    upstream); single-segment OAuth-pool ids get a display name carrying the
    gateway-reported owner so the picker shows which pool serves them.
    Entries are ordered singles-first because the web picker caps custom
    models per instance — OAuth pools win the visible window.
    """
    deployment = load_json_object(CLIPROXY_DEPLOYMENT_PATH)
    client = deployment.get("client") if deployment else None
    base = cast(JsonObject, client).get("baseUrl") if isinstance(client, dict) else None
    if not isinstance(base, str):
        return []
    data = fetch_json(base.rstrip("/") + "/models")
    models = data.get("data") if isinstance(data, dict) else None
    if not isinstance(models, list):
        return []
    singles: list[Json] = []
    pooled: list[str] = []
    for entry in cast(list[object], models):
        if not isinstance(entry, dict):
            continue
        model_id = cast(JsonObject, entry).get("id")
        if not isinstance(model_id, str) or not model_id:
            continue
        owner = cast(JsonObject, entry).get("owned_by")
        if "/" in model_id or not isinstance(owner, str) or not owner:
            pooled.append(model_id)
        else:
            singles.append({"slug": model_id, "name": f"{model_id} ({owner})"})
    # The web picker renders at most 32 custom models per instance, first
    # settings order wins — OAuth-pool ids go first so they win the window;
    # pooled ids fill the rest and remain visible on mobile, which reads the
    # uncapped server snapshot.
    singles.sort(key=lambda e: str(cast(JsonObject, e).get("slug", "")))
    return [*singles, *sorted(pooled)]


def resolve_opencode_binary() -> str | None:
    """Resolve the real opencode binary inside the sync npm cache.

    `~/.local/bin/opencode` is a sync wrapper that routes every spawn through
    `sync launch`, adding ~3s of Python startup — enough to overrun T3's 4s
    OpenCode version probe. Pointing the driver at the cached binary directly
    keeps probes under a second. Prefers the non-baseline build.
    """
    candidates = sorted(
        Path.home().glob(
            ".cache/npm-tools/opencode/packages/*/current/node_modules/opencode-*/bin/opencode"
        )
    )
    for preferred in candidates:
        if "-baseline" not in preferred.parent.parent.name and os.access(preferred, os.X_OK):
            return str(preferred)
    for fallback in candidates:
        if os.access(fallback, os.X_OK):
            return str(fallback)
    return None


def sync_opencode_binary_path(live: JsonObject) -> None:
    """Point the OpenCode driver's binaryPath at the resolved cached binary.

    The launcher wrapper still owns user-facing launches; this only affects
    the binary T3 spawns for probes and sessions.
    """
    binary = resolve_opencode_binary()
    if binary is None:
        return
    instances = live.get("providerInstances")
    if not isinstance(instances, dict):
        return
    opencode = instances.get("opencode")
    if not isinstance(opencode, dict):
        return
    config = opencode.get("config")
    if not isinstance(config, dict):
        config = cast(JsonObject, {})
        cast(JsonObject, opencode)["config"] = config
    if config.get("binaryPath") != binary:
        cast(JsonObject, config)["binaryPath"] = binary
        print(f"opencode binaryPath -> {binary}")


def sync_codex_custom_models(live: JsonObject) -> None:
    """Refresh the Codex driver's customModels from the live gateway catalog.

    T3's Codex picker lists `codex app-server model/list` plus this setting;
    generating it at apply time keeps the tracked settings file free of a
    stale model snapshot.
    """
    instances = live.get("providerInstances")
    if not isinstance(instances, dict):
        return
    codex = instances.get("codex")
    if not isinstance(codex, dict):
        return
    _ = codex.pop("customModels", None)
    entries = cliproxy_custom_models()
    if not entries:
        print(
            "t3ctl: warning — cliproxy catalog unreachable; keeping existing customModels",
            file=sys.stderr,
        )
        return
    config = codex.get("config")
    if not isinstance(config, dict):
        config = cast(JsonObject, {})
        cast(JsonObject, codex)["config"] = config
    cast(JsonObject, config)["customModels"] = entries
    print(f"synced {len(entries)} cliproxy model ids into codex config.customModels")


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
    sync_opencode_binary_path(live)
    sync_codex_custom_models(live)
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


def cmd_sync_models(_args: argparse.Namespace) -> int:
    """Refresh codex customModels while the service runs.

    The server watches settings.json and publishes the change to clients, so
    the model picker repopulates without a restart.
    """
    require_declared_host()
    live = load_json_object(SETTINGS_TARGET)
    if live is None:
        die(f"{SETTINGS_TARGET} missing or unreadable; is the service installed?")
    sync_opencode_binary_path(live)
    sync_codex_custom_models(live)
    write_settings(live)
    return 0


def cmd_pair(args: argparse.Namespace) -> int:
    require_declared_host()
    return run([*ops_cli(), "pair", "--tailscale", *extra_args(args)])


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
    "sync-models": cmd_sync_models,
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
        ("sync-models", "refresh codex customModels from the live gateway catalog"),
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
