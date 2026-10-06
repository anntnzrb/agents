# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""T3 Code service management, updates, model synchronization, and operations."""

from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, cast

from sync.core.harness import SyncEnv
from sync.runtime.jsonc import is_obj_dict, is_obj_list

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

type Json = str | int | float | bool | list[Json] | dict[str, Json] | None
type JsonObject = dict[str, Json]

UNIT = "t3code.service"
LAUNCHD_LABEL = "com.t3tools.t3code.service"
ENVIRONMENT_PATH = "/.well-known/t3/environment"
CLAUDE_INSTANCE = "claudeAgent"
HTTP_OK = 200

HARNESS_WRAPPERS: dict[str, str] = {
    "pi": "pi",
    "codex": "codex",
    "claudeAgent": "claude",
}


def out(msg: str) -> None:
    """Print one message line to stdout."""
    _ = sys.stdout.write(f"{msg}\n")
    _ = sys.stdout.flush()


def err(msg: str) -> None:
    """Print one message line to stderr."""
    _ = sys.stderr.write(f"t3: {msg}\n")
    _ = sys.stderr.flush()


def load_json_object(path: Path) -> JsonObject | None:
    """Load JSON object from path, or None if missing or malformed."""
    try:
        data: object = json.loads(path.read_text(encoding="utf-8"))  # pyright: ignore[reportAny]
    except (OSError, ValueError):
        return None
    if is_obj_dict(data):
        return cast("JsonObject", data)
    return None


def load_deployment(sync_env: SyncEnv) -> JsonObject:
    """Load deployment config from the SSOT checkout."""
    path = Path(sync_env.ssot_home) / "tools" / "t3" / "deployment.json"
    data = load_json_object(path)
    return data if data is not None else {}


def channel(sync_env: SyncEnv) -> str:
    """Return configured release channel (default 'nightly')."""
    dep = load_deployment(sync_env)
    ch = dep.get("channel")
    return ch if isinstance(ch, str) and ch else "nightly"


def t3_home(sync_env: SyncEnv) -> Path:
    """Return T3 user data root."""
    return Path(os.environ.get("T3CODE_HOME") or Path(sync_env.home) / ".t3")


def state_file(sync_env: SyncEnv) -> Path:
    """Return path to T3 runtime state JSON."""
    return t3_home(sync_env) / "runtime" / "service-state.json"


def active_version(sync_env: SyncEnv) -> str | None:
    """Return version recorded in runtime service state, if installed."""
    data = load_json_object(state_file(sync_env))
    if data is None:
        return None
    version = data.get("activeVersion")
    return version if isinstance(version, str) else None


def resolved_version(sync_env: SyncEnv) -> str:
    """Return currently active version or fall back to channel head."""
    return active_version(sync_env) or channel(sync_env)


def pinned_bin(sync_env: SyncEnv) -> Path | None:
    """Return active runtime's self-contained executable."""
    version = active_version(sync_env)
    if not version:
        return None
    path = t3_home(sync_env) / "runtime" / "versions" / version / "t3"
    return path if os.access(path, os.X_OK) else None


def package_runner(version: str, *, prefer_node: bool) -> list[str]:
    """Return argv running t3 CLI at `version` from the registry."""
    order = ["npx", "bunx"] if prefer_node else ["bunx", "npx"]
    for tool in order:
        if shutil.which(tool):
            args = [tool, "-y"] if tool == "npx" else [tool]
            return [*args, f"t3@{version}"]
    msg = "no JavaScript package runner found on PATH (npx or bunx)"
    err(msg)
    raise SystemExit(1)


def ops_cli(sync_env: SyncEnv) -> list[str]:
    """Return argv running CLI version that service executes."""
    pinned = pinned_bin(sync_env)
    if pinned:
        return [str(pinned)]
    return package_runner(resolved_version(sync_env), prefer_node=True)


def install_cli(sync_env: SyncEnv) -> list[str]:
    """Return argv for service install at the channel head."""
    return package_runner(channel(sync_env), prefer_node=True)


def run_cmd(argv: Sequence[str]) -> int:
    """Echo and execute a subprocess."""
    out(f"+ {' '.join(argv)}")
    return subprocess.call(list(argv))  # noqa: S603


def live_port(sync_env: SyncEnv) -> int | None:
    """Return port the server runtime currently binds."""
    runtime_json = t3_home(sync_env) / "userdata" / "server-runtime.json"
    data = load_json_object(runtime_json)
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


def probe_endpoint(port: int, *, timeout: float = 5.0) -> int | None:
    """Query the local environment endpoint."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        conn.request("GET", ENVIRONMENT_PATH)
        return conn.getresponse().status
    except (OSError, http.client.HTTPException):
        return None
    finally:
        conn.close()


def launchd_plist(sync_env: SyncEnv) -> Path:
    """Return path to launchd plist file on macOS."""
    return Path(sync_env.home) / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"


def service_restart(sync_env: SyncEnv) -> int:
    """Restart the T3 service unit or launchd agent."""
    if sync_env.platform == "darwin":
        gui = f"gui/{os.getuid()}/{LAUNCHD_LABEL}"
        cmd_launch = ["launchctl", "kickstart", "-k", gui]
        return run_cmd(cmd_launch)
    cmd_sys = ["systemctl", "--user", "restart", UNIT]
    return run_cmd(cmd_sys)


def service_stop(sync_env: SyncEnv) -> int:
    """Stop the T3 service unit or launchd agent."""
    if sync_env.platform == "darwin":
        gui = f"gui/{os.getuid()}/{LAUNCHD_LABEL}"
        cmd_bootout = ["launchctl", "bootout", "--wait", gui]
        return subprocess.run(  # noqa: S603
            cmd_bootout,
            capture_output=True,
            text=True,
            check=False,
        ).returncode
    cmd_stop = ["systemctl", "--user", "stop", UNIT]
    return subprocess.run(  # noqa: S603
        cmd_stop,
        capture_output=True,
        text=True,
        check=False,
    ).returncode


def service_start(sync_env: SyncEnv) -> int:
    """Start the T3 service unit or launchd agent."""
    if sync_env.platform == "darwin":
        gui = f"gui/{os.getuid()}"
        plist = str(launchd_plist(sync_env))
        cmd_boot = ["launchctl", "bootstrap", gui, plist]
        return run_cmd(cmd_boot)
    cmd_start = ["systemctl", "--user", "start", UNIT]
    return run_cmd(cmd_start)


def service_enabled_active(sync_env: SyncEnv) -> tuple[str, str]:
    """Report enabled and active state of the background service."""
    if sync_env.platform == "darwin":
        enabled = "enabled" if launchd_plist(sync_env).exists() else "disabled"
        gui = f"gui/{os.getuid()}/{LAUNCHD_LABEL}"
        cmd_print = ["launchctl", "print", gui]
        loaded = (
            subprocess.run(  # noqa: S603
                cmd_print,
                capture_output=True,
                text=True,
                check=False,
            ).returncode
            == 0
        )
        return enabled, ("active" if loaded else "inactive")
    cmd_en = ["systemctl", "--user", "is-enabled", UNIT]
    res_en = subprocess.run(  # noqa: S603
        cmd_en,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    cmd_ac = ["systemctl", "--user", "is-active", UNIT]
    res_ac = subprocess.run(  # noqa: S603
        cmd_ac,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    return res_en or "unknown", res_ac or "unknown"


def wait_for_endpoint(sync_env: SyncEnv, *, timeout_s: int = 30) -> int | None:
    """Poll endpoint until it answers HTTP 200 or deadline expires."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        port = live_port(sync_env)
        if port and probe_endpoint(port, timeout=2.0) == HTTP_OK:
            return port
        time.sleep(1.0)
    return None


def channel_head(sync_env: SyncEnv) -> str:
    """Lookup latest registry version on the configured channel."""
    spec = f"t3@{channel(sync_env)}"
    cmd_view = ["npm", "view", spec, "version"]
    out_res = subprocess.run(  # noqa: S603
        cmd_view,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    version = out_res.stdout.strip()
    if out_res.returncode != 0 or not version:
        err(f"npm view {spec} failed: {out_res.stderr.strip() or 'no version'}")
        raise SystemExit(1)
    return version


def launcher_version(sync_env: SyncEnv) -> str | None:
    """Extract launcher version pinned in the service unit/plist."""
    if sync_env.platform == "darwin":
        plist = launchd_plist(sync_env)
        if not plist.exists():
            return None
        unit = plist.read_text(encoding="utf-8")
    else:
        cmd_cat = ["systemctl", "--user", "cat", UNIT]
        unit = subprocess.run(  # noqa: S603
            cmd_cat,
            capture_output=True,
            text=True,
            check=False,
        ).stdout
    match = re.search(r"/runtime/versions/([^/\s<]+)/t3", unit)
    return match.group(1) if match else None


def busy_threads(sync_env: SyncEnv) -> int:
    """Count threads with live orchestrator-v2 runs."""
    db_path = t3_home(sync_env) / "userdata" / "statev2.sqlite"
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10)
    try:
        query = (
            "SELECT count(DISTINCT thread_id) FROM orchestration_v2_projection_runs "
            "WHERE status IN ('preparing', 'starting', 'running')"
        )
        row = cast(
            "tuple[int, ...] | None",
            conn.execute(query).fetchone(),
        )
        if row is not None and len(row) > 0:
            return row[0]
        return 0
    finally:
        conn.close()


def sync_binary_paths(live: JsonObject, sync_env: SyncEnv) -> None:
    """Point harness drivers at installed sync wrappers."""
    instances = live.get("providerInstances")
    if not isinstance(instances, dict):
        return
    wrapper_dir = Path(sync_env.home) / ".local" / "bin"
    for instance_id, bin_name in HARNESS_WRAPPERS.items():
        instance = instances.get(instance_id)
        if not isinstance(instance, dict):
            continue
        wrapper = wrapper_dir / bin_name
        if not os.access(wrapper, os.X_OK):
            err(f"warning — {wrapper} missing; run sync on this host")
            continue
        config = instance.get("config")
        if not isinstance(config, dict):
            config = {}
            instance["config"] = config
        config["binaryPath"] = str(wrapper)
        out(f"{instance_id} binaryPath -> {wrapper}")


def gateway_claude_models(sync_env: SyncEnv) -> list[Json] | None:
    """Fetch gateway model catalog as Claude custom models."""
    dep_path = Path(sync_env.ssot_home) / "tools" / "cliproxyapi" / "deployment.json"
    dep = load_json_object(dep_path) or {}
    client = dep.get("client")
    base_url = client.get("baseUrl") if isinstance(client, dict) else None
    if not isinstance(base_url, str) or not base_url.startswith(
        ("http://", "https://")
    ):
        return None
    request = urllib.request.Request(  # noqa: S310
        f"{base_url.rstrip('/')}/models",
        headers={"x-api-key": "keyless", "anthropic-version": "2023-06-01"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310 # pyright: ignore[reportAny]
            body = cast("bytes", response.read())  # pyright: ignore[reportAny]
        payload: object = json.loads(body)  # pyright: ignore[reportAny]
    except (OSError, ValueError):
        return None
    if not is_obj_dict(payload):
        return None
    data = payload.get("data")
    if not is_obj_list(data):
        return None
    models: list[Json] = []
    for model in data:
        if not is_obj_dict(model) or model.get("owned_by") == "anthropic":
            continue
        slug = model.get("id")
        name = model.get("display_name")
        if isinstance(slug, str) and slug:
            entry: JsonObject = {"slug": slug}
            if isinstance(name, str) and name:
                entry["name"] = name
            models.append(entry)
    return models


def sync_claude_models(live: JsonObject, sync_env: SyncEnv) -> bool:
    """Update Claude customModels configuration from gateway catalog."""
    instances = live.get("providerInstances")
    instance = instances.get(CLAUDE_INSTANCE) if isinstance(instances, dict) else None
    if not isinstance(instance, dict) or not instance.get("enabled"):
        return False
    models = gateway_claude_models(sync_env)
    if models is None:
        err("warning — gateway catalog unreachable; Claude models unchanged")
        return False
    config = instance.setdefault("config", {})
    if not isinstance(config, dict) or config.get("customModels") == models:
        return False
    config["customModels"] = models
    out(f"{CLAUDE_INSTANCE} customModels -> {len(models)} gateway models")
    return True


def deep_merge(base: JsonObject, overlay: JsonObject) -> None:
    """Merge overlay into base dictionary in place."""
    for key, value in overlay.items():
        existing = base.get(key)
        if isinstance(value, dict) and isinstance(existing, dict):
            deep_merge(existing, value)
        else:
            base[key] = value


def write_settings(target: Path, live: JsonObject) -> None:
    """Atomically write JSON settings to target path."""
    fd, tmp = tempfile.mkstemp(dir=target.parent, suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(live, f, indent=2)
        _ = f.write("\n")
    _ = Path(tmp).replace(target)


def apply_settings(sync_env: SyncEnv) -> None:
    """Merge SSOT server-settings.json and sync harness configurations."""
    target = t3_home(sync_env) / "userdata" / "settings.json"
    if not target.parent.is_dir():
        err(f"{target.parent} missing; is the service installed?")
        raise SystemExit(1)
    settings_src = Path(sync_env.ssot_home) / "tools" / "t3" / "server-settings.json"
    desired = load_json_object(settings_src)
    live = load_json_object(target) if target.exists() else {}
    if desired is None or live is None:
        err("settings files must contain a JSON object")
        raise SystemExit(1)
    deep_merge(live, desired)
    sync_binary_paths(live, sync_env)
    _ = sync_claude_models(live, sync_env)
    write_settings(target, live)
    out(f"applied {settings_src} -> {target}")


def cmd_apply_settings(_args: argparse.Namespace, sync_env: SyncEnv) -> int:
    """Stop service, apply settings offline, and restart."""
    _ = service_stop(sync_env)
    try:
        apply_settings(sync_env)
    finally:
        _ = service_start(sync_env)
    if wait_for_endpoint(sync_env):
        return 0
    err("endpoint did not come back; try `doctor`")
    return 1


def cmd_install(args: argparse.Namespace, sync_env: SyncEnv) -> int:
    """Bootstrap the service on this host."""
    required = (
        ("launchctl",) if sync_env.platform == "darwin" else ("systemctl", "loginctl")
    )
    missing = [t for t in required if not shutil.which(t)]
    if missing:
        err(f"missing required tools: {', '.join(missing)} (need launchd or systemd)")
        return 1
    if run_cmd([*install_cli(sync_env), "service", "install"]) != 0:
        return 1
    if cmd_apply_settings(args, sync_env) != 0:
        return 1
    port = wait_for_endpoint(sync_env)
    if port:
        out(f"t3code: installed and active on http://127.0.0.1:{port}")
    else:
        out("t3code: installed; endpoint not answering yet — see `logs`")
    dep = load_deployment(sync_env)
    exposure = dep.get("exposure")
    if isinstance(exposure, dict) and exposure.get("connect"):
        out("next: `sync t3 connect login`, `connect link`, then `restart`")
    return 0


def cmd_status(_args: argparse.Namespace, sync_env: SyncEnv) -> int:
    """Print service state summary."""
    out(f"this host     : {socket.gethostname()}")
    out(f"channel       : {channel(sync_env)}")
    enabled, active = service_enabled_active(sync_env)
    out(f"unit enabled  : {enabled}")
    out(f"unit active   : {active}")
    active_str = active_version(sync_env) or "none (service never installed)"
    out(f"active version: {active_str}")
    port = live_port(sync_env)
    if port:
        code = probe_endpoint(port)
        out(f"bound port    : {port}")
        out(f"endpoint      : http://127.0.0.1:{port} -> {code or 'unreachable'}")
    else:
        out("bound port    : none (server not running)")
    out("--- tailscale serve ---")
    if shutil.which("tailscale"):
        cmd_ts = ["tailscale", "serve", "status"]
        _ = run_cmd(cmd_ts)
    else:
        out("unavailable (tailscale not installed)")
    out("--- connect ---")
    try:
        _ = run_cmd([*ops_cli(sync_env), "connect", "status"])
    except SystemExit:
        out("  (no CLI runtime available)")
    return 0


def cmd_restart(_args: argparse.Namespace, sync_env: SyncEnv) -> int:
    """Restart service and wait for endpoint."""
    _ = service_restart(sync_env)
    port = wait_for_endpoint(sync_env)
    if port:
        out(f"t3code: active on http://127.0.0.1:{port}")
        return 0
    err("service restarted but the endpoint did not answer in time; try `doctor`")
    return 1


def cmd_update(args: argparse.Namespace, sync_env: SyncEnv) -> int:
    """Reconcile service at the configured channel head."""
    rc = run_cmd([*install_cli(sync_env), "service", "install"])
    if rc == 0:
        return cmd_apply_settings(args, sync_env)
    return rc


def cmd_auto_update(args: argparse.Namespace, sync_env: SyncEnv) -> int:
    """Update only when behind channel head and no threads are active."""
    ch = channel(sync_env)
    if re.fullmatch(r"\d+\.\d+\.\d+(?:-[\w.]+)?", ch):
        out(f"t3: pinned at {ch}; automatic updates disabled")
        return 0
    if active_version(sync_env) is None:
        return cmd_install(args, sync_env)
    head = channel_head(sync_env)
    running = active_version(sync_env)
    launcher = launcher_version(sync_env)
    if running == head and launcher == head:
        out(f"t3: current at {head}")
        return 0
    try:
        busy = busy_threads(sync_env)
    except sqlite3.Error as error:
        err(f"cannot tell whether threads are running ({error}); not updating")
        return 1
    if busy:
        out(f"t3: {busy} thread(s) running; postponing {running} -> {head}")
        return 0
    out(f"t3: updating runtime {running} / launcher {launcher} -> {head}")
    return cmd_update(args, sync_env)


def cmd_refresh_models(_args: argparse.Namespace, sync_env: SyncEnv) -> int:
    """Refresh Claude gateway models live."""
    target = t3_home(sync_env) / "userdata" / "settings.json"
    live = load_json_object(target)
    if live is None:
        err(f"{target} missing or not a JSON object")
        return 1
    if sync_claude_models(live, sync_env):
        write_settings(target, live)
    return 0


def cmd_pair(args: argparse.Namespace, sync_env: SyncEnv) -> int:
    """Forward arguments to `t3 pair`."""
    rest: object = getattr(args, "rest", [])
    extra = [item for item in cast("list[object]", rest) if isinstance(item, str)]
    return run_cmd([*ops_cli(sync_env), "pair", *extra])


def cmd_connect(args: argparse.Namespace, sync_env: SyncEnv) -> int:
    """Forward arguments to `t3 connect`."""
    rest: object = getattr(args, "rest", [])
    extra = [item for item in cast("list[object]", rest) if isinstance(item, str)]
    return run_cmd([*ops_cli(sync_env), "connect", *extra])


def cmd_logs(args: argparse.Namespace, sync_env: SyncEnv) -> int:
    """Show service journal and boot log."""
    lines_val: object = getattr(args, "lines", 30)
    n = str(lines_val if isinstance(lines_val, int) else 30)
    if sync_env.platform != "darwin" and shutil.which("journalctl"):
        out(f"=== journalctl --user -u {UNIT} ===")
        cmd = ["journalctl", "--user", "-u", UNIT, "-n", n, "--no-pager"]
        _ = subprocess.call(cmd)  # noqa: S603
    boot_log = t3_home(sync_env) / "userdata" / "logs" / "boot-service.log"
    out(f"=== {boot_log} ===")
    cmd_tail = ["tail", "-n", n, str(boot_log)]
    _ = subprocess.call(cmd_tail)  # noqa: S603
    return 0


def cmd_doctor(args: argparse.Namespace, sync_env: SyncEnv) -> int:
    """Status plus unit definition, service-state, and recent logs."""
    _ = cmd_status(args, sync_env)
    unit = (
        launchd_plist(sync_env)
        if sync_env.platform == "darwin"
        else Path(sync_env.home) / ".config" / "systemd" / "user" / UNIT
    )
    out("--- unit ---")
    out(unit.read_text(encoding="utf-8") if unit.exists() else f"{unit} missing")
    out("--- service-state ---")
    state = state_file(sync_env)
    out(state.read_text(encoding="utf-8") if state.exists() else "none")
    _ = cmd_logs(args, sync_env)
    return 0


type Handler = Callable[[argparse.Namespace, SyncEnv], int]

HANDLERS: dict[str, Handler] = {
    "install": cmd_install,
    "status": cmd_status,
    "doctor": cmd_doctor,
    "restart": cmd_restart,
    "update": cmd_update,
    "auto-update": cmd_auto_update,
    "apply-settings": cmd_apply_settings,
    "refresh-models": cmd_refresh_models,
    "pair": cmd_pair,
    "connect": cmd_connect,
    "logs": cmd_logs,
}


def build_t3_parser() -> argparse.ArgumentParser:
    """Construct argument parser for t3 subcommands."""
    parser = argparse.ArgumentParser(
        prog="sync t3",
        description="Operations for the T3 Code background service.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    commands = [
        ("install", "bootstrap the service on this host"),
        ("status", "live service state summary"),
        ("doctor", "status plus unit, state, and recent logs"),
        ("restart", "restart the service and wait for the endpoint"),
        ("update", "install/update/repair the service on the configured channel"),
        ("auto-update", "update only when behind the channel and no thread runs"),
        ("apply-settings", "merge server-settings.json offline, then restart"),
        ("refresh-models", "reload Claude's model list from the gateway, live"),
        ("pair", "mint a tailnet pairing link (extra args forwarded)"),
        ("connect", "T3 Connect management (args forwarded: login/link/publish/…)"),
        ("logs", "recent service journal and boot log [-n LINES]"),
    ]
    for name, help_text in commands:
        p = sub.add_parser(name, help=help_text)
        if name in ("pair", "connect"):
            _ = p.add_argument("rest", nargs=argparse.REMAINDER)
        if name in ("logs", "doctor"):
            _ = p.add_argument("-n", "--lines", type=int, default=30)
    return parser


def run_t3(argv: Sequence[str], *, sync_env: SyncEnv | None = None) -> int:
    """Run T3 subcommand and return process exit code."""
    parser = build_t3_parser()
    try:
        args = parser.parse_args(list(argv))
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    cmd = getattr(args, "cmd", None)
    if not isinstance(cmd, str) or cmd not in HANDLERS:
        err("unknown command")
        return 2
    env = sync_env or SyncEnv.from_system()
    return HANDLERS[cmd](args, env)
