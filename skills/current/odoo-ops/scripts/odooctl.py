#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Autonomous Odoo 17 stack controller, test runner, linter/formatter, and PostgreSQL inspector."""

from __future__ import annotations

import argparse
import ast
import configparser
import csv
import io
import json
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

# ==============================================================================
# CONFIGURATION CONSTANTS & DEFAULTS
# ==============================================================================

# Script Directories
SCRIPT_DIR = Path(__file__).resolve().parent
SQL_DIR = SCRIPT_DIR / "sql"
PROFILE_DIR = SCRIPT_DIR.parent / "profiles"
CONFIG_DIR = SCRIPT_DIR.parent / "config"
RUFF_CONFIG_PATH = CONFIG_DIR / "ruff.toml"

# Network & Ports (Cero Magic Numbers)
DEFAULT_HTTP_PORT = int(os.environ.get("ODOO_HTTP_PORT", "8069"))
DEFAULT_DB_PORT = int(os.environ.get("ODOO_DB_PORT", "5432"))
DEFAULT_HOST_BIND_IP = os.environ.get("ODOO_BIND_IP", "127.0.0.1")

# Container Runtime & Names (Cero Magic Strings)
PODMAN_BIN = os.environ.get("PODMAN_BIN", "podman")
POD_NAME = os.environ.get("ODOO_POD_NAME", "odoo-pod")
DB_CONTAINER_NAME = os.environ.get("ODOO_DB_CONTAINER", "odoo-db")
WEB_CONTAINER_NAME = os.environ.get("ODOO_WEB_CONTAINER", "odoo-web")
TEST_CONTAINER_NAME = os.environ.get("ODOO_TEST_CONTAINER", "odoo-test")

# Container Images
ODOO_IMAGE = os.environ.get("ODOO_IMAGE", "localhost/odoo17-local:17.0-e-20260527")
POSTGRES_IMAGE = os.environ.get("POSTGRES_IMAGE", "docker.io/library/postgres:15")

# Container In-Guest Mount Targets
CONTAINER_MOUNT_WEB_DATA = "/var/lib/odoo"
CONTAINER_MOUNT_CONFIG = "/etc/odoo"
CONTAINER_MOUNT_SOURCE = "/mnt/odoo-src"
CONTAINER_MOUNT_CUSTOM_ADDONS = "/mnt/custom-addons"
CONTAINER_MOUNT_PGDATA = "/var/lib/postgresql/data/pgdata"

# Database Configuration Defaults
DEFAULT_DB_NAME = os.environ.get("ODOO_DEFAULT_DB", "erptech_0817-crm")
DEFAULT_DB_USER = os.environ.get("ODOO_DB_USER", "odoo")
DEFAULT_DB_PASSWORD = os.environ.get("ODOO_DB_PASSWORD", "odoo")
DEFAULT_POSTGRES_DB = os.environ.get("POSTGRES_DEFAULT_DB", "postgres")

# Profile & Discovery Defaults
DEFAULT_PROFILE_NAME = os.environ.get("ODOO_DEFAULT_PROFILE", "etech")
DEFAULT_TABLE_LIMIT = 20
DB_STARTUP_WAIT_SECONDS = 1.5

# Host Directory Defaults
DEFAULT_RUNTIME_ROOT = Path(os.environ.get("ODOO_RUNTIME_DIR", "/opt/odoo17"))
DEFAULT_ADDONS_RELATIVE_PATH = Path("repos/etech/odoo")
FALLBACK_XDG_RUNTIME_ROOT = Path.home() / ".local/share/odoo17"

# Odoo Engine Hot-Reload Flags
DEV_MODE_FLAGS = "--dev=reload,xml,qweb,werkzeug"
ODOO_CONFIG_SUBPATH = Path("config/odoo.conf")
ODOO_SOURCE_SUBPATH = Path("source")
ODOO_DATA_WEB_SUBPATH = Path("data/web")
ODOO_DATA_DB_SUBPATH = Path("data/db")
ODOO_PROFILES_SUBPATH = Path("profiles")
SOURCE_ADDONS_GLOB = "odoo-*/odoo/addons"

# Security & AST Redaction
SECRET_TOKENS = ("passwd", "password", "token", "secret", "key")
WRITE_HINTS = {
    "create", "write", "unlink", "commit", "rollback",
    "execute", "save", "update", "delete", "insert",
    "patch", "post", "put",
}

MUTATING_SQL_RE = re.compile(
    r"\b("
    r"insert|update|delete|merge|upsert|alter|drop|create|grant|revoke|truncate|"
    r"comment|vacuum|analyze|reindex|cluster|refresh|copy\s+[^;]*\s+from|"
    r"call|do|lock|checkpoint|discard|savepoint|release\s+savepoint|"
    r"rollback|commit|set\s+transaction|set\s+session|listen|notify|unlisten"
    r")\b",
    re.IGNORECASE | re.DOTALL,
)

# String prefixes to silently drop (stack traces, importlib warnings)
DROPPED_PREFIXES = (
    "File \"",
    "main(",
    "o.run(",
    "rc =",
    "registry =",
    "processed_modules",
    "loaded, processed",
    "load_openerp_module",
    "return func(",
    "DeprecationWarning",
    "sys:1: DeprecationWarning",
    "exec(code",
    "__import__(",
    "return _run_code",
)

# Noise Patterns to Filter Out of Console Stream
IGNORE_LOG_PATTERNS = [
    re.compile(r"builtin type (SwigPyPacked|SwigPyObject|swigvarlink) has no __module__ attribute"),
    re.compile(r"Missing `license` key in manifest"),
    re.compile(r"The model .* is not overriding the create method in batch"),
    re.compile(r"overrides existing selection; use selection_add instead"),
    re.compile(r"unknown parameter 'tracking', if this is an actual parameter"),
    re.compile(r"filestore gc"),
    re.compile(r"ConnectionPool.*Closed"),
    re.compile(r"Initiating shutdown"),
    re.compile(r"Hit CTRL-C again"),
    re.compile(r"psycopg2\.InterfaceError: connection already closed"),
    re.compile(r"Exception in thread odoo\.service\.cron"),
]

ODOO_LOG_REGEX = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})\s+(?P<time>\d{2}:\d{2}:\d{2}),\d+\s+(?P<pid>\d+)\s+(?P<level>INFO|WARNING|ERROR|CRITICAL|DEBUG)\s+(?P<db>\S+)?\s+(?P<logger>[^:]+):\s+(?P<msg>.*)$"
)

HTTP_LOG_REGEX = re.compile(
    r'^(?P<ip>[\d\.]+)\s+-\s+-\s+\[[^\]]+\]\s+"(?P<method>GET|POST|PUT|DELETE|OPTIONS|HEAD)\s+(?P<path>[^\s]+)\s+HTTP/[^"]+"\s+(?P<status>\d{3})\s+(?P<rest>.*)$'
)


# ==============================================================================
# ANSI TERMINAL STYLING & NOISE FILTER
# ==============================================================================

class Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    UNDERLINE = "\033[4m"
    
    BLACK = "\033[30m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"

    BG_BLUE = "\033[44m"
    BG_MAGENTA = "\033[45m"
    BG_GREEN = "\033[42m"
    BG_RED = "\033[41m"
    BG_YELLOW = "\033[43m"
    BG_DARK = "\033[100m"

    _FORCE_PRETTY = False

    @classmethod
    def is_enabled(cls) -> bool:
        if cls._FORCE_PRETTY:
            return True
        return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None

    @classmethod
    def set_pretty(cls, pretty: bool) -> None:
        cls._FORCE_PRETTY = pretty

    @classmethod
    def style(cls, text: str, *styles: str) -> str:
        if not cls.is_enabled():
            return text
        prefix = "".join(styles)
        return f"{prefix}{text}{cls.RESET}"


def log_header(title: str, subtitle: str = "", color: str = Colors.CYAN) -> None:
    if not Colors.is_enabled():
        print(f"=== {title} ===")
        if subtitle:
            print(f"({subtitle})")
        return
    bar = "═" * 72
    print(f"\n{color}{Colors.BOLD}╔{bar}╗{Colors.RESET}")
    print(f"{color}{Colors.BOLD}║  {title:<68}  ║{Colors.RESET}")
    if subtitle:
        print(f"{color}{Colors.DIM}║  {subtitle:<68}  ║{Colors.RESET}")
    print(f"{color}{Colors.BOLD}╚{bar}╝{Colors.RESET}\n")


def log_field(badge: str, label: str, value: str, badge_color: str = Colors.CYAN) -> None:
    if not Colors.is_enabled():
        print(f"[{badge}] {label}: {value}")
        return
    badge_str = Colors.style(f" {badge} ", Colors.BOLD, Colors.WHITE, badge_color)
    label_str = Colors.style(f"{label:<14}", Colors.BOLD)
    print(f"{badge_str} {label_str} {value}")


def log_success(badge: str, message: str) -> None:
    if not Colors.is_enabled():
        print(f"[{badge}] {message}")
        return
    badge_str = Colors.style(f" {badge} ", Colors.BOLD, Colors.WHITE, Colors.BG_GREEN)
    print(f"{badge_str} {Colors.style(message, Colors.BOLD, Colors.GREEN)}")


def log_warn(badge: str, message: str) -> None:
    badge_str = Colors.style(f" {badge} ", Colors.BOLD, Colors.BLACK, Colors.BG_YELLOW)
    print(f"{badge_str} {Colors.style(message, Colors.YELLOW)}")


def log_error(badge: str, message: str) -> None:
    badge_str = Colors.style(f" {badge} ", Colors.BOLD, Colors.WHITE, Colors.BG_RED)
    print(f"{badge_str} {Colors.style(message, Colors.BOLD, Colors.RED)}", file=sys.stderr)


def format_log_line(line: str, pretty: bool = False) -> str | None:
    line_clean = line.strip()
    if not line_clean:
        return None

    # Filter spam / noise
    for prefix in DROPPED_PREFIXES:
        if line_clean.startswith(prefix):
            return None

    for pat in IGNORE_LOG_PATTERNS:
        if pat.search(line_clean):
            return None

    # In RAW mode (for agents), return clean noise-free log line directly
    if not pretty and not Colors.is_enabled():
        return line_clean

    # 1. Match Standard Odoo Log Line
    m = ODOO_LOG_REGEX.match(line_clean)
    if m:
        time_str = Colors.style(f"[{m.group('time')}]", Colors.DIM)
        level = m.group("level")
        logger = m.group("logger")
        msg = m.group("msg")

        # Color-code level badge
        if level == "INFO":
            lvl_badge = Colors.style(" INFO ", Colors.BOLD, Colors.WHITE, Colors.BG_BLUE)
        elif level == "WARNING":
            lvl_badge = Colors.style(" WARN ", Colors.BOLD, Colors.BLACK, Colors.BG_YELLOW)
        elif level in ("ERROR", "CRITICAL"):
            lvl_badge = Colors.style(" FAIL ", Colors.BOLD, Colors.WHITE, Colors.BG_RED)
        else:
            lvl_badge = Colors.style(f" {level} ", Colors.DIM)

        logger_name = logger.split(".")[-1]
        logger_str = Colors.style(f"[{logger_name:<12}]", Colors.DIM)

        # Highlight important milestones
        if "HTTP service (werkzeug) running on" in msg:
            msg = Colors.style(f"🚀 {msg}", Colors.BOLD, Colors.GREEN)
        elif "AutoReload watcher running" in msg:
            msg = Colors.style(f"🔥 {msg}", Colors.BOLD, Colors.CYAN)
        elif "Registry loaded in" in msg:
            msg = Colors.style(f"✨ {msg}", Colors.BOLD, Colors.GREEN)
        elif "0 failed, 0 error(s)" in msg:
            return f"\n{Colors.style('  🏆 100% GREEN PASS  ', Colors.BOLD, Colors.WHITE, Colors.BG_GREEN)} {Colors.style(msg, Colors.BOLD, Colors.GREEN)}\n"
        elif "Loading module" in msg:
            mod_name = msg.replace("Loading module ", "")
            msg = f"Loading module {Colors.style(mod_name, Colors.BOLD, Colors.CYAN)}"
        elif "Starting Test" in msg:
            return None
        elif "failed" in msg or "error" in msg.lower():
            if level in ("ERROR", "CRITICAL", "WARNING"):
                msg = Colors.style(msg, Colors.BOLD, Colors.RED)

        return f"{time_str} {lvl_badge} {logger_str} {msg}"

    # 2. Match HTTP Access Logs
    hm = HTTP_LOG_REGEX.match(line_clean)
    if hm:
        method = hm.group("method")
        path = hm.group("path")
        status = int(hm.group("status"))
        rest = hm.group("rest")

        method_str = Colors.style(f" {method:<4} ", Colors.BOLD, Colors.WHITE, Colors.BG_BLUE)
        path_str = Colors.style(path, Colors.BOLD)

        if 200 <= status < 300:
            status_str = Colors.style(f" {status} OK ", Colors.BOLD, Colors.WHITE, Colors.BG_GREEN)
        elif 300 <= status < 400:
            status_str = Colors.style(f" {status} ", Colors.BOLD, Colors.BLACK, Colors.BG_YELLOW)
        else:
            status_str = Colors.style(f" {status} ERROR ", Colors.BOLD, Colors.WHITE, Colors.BG_RED)

        return f"               {method_str} {status_str} {path_str} {Colors.style(rest, Colors.DIM)}"

    # 3. Test Progress Highlights
    if "Starting " in line_clean and " ... " in line_clean:
        test_name = line_clean.split("Starting ")[-1].replace(" ...", "")
        return Colors.style(f"   ▶ {test_name}", Colors.DIM, Colors.CYAN)

    if line_clean.startswith("ERROR:") or line_clean.startswith("FAIL:"):
        return Colors.style(f"❌ {line_clean}", Colors.BOLD, Colors.RED)

    return line_clean


def stream_process_output(cmd: list[str], pretty: bool = False) -> int:
    """Streams and filters command stdout/stderr line-by-line with real-time coloring in pretty mode."""
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    try:
        if proc.stdout:
            for raw_line in iter(proc.stdout.readline, ""):
                formatted = format_log_line(raw_line, pretty=pretty)
                if formatted:
                    print(formatted, flush=True)
        return proc.wait()
    except KeyboardInterrupt:
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            proc.kill()
        return 0


# ==============================================================================
# DISCOVERY HELPERS
# ==============================================================================

def _resolve_runtime() -> Path:
    if "ODOO_RUNTIME_DIR" in os.environ:
        return Path(os.environ["ODOO_RUNTIME_DIR"]).resolve()
    for candidate in (DEFAULT_RUNTIME_ROOT, FALLBACK_XDG_RUNTIME_ROOT):
        if candidate.is_dir():
            return candidate
    return DEFAULT_RUNTIME_ROOT


def _resolve_addons() -> Path:
    if "ODOO_ADDONS_DIR" in os.environ:
        return Path(os.environ["ODOO_ADDONS_DIR"]).resolve()
    
    cwd = Path.cwd().resolve()
    if (cwd / "crm_espol").is_dir() or any(cwd.glob("*/__manifest__.py")):
        return cwd
        
    candidate = Path.home() / DEFAULT_ADDONS_RELATIVE_PATH
    if candidate.is_dir():
        return candidate
    return cwd


def _resolve_source_dir(runtime_root: Path) -> Path:
    source_root = runtime_root / ODOO_SOURCE_SUBPATH
    if source_root.is_dir():
        for d in sorted(source_root.glob("odoo-*")):
            if d.is_dir():
                return d
    return source_root


def _resolve_target_paths(ctx: WorkspaceContext, target: str, profile_name: str = DEFAULT_PROFILE_NAME, for_lint: bool = False) -> tuple[list[Path], list[str]]:
    """Resolves directory paths for a workflow name or single module name."""
    try:
        profile = _load_workflow_profile(profile_name, target)
        if for_lint:
            module_names = list(profile.lint_modules)
        else:
            module_names = list(profile.modules)
    except CliError:
        module_names = [target]

    paths: list[Path] = []
    for mod in module_names:
        mod_path = ctx.root / mod
        if mod_path.is_dir():
            paths.append(mod_path)
    return paths, module_names


# ==============================================================================
# DATA STRUCTURES & EXCEPTIONS
# ==============================================================================

class CliError(RuntimeError):
    """Raised for actionable command failures."""


@dataclass(frozen=True)
class RuntimeContext:
    backend: str
    root: Path
    config_path: Path
    config: dict[str, str]
    addons_paths: list[Path]
    source_path: Path


@dataclass(frozen=True)
class WorkspaceContext:
    root: Path
    config_path: Path
    config: dict[str, str]
    addons_paths: list[Path]
    effective_db_name: str
    runtime: RuntimeContext


@dataclass(frozen=True, slots=True)
class WorkflowProfile:
    profile: str
    workflow: str
    database: str
    modules: tuple[str, ...]
    test_modules: tuple[str, ...]
    lint_modules: tuple[str, ...]


@dataclass(frozen=True)
class RouteRecord:
    file: str
    class_name: str
    method_name: str
    routes: list[str]
    auth: str | None
    methods: list[str]
    write_signals: list[str]


# ==============================================================================
# UTILITY FUNCTIONS
# ==============================================================================

def _redact_mapping(data: dict[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, value in data.items():
        if any(token in key.lower() for token in SECRET_TOKENS):
            redacted[key] = "<redacted>"
        else:
            redacted[key] = value
    return redacted


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    raise TypeError(f"cannot JSON encode {type(value)!r}")


def _emit_result(args: argparse.Namespace, payload: dict[str, Any]) -> int:
    print(json.dumps(payload, default=_json_default, indent=2))
    return 0


def _fail(args: argparse.Namespace, message: str, checked: list[str] | None = None) -> int:
    if getattr(args, "json", False):
        payload = {"error": message}
        if checked:
            payload["checked"] = checked
        print(json.dumps(payload, indent=2), file=sys.stderr)
    else:
        log_error("ERROR", message)
        if checked:
            for item in checked:
                print(f"   ↳ {item}", file=sys.stderr)
    return 1


def _read_config(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(path, encoding="utf-8")
    if "options" in parser:
        return dict(parser["options"].items())
    return {}


def load_workspace(args: argparse.Namespace | None = None) -> WorkspaceContext:
    root = Path(getattr(args, "root", None) or _resolve_addons()).resolve()
    runtime_root = Path(getattr(args, "runtime_dir", None) or _resolve_runtime()).resolve()
    config_path = runtime_root / ODOO_CONFIG_SUBPATH
    source_dir = _resolve_source_dir(runtime_root)
    
    config = _read_config(config_path) if config_path.is_file() else {}
    
    addons_paths = [root]
    for p in source_dir.glob(SOURCE_ADDONS_GLOB):
        if p.is_dir():
            addons_paths.append(p)
            
    raw_db = getattr(args, "db", None) or config.get("db_name")
    if raw_db in ("False", "None", "", None):
        raw_db = DEFAULT_DB_NAME

    runtime = RuntimeContext(
        backend="podman",
        root=runtime_root,
        config_path=config_path,
        config=config,
        addons_paths=addons_paths,
        source_path=source_dir,
    )

    return WorkspaceContext(
        root=root,
        config_path=config_path,
        config=config,
        addons_paths=addons_paths,
        effective_db_name=raw_db,
        runtime=runtime,
    )


def _load_workflow_profile(profile: str, workflow: str) -> WorkflowProfile:
    pfile = PROFILE_DIR / f"{profile}.json"
    if not pfile.is_file():
        alt = _resolve_runtime() / ODOO_PROFILES_SUBPATH / f"{profile}.json"
        if alt.is_file():
            pfile = alt
        else:
            raise CliError(f"workflow profile not found: {pfile}")
    
    data = json.loads(pfile.read_text(encoding="utf-8"))
    wf = data.get("workflows", {}).get(workflow)
    if not wf:
        available = list(data.get("workflows", {}).keys())
        raise CliError(f"workflow {workflow!r} not found in profile {profile!r}. Available workflows: {available}")
    
    db = wf.get("database")
    if not db or db == "False":
        db = DEFAULT_DB_NAME

    mods = list(wf.get("modules", []))
    for dep in ("admin_units", "contact_extension"):
        if dep not in mods and (_resolve_addons() / dep).is_dir():
            mods.append(dep)

    lint_mods = wf.get("lint_modules", wf.get("test_modules", wf.get("modules", [])))

    return WorkflowProfile(
        profile=profile,
        workflow=workflow,
        database=db,
        modules=tuple(mods),
        test_modules=tuple(wf.get("test_modules", wf.get("modules", []))),
        lint_modules=tuple(lint_mods),
    )


# ==============================================================================
# CONTAINER LIFECYCLE HELPERS
# ==============================================================================

def _ensure_podman_pod() -> None:
    proc = subprocess.run([PODMAN_BIN, "pod", "exists", POD_NAME])
    if proc.returncode != 0:
        subprocess.run([
            PODMAN_BIN, "pod", "create",
            "--name", POD_NAME,
            "-p", f"{DEFAULT_HTTP_PORT}:{DEFAULT_HTTP_PORT}",
            "-p", f"{DEFAULT_HOST_BIND_IP}:{DEFAULT_DB_PORT}:{DEFAULT_DB_PORT}",
        ], check=True)


def _ensure_db_container(ctx: WorkspaceContext) -> None:
    _ensure_podman_pod()
    proc = subprocess.run([PODMAN_BIN, "container", "exists", DB_CONTAINER_NAME])
    if proc.returncode != 0:
        db_data = ctx.runtime.root / ODOO_DATA_DB_SUBPATH
        db_data.mkdir(parents=True, exist_ok=True)
        subprocess.run([
            PODMAN_BIN, "run", "-d",
            "--name", DB_CONTAINER_NAME,
            "--pod", POD_NAME,
            "-v", f"{db_data}:{CONTAINER_MOUNT_PGDATA}:Z",
            "-e", f"POSTGRES_DB={DEFAULT_POSTGRES_DB}",
            "-e", f"POSTGRES_USER={DEFAULT_DB_USER}",
            "-e", f"POSTGRES_PASSWORD={DEFAULT_DB_PASSWORD}",
            "-e", f"PGDATA={CONTAINER_MOUNT_PGDATA}",
            POSTGRES_IMAGE,
        ], check=True)
        time.sleep(DB_STARTUP_WAIT_SECONDS)


# ==============================================================================
# LINTER & FORMATTER GATE HELPERS
# ==============================================================================

def _run_ruff_check(paths: list[Path], *, fix: bool = False, pretty: bool = False) -> int:
    cmd = ["uvx", "ruff", "check"]
    if fix:
        cmd.append("--fix")
    if RUFF_CONFIG_PATH.is_file():
        cmd.extend(["--config", str(RUFF_CONFIG_PATH)])
    cmd.extend(str(p) for p in paths)
    return subprocess.call(cmd)


def _run_ruff_format(paths: list[Path], *, check: bool = False, pretty: bool = False) -> int:
    cmd = ["uvx", "ruff", "format"]
    if check:
        cmd.append("--check")
    if RUFF_CONFIG_PATH.is_file():
        cmd.extend(["--config", str(RUFF_CONFIG_PATH)])
    cmd.extend(str(p) for p in paths)
    return subprocess.call(cmd)


def cmd_lint(args: argparse.Namespace) -> int:
    """Linter: runs ruff check against explicit lint_modules."""
    if not args.target:
        raise CliError("explicit target (workflow or module name) is required for lint (e.g. 'cli.py lint crm' or 'cli.py lint url_shortener')")

    pretty = getattr(args, "pretty", False)
    if pretty:
        Colors.set_pretty(True)

    ctx = load_workspace(args)
    profile_name = getattr(args, "profile", DEFAULT_PROFILE_NAME) or DEFAULT_PROFILE_NAME
    paths, mod_names = _resolve_target_paths(ctx, args.target, profile_name, for_lint=True)

    if not paths:
        raise CliError(f"no valid module directories found on disk for target {args.target!r}")

    if pretty:
        log_header("🔍 RUFF LINTER GATE", f"Target: {args.target} ({len(paths)} lint modules)", Colors.YELLOW)
        log_field("MODULES ", "Inspecting", ", ".join(mod_names), Colors.BG_YELLOW)
        log_field("CONFIG  ", "Ruff TOML", str(RUFF_CONFIG_PATH), Colors.BG_YELLOW)
        print()
    else:
        print(f"Linting modules: {', '.join(mod_names)}")

    ret = _run_ruff_check(paths, fix=getattr(args, "fix", False), pretty=pretty)
    if pretty:
        if ret == 0:
            log_success("PASS", "Zero lint violations detected across lint_modules.")
        else:
            log_error("LINT ERROR", f"Lint check exited with code: {ret}")
    return ret


def cmd_fmt(args: argparse.Namespace) -> int:
    """Formatter: runs ruff format against explicit lint_modules."""
    if not args.target:
        raise CliError("explicit target (workflow or module name) is required for fmt (e.g. 'cli.py fmt crm' or 'cli.py fmt url_shortener')")

    pretty = getattr(args, "pretty", False)
    if pretty:
        Colors.set_pretty(True)

    ctx = load_workspace(args)
    profile_name = getattr(args, "profile", DEFAULT_PROFILE_NAME) or DEFAULT_PROFILE_NAME
    paths, mod_names = _resolve_target_paths(ctx, args.target, profile_name, for_lint=True)

    if not paths:
        raise CliError(f"no valid module directories found on disk for target {args.target!r}")

    is_check = getattr(args, "check", False)

    if pretty:
        log_header("🎨 RUFF FORMATTER GATE", f"Target: {args.target} ({'Check only' if is_check else 'Auto-format'})", Colors.CYAN)
        log_field("MODULES ", "Inspecting", ", ".join(mod_names), Colors.BG_BLUE)
        log_field("CONFIG  ", "Ruff TOML", str(RUFF_CONFIG_PATH), Colors.BG_BLUE)
        print()
    else:
        print(f"Formatting modules: {', '.join(mod_names)} (check={is_check})")

    ret = _run_ruff_format(paths, check=is_check, pretty=pretty)
    if pretty:
        if ret == 0:
            log_success("FORMAT", "All files in lint_modules formatted cleanly.")
        else:
            log_warn("UNFORMATTED", f"Formatting check failed with code: {ret}")
    return ret


# ==============================================================================
# EXPLICIT RUNNERS
# ==============================================================================

def cmd_dev(args: argparse.Namespace) -> int:
    """Dev runner: starts DB in background and runs Odoo synchronously in FOREGROUND with hot-reloading (Ctrl-C to stop)."""
    if not args.workflow:
        raise CliError("explicit workflow argument is required for dev (e.g. 'cli.py dev crm')")
        
    pretty = getattr(args, "pretty", False)
    if pretty:
        Colors.set_pretty(True)

    ctx = load_workspace(args)
    profile_name = getattr(args, "profile", DEFAULT_PROFILE_NAME) or DEFAULT_PROFILE_NAME
    profile = _load_workflow_profile(profile_name, args.workflow)
    target_db = profile.database

    if pretty:
        log_header("⚡ ODOO 17 DEVELOPMENT RUNNER", "Synchronous foreground engine with instant hot-reloading", Colors.CYAN)
        log_field("PROFILE ", "Workflow Config", f"{Colors.style(profile_name, Colors.BOLD, Colors.YELLOW)} ➔ {Colors.style(args.workflow, Colors.BOLD, Colors.MAGENTA)}", Colors.BG_BLUE)
        log_field("DATABASE", "Active DB Target", Colors.style(target_db, Colors.BOLD, Colors.GREEN), Colors.BG_BLUE)
        log_field("WORKSPACE", "Custom Addons", Colors.style(str(ctx.root), Colors.UNDERLINE, Colors.WHITE), Colors.BG_BLUE)
        log_field("ENDPOINT", "Web URL", Colors.style(f"http://{DEFAULT_HOST_BIND_IP}:{DEFAULT_HTTP_PORT}/web/login?db={target_db}", Colors.BOLD, Colors.UNDERLINE, Colors.CYAN), Colors.BG_BLUE)
        print()
        log_warn("RELOAD", "Hot-reload active: Python edits reload on save; XML views update on browser refresh.")
        log_warn("ATTACH", f"Streaming container logs live below. Press {Colors.style('Ctrl-C', Colors.BOLD, Colors.RED)} to gracefully stop.")
        print(Colors.style("─" * 74 + "\n", Colors.DIM))
    else:
        print(f"Launching dev server: profile={profile_name} workflow={args.workflow} db={target_db} addons={ctx.root}")

    # 1. Ensure DB container is running
    _ensure_db_container(ctx)

    # 2. Clean up previous web or test containers
    subprocess.run([PODMAN_BIN, "rm", "-f", WEB_CONTAINER_NAME, TEST_CONTAINER_NAME], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # 3. Start odoo-web container in the FOREGROUND (synchronous) with real-time log stream formatting
    web_data = ctx.runtime.root / ODOO_DATA_WEB_SUBPATH
    web_data.mkdir(parents=True, exist_ok=True)
    config_dir = ctx.runtime.root / "config"
    source_dir = ctx.runtime.source_path
    addons_dir = ctx.root

    dev_cmd = [
        PODMAN_BIN, "run", "--rm",
        "--name", WEB_CONTAINER_NAME,
        "--pod", POD_NAME,
        "-v", f"{web_data}:{CONTAINER_MOUNT_WEB_DATA}:Z",
        "-v", f"{config_dir}:{CONTAINER_MOUNT_CONFIG}:Z",
        "-v", f"{source_dir}:{CONTAINER_MOUNT_SOURCE}:Z",
        "-v", f"{addons_dir}:{CONTAINER_MOUNT_CUSTOM_ADDONS}:Z",
        "-e", f"PYTHONPATH={CONTAINER_MOUNT_SOURCE}",
        "-e", "PYTHONWARNINGS=ignore::DeprecationWarning",
        "-w", CONTAINER_MOUNT_SOURCE,
        ODOO_IMAGE,
        "python3", "-m", "odoo", "-c", f"{CONTAINER_MOUNT_CONFIG}/odoo.conf",
        "-d", target_db,
        DEV_MODE_FLAGS,
    ]

    try:
        return stream_process_output(dev_cmd, pretty=pretty)
    except KeyboardInterrupt:
        print()
        log_warn("SHUTDOWN", "Dev server received Ctrl-C. Initiating graceful container teardown...")
        return 0
    finally:
        subprocess.run([PODMAN_BIN, "stop", "-t", "2", WEB_CONTAINER_NAME], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run([PODMAN_BIN, "rm", "-f", WEB_CONTAINER_NAME], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log_success("CLEAN", "Odoo dev container terminated and resources released.")


def cmd_test(args: argparse.Namespace) -> int:
    """Test runner: executes isolated headless test gauntlet directly (zero lint blocking)."""
    if not args.target:
        raise CliError("explicit target (workflow or module name) is required for test (e.g. 'cli.py test crm' or 'cli.py test url_shortener')")

    pretty = getattr(args, "pretty", False)
    if pretty:
        Colors.set_pretty(True)

    ctx = load_workspace(args)
    profile_name = getattr(args, "profile", DEFAULT_PROFILE_NAME) or DEFAULT_PROFILE_NAME

    try:
        profile = _load_workflow_profile(profile_name, args.target)
        target_db = profile.database
        modules = ",".join(profile.modules)
        test_tags = ",".join(f"/{m}" for m in profile.test_modules)
        is_workflow = True
    except CliError:
        target_db = getattr(args, "db", None) or ctx.effective_db_name or DEFAULT_DB_NAME
        modules = args.target
        test_tags = f"/{args.target}"
        is_workflow = False

    # Launch Odoo Test Gauntlet directly
    if pretty:
        log_header("🧪 ODOO 17 HEADLESS TEST RUNNER", "Isolated disposable container execution", Colors.MAGENTA)
        if is_workflow:
            log_field("WORKFLOW", "Profile Target", f"{Colors.style(profile_name, Colors.BOLD, Colors.YELLOW)} ➔ {Colors.style(args.target, Colors.BOLD, Colors.MAGENTA)}", Colors.BG_MAGENTA)
        else:
            log_field("MODULE  ", "Single Module", Colors.style(args.target, Colors.BOLD, Colors.YELLOW), Colors.BG_MAGENTA)
            
        log_field("DATABASE", "Target Database", Colors.style(target_db, Colors.BOLD, Colors.GREEN), Colors.BG_MAGENTA)
        log_field("MODULES ", "Upgrade Suite", Colors.style(modules, Colors.CYAN), Colors.BG_MAGENTA)
        log_field("TAGS    ", "Test Filter", Colors.style(test_tags, Colors.YELLOW), Colors.BG_MAGENTA)
        log_field("WORKSPACE", "Custom Addons", Colors.style(str(ctx.root), Colors.UNDERLINE, Colors.WHITE), Colors.BG_MAGENTA)
        print(Colors.style("─" * 74 + "\n", Colors.DIM))
    else:
        print(f"Running tests: target={args.target} db={target_db} modules={modules} tags={test_tags} addons={ctx.root}")

    _ensure_db_container(ctx)

    # Clean up any lingering container before test run
    subprocess.run([PODMAN_BIN, "rm", "-f", TEST_CONTAINER_NAME, WEB_CONTAINER_NAME], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    web_data = ctx.runtime.root / ODOO_DATA_WEB_SUBPATH
    config_dir = ctx.runtime.root / "config"
    source_dir = ctx.runtime.source_path
    addons_dir = ctx.root

    test_cmd = [
        PODMAN_BIN, "run", "--rm",
        "--name", TEST_CONTAINER_NAME,
        "--pod", POD_NAME,
        "-v", f"{web_data}:{CONTAINER_MOUNT_WEB_DATA}:Z",
        "-v", f"{config_dir}:{CONTAINER_MOUNT_CONFIG}:Z",
        "-v", f"{source_dir}:{CONTAINER_MOUNT_SOURCE}:Z",
        "-v", f"{addons_dir}:{CONTAINER_MOUNT_CUSTOM_ADDONS}:Z",
        "-e", f"PYTHONPATH={CONTAINER_MOUNT_SOURCE}",
        "-e", "PYTHONWARNINGS=ignore::DeprecationWarning",
        "-w", CONTAINER_MOUNT_SOURCE,
        ODOO_IMAGE,
        "python3", "-m", "odoo", "-c", f"{CONTAINER_MOUNT_CONFIG}/odoo.conf",
        "-d", target_db,
        "-u", modules,
        "--test-tags", test_tags,
        "--stop-after-init",
    ]

    try:
        ret = stream_process_output(test_cmd, pretty=pretty)
        if pretty:
            print(Colors.style("\n" + "─" * 74, Colors.DIM))
            if ret == 0:
                log_success("COMPLETE", "Test gauntlet finished execution successfully.")
            else:
                log_error("FAILURE", f"Test runner exited with failure code: {ret}")
        return ret
    finally:
        subprocess.run([PODMAN_BIN, "rm", "-f", TEST_CONTAINER_NAME], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def cmd_stop(args: argparse.Namespace) -> int:
    """Stops and removes the entire pod and containers."""
    pretty = getattr(args, "pretty", False)
    if pretty:
        log_warn("STOP", "Terminating and destroying Odoo container stack...")
    else:
        print("Stopping Odoo container stack...")
        
    subprocess.run([PODMAN_BIN, "pod", "rm", "-f", POD_NAME], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    if pretty:
        log_success("CLEAN", "All containers destroyed, ports released, and memory freed.")
    else:
        print("Odoo container stack stopped.")
    return 0


def cmd_logs(args: argparse.Namespace) -> int:
    """Tails container logs."""
    pretty = getattr(args, "pretty", False)
    if pretty:
        log_header("📜 LIVE ODOO SERVER LOGS", f"Streaming logs from container '{WEB_CONTAINER_NAME}'", Colors.BLUE)
    return subprocess.call([PODMAN_BIN, "logs", "-f", WEB_CONTAINER_NAME])


# ==============================================================================
# DATABASE & INSPECTION TOOLS
# ==============================================================================

def _run_psql(sql: str, *, db: str | None, read_only: bool = True) -> list[dict[str, Any]]:
    if not db:
        raise CliError("database must be specified with --db or loaded from profile")

    if read_only and MUTATING_SQL_RE.search(sql):
        raise CliError("mutating SQL rejected in read-only mode")

    psql_script = (
        "\\set ON_ERROR_STOP on\n"
        "\\pset footer off\n"
        "\\pset format unaligned\n"
        "\\pset fieldsep ','\n"
        "\\pset null ''\n"
        "\\pset tuples_only off\n"
        f"{sql};\n"
    )

    cmd = [
        PODMAN_BIN, "exec", "-i", DB_CONTAINER_NAME,
        "psql", "-U", DEFAULT_DB_USER, "-d", db,
    ]

    proc = subprocess.run(
        cmd,
        input=psql_script,
        text=True,
        capture_output=True,
    )

    if proc.returncode != 0:
        raise CliError(f"PostgreSQL error: {proc.stderr.strip()}")

    reader = csv.DictReader(io.StringIO(proc.stdout.strip()))
    return [dict(row) for row in reader]


def _load_sql_recipe(name: str, **params: str) -> str:
    path = SQL_DIR / f"{name}.sql"
    if not path.is_file():
        raise CliError(f"SQL recipe not found: {path}")
    content = path.read_text(encoding="utf-8")
    for key, value in params.items():
        content = content.replace(f"{{{{{key}}}}}", value)
    return content


def cmd_env_inspect(args: argparse.Namespace) -> int:
    ctx = load_workspace(args)
    payload = {
        "runtime": {
            "backend": ctx.runtime.backend,
            "root": str(ctx.runtime.root),
            "config_path": str(ctx.runtime.config_path),
            "source_path": str(ctx.runtime.source_path),
        },
        "root": str(ctx.root),
        "config_path": str(ctx.config_path),
        "config": _redact_mapping(ctx.config),
        "addons_paths": [str(p) for p in ctx.addons_paths],
        "effective_db_name": ctx.effective_db_name,
    }
    return _emit_result(args, payload)


def cmd_addons_list(args: argparse.Namespace) -> int:
    ctx = load_workspace(args)
    modules: list[dict[str, Any]] = []
    for addons_dir in ctx.addons_paths:
        if not addons_dir.is_dir():
            continue
        for manifest in sorted(addons_dir.glob("*/__manifest__.py")):
            modules.append({
                "name": manifest.parent.name,
                "path": str(manifest.parent),
                "manifest_path": str(manifest),
            })
    return _emit_result(args, {"count": len(modules), "modules": modules})


def cmd_module_status(args: argparse.Namespace) -> int:
    ctx = load_workspace(args)
    target_db = getattr(args, "db", None) or ctx.effective_db_name or DEFAULT_DB_NAME
    sql = _load_sql_recipe("module_status", module_name=args.module)
    rows = _run_psql(sql, db=target_db)
    return _emit_result(args, {"module": args.module, "database": target_db, "rows": rows})


def cmd_db_summary(args: argparse.Namespace) -> int:
    ctx = load_workspace(args)
    target_db = getattr(args, "db", None) or ctx.effective_db_name or DEFAULT_DB_NAME
    sql = _load_sql_recipe("db_summary")
    rows = _run_psql(sql, db=target_db)
    return _emit_result(args, {"database": target_db, "summary": rows})


def cmd_db_query(args: argparse.Namespace) -> int:
    ctx = load_workspace(args)
    target_db = getattr(args, "db", None) or ctx.effective_db_name or DEFAULT_DB_NAME
    sql = ""
    if args.sql_file:
        sql = Path(args.sql_file).read_text(encoding="utf-8")
    elif args.sql_stdin:
        sql = sys.stdin.read()
    else:
        raise CliError("pass --sql-file or --sql-stdin")
    rows = _run_psql(sql, db=target_db, read_only=args.read_only)
    return _emit_result(args, {"database": target_db, "rows": rows})


# ==============================================================================
# AST ROUTE SCANNER
# ==============================================================================

class _RouteCollector(ast.NodeVisitor):
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.routes: list[RouteRecord] = []
        self.current_class = ""

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        old = self.current_class
        self.current_class = node.name
        self.generic_visit(node)
        self.current_class = old

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        routes: list[str] = []
        auth = None
        methods: list[str] = []
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call) and getattr(dec.func, "attr", "") == "route":
                for arg in dec.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        routes.append(arg.value)
                    elif isinstance(arg, (ast.List, ast.Tuple)):
                        for elt in arg.elts:
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                routes.append(elt.value)
                for kw in dec.keywords:
                    if kw.arg == "auth" and isinstance(kw.value, ast.Constant):
                        auth = str(kw.value.value)
                    elif kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple)):
                        for elt in kw.value.elts:
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                methods.append(elt.value)
        if routes:
            write_signals = []
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call) and getattr(sub.func, "attr", "") in WRITE_HINTS:
                    write_signals.append(sub.func.attr)
            self.routes.append(RouteRecord(
                file=self.file_path,
                class_name=self.current_class,
                method_name=node.name,
                routes=routes,
                auth=auth,
                methods=methods,
                write_signals=sorted(set(write_signals)),
            ))


def _scan_routes(ctx: WorkspaceContext) -> list[RouteRecord]:
    routes: list[RouteRecord] = []
    for addon_dir in ctx.addons_paths:
        for py_file in addon_dir.glob("*/controllers/**/*.py"):
            try:
                tree = ast.parse(py_file.read_text(encoding="utf-8"))
                collector = _RouteCollector(str(py_file))
                collector.visit(tree)
                routes.extend(collector.routes)
            except Exception:
                pass
    return routes


def cmd_route_list(args: argparse.Namespace) -> int:
    ctx = load_workspace(args)
    routes = _scan_routes(ctx)
    return _emit_result(args, {"count": len(routes), "routes": routes})


# ==============================================================================
# CLI PARSER DEFINITION
# ==============================================================================

def build_parser() -> argparse.ArgumentParser:
    shared_parser = argparse.ArgumentParser(add_help=False)
    shared_parser.add_argument("--pretty", action="store_true", help="Enable ANSI colors, badges, and visual formatting")
    shared_parser.add_argument("--raw", action="store_true", help="Force raw uncolored stream (default for agents)")

    parser = argparse.ArgumentParser(prog="odooctl", description="Explicit Odoo 17 Stack Controller & Inspector", parents=[shared_parser])
    parser.add_argument("--root", help="Explicit Odoo workspace root override")
    parser.add_argument("--config", help="Explicit odoo.conf override")
    parser.add_argument("--db", help="Explicit database override")
    parser.add_argument("--runtime-dir", help="Explicit runtime directory override")
    parser.add_argument("--json", action="store_true", help="Format output as JSON")

    top = parser.add_subparsers(dest="topic", required=True)

    # 1. Dev Runner (Synchronous in foreground, hot-reloading active, Ctrl-C to stop)
    dev_parser = top.add_parser("dev", help="Start Odoo dev server in FOREGROUND with hot-reloading (Ctrl-C to stop)", parents=[shared_parser])
    dev_parser.add_argument("workflow", help="Explicit workflow name (e.g. crm)")
    dev_parser.add_argument("--profile", default=DEFAULT_PROFILE_NAME, help=f"Workflow profile name (default: {DEFAULT_PROFILE_NAME})")
    dev_parser.set_defaults(func=cmd_dev)

    # 2. Test Runner (Strictly for running Odoo unit tests, zero lint blocking)
    test_parser = top.add_parser("test", help="Run isolated headless Odoo unit test runner for an explicit workflow or module", parents=[shared_parser])
    test_parser.add_argument("target", help="Explicit workflow or module name (e.g. crm, url_shortener)")
    test_parser.add_argument("--profile", default=DEFAULT_PROFILE_NAME, help=f"Workflow profile name (default: {DEFAULT_PROFILE_NAME})")
    test_parser.set_defaults(func=cmd_test)

    # 3. Linter Gate (Ruff)
    lint_parser = top.add_parser("lint", help="Run Ruff linter on explicit workflow or module", parents=[shared_parser])
    lint_parser.add_argument("target", help="Explicit workflow or module name (e.g. crm, url_shortener)")
    lint_parser.add_argument("--profile", default=DEFAULT_PROFILE_NAME, help=f"Workflow profile name (default: {DEFAULT_PROFILE_NAME})")
    lint_parser.add_argument("--fix", action="store_true", help="Automatically fix safe lint errors")
    lint_parser.set_defaults(func=cmd_lint)

    # 4. Formatter Gate (Ruff)
    fmt_parser = top.add_parser("fmt", help="Run Ruff formatter on explicit workflow or module", parents=[shared_parser])
    fmt_parser.add_argument("target", help="Explicit workflow or module name (e.g. crm, url_shortener)")
    fmt_parser.add_argument("--profile", default=DEFAULT_PROFILE_NAME, help=f"Workflow profile name (default: {DEFAULT_PROFILE_NAME})")
    fmt_parser.add_argument("--check", action="store_true", help="Check formatting without modifying files")
    fmt_parser.set_defaults(func=cmd_fmt)

    # 5. Stack Stop
    stop_parser = top.add_parser("stop", help="Stop and destroy Odoo container stack", parents=[shared_parser])
    stop_parser.set_defaults(func=cmd_stop)

    # 6. Logs
    logs_parser = top.add_parser("logs", help="Follow Odoo container logs", parents=[shared_parser])
    logs_parser.set_defaults(func=cmd_logs)

    # 7. Inspection
    env_parser = top.add_parser("env")
    env_sub = env_parser.add_subparsers(dest="action", required=True)
    env_inspect = env_sub.add_parser("inspect")
    env_inspect.add_argument("--json", action="store_true")
    env_inspect.set_defaults(func=cmd_env_inspect)

    addons_parser = top.add_parser("addons")
    addons_sub = addons_parser.add_subparsers(dest="action", required=True)
    addons_list = addons_sub.add_parser("list")
    addons_list.add_argument("--json", action="store_true")
    addons_list.set_defaults(func=cmd_addons_list)

    module_parser = top.add_parser("module")
    module_sub = module_parser.add_subparsers(dest="action", required=True)
    module_status = module_sub.add_parser("status")
    module_status.add_argument("module")
    module_status.add_argument("--json", action="store_true")
    module_status.set_defaults(func=cmd_module_status)

    db_parser = top.add_parser("db")
    db_sub = db_parser.add_subparsers(dest="action", required=True)
    db_summary = db_sub.add_parser("summary")
    db_summary.add_argument("--json", action="store_true")
    db_summary.set_defaults(func=cmd_db_summary)

    db_query = db_sub.add_parser("query")
    db_query.add_argument("--read-only", action="store_true")
    db_query.add_argument("--sql-file")
    db_query.add_argument("--sql-stdin", action="store_true")
    db_query.add_argument("--json", action="store_true")
    db_query.set_defaults(func=cmd_db_query)

    route_parser = top.add_parser("route")
    route_sub = route_parser.add_subparsers(dest="action", required=True)
    route_list = route_sub.add_parser("list")
    route_list.add_argument("--json", action="store_true")
    route_list.set_defaults(func=cmd_route_list)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv or sys.argv[1:])
    try:
        return args.func(args)
    except CliError as exc:
        return _fail(args, str(exc))
    except KeyboardInterrupt:
        return _fail(args, "interrupted")


if __name__ == "__main__":
    raise SystemExit(main())
