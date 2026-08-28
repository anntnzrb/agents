#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Autonomous Odoo 17 stack controller, test runner, linter/formatter, and PostgreSQL inspector."""

from __future__ import annotations

import argparse
import ast
import configparser
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

# ==============================================================================
# CONFIGURATION & CONSTANTS
# ==============================================================================

# Script Directories
SCRIPT_DIR = Path(__file__).resolve().parent
SQL_DIR = SCRIPT_DIR / "sql"
PROFILE_DIR = SCRIPT_DIR.parent / "profiles"
CONFIG_DIR = SCRIPT_DIR.parent / "config"
RUFF_CONFIG_PATH = CONFIG_DIR / "ruff.toml"

# Network & Ports (Cero Magic Numbers)
DEFAULT_HTTP_PORT = int(os.environ.get("ODOO_HTTP_PORT", "8069"))
DEFAULT_POSTGRES_PORT = int(os.environ.get("POSTGRES_PORT", "5432"))
DEFAULT_DB_HOST = "127.0.0.1"
DEFAULT_DB_USER = "odoo"
DEFAULT_DB_PASS = "odoo"
DEFAULT_DB_NAME = "erptech_0817"

# Container Topology (Local Podman Pod)
DEFAULT_POD_NAME = "odoo-pod"
DEFAULT_DB_CONTAINER = "odoo-db"
DEFAULT_WEB_CONTAINER = "odoo-web"
DEFAULT_POSTGRES_IMAGE = "docker.io/library/postgres:15"
DEFAULT_ODOO_IMAGE = "localhost/odoo17-local:17.0-e-20260527"

# Standard Base Addons required by Odoo web/enterprise engine
BASE_ODOO_ADDONS = (
    "web",
    "web_enterprise",
    "base",
    "bus",
    "mail",
    "auth_signup",
    "web_editor",
    "portal",
)

# Standard Exclusions for module scans
IGNORED_ADDON_DIRS = {
    "__pycache__",
    ".git",
    ".github",
    ".zed",
    ".idea",
    ".vscode",
    "node_modules",
    "setup",
    "doc",
    "docs",
}

# Odoo Engine Hot-Reload Flags
DEV_MODE_FLAGS = "--dev=reload,xml,qweb,werkzeug"
ODOO_CONFIG_SUBPATH = Path("config/odoo.conf")
ODOO_SOURCE_SUBPATH = Path("source")
ODOO_DATA_WEB_SUBPATH = Path("data/web")
ODOO_DATA_DB_SUBPATH = Path("data/db")
SOURCE_ADDONS_GLOB = "odoo-*/odoo/addons"

# Security & AST Redaction
SECRET_TOKENS = ("passwd", "password", "token", "secret", "key")
WRITE_HINTS = {
    "create", "write", "unlink", "commit", "rollback",
    "execute", "save", "update", "delete", "insert",
    "drop", "alter", "truncate", "flush"
}


# ==============================================================================
# DATA MODELS & ERROR TYPES
# ==============================================================================

class CliError(Exception):
    """Clean domain error with exit code."""
    def __init__(self, message: str, code: int = 1):
        super().__init__(message)
        self.code = code


@dataclass
class WorkflowProfile:
    database: str
    modules: List[str]
    test_modules: List[str] = field(default_factory=list)
    lint_modules: List[str] = field(default_factory=list)


@dataclass
class WorkspaceContext:
    root: Path
    config_path: Path
    config: configparser.ConfigParser
    addons_paths: List[Path]
    effective_db_name: str
    runtime: Path


# ==============================================================================
# RECURSIVE AST & SQL EXTRACTOR (ZERO REGEX)
# ==============================================================================

class _OdooASTVisitor(ast.NodeVisitor):
    def __init__(self, module_name: str, file_path: str):
        self.module_name = module_name
        self.file_path = file_path
        self.models: List[Dict[str, Any]] = []
        self.controllers: List[Dict[str, Any]] = []
        self._current_cls: Optional[str] = None
        self._current_model_name: Optional[str] = None
        self._current_inherit: Optional[Union[str, List[str]]] = None
        self._current_fields: Dict[str, str] = {}
        self._current_actions: List[Dict[str, Any]] = []
        self._current_is_controller = False

    def _eval_literal(self, node: ast.AST) -> Any:
        try:
            return ast.literal_eval(node)
        except Exception:
            if isinstance(node, ast.Constant):
                return node.value
            return None

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        prev_cls = self._current_cls
        prev_model = self._current_model_name
        prev_inherit = self._current_inherit
        prev_fields = self._current_fields
        prev_actions = self._current_actions
        prev_ctrl = self._current_is_controller

        self._current_cls = node.name
        self._current_model_name = None
        self._current_inherit = None
        self._current_fields = {}
        self._current_actions = []
        self._current_is_controller = False

        # Classify by base class names
        for base in node.bases:
            name = getattr(base, "id", None) or getattr(base, "attr", None)
            if name in ("Controller", "Home"):
                self._current_is_controller = True

        for stmt in node.body:
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if isinstance(target, ast.Name):
                        if target.id == "_name":
                            self._current_model_name = self._eval_literal(stmt.value)
                        elif target.id == "_inherit":
                            self._current_inherit = self._eval_literal(stmt.value)
                        elif isinstance(stmt.value, ast.Call):
                            func = stmt.value.func
                            fname = getattr(func, "attr", None) or getattr(func, "id", None)
                            if fname and (fname[0].isupper() or fname in ("Char", "Integer", "Many2one", "One2many", "Many2many", "Boolean", "Float", "Text", "Html", "Selection", "Binary", "Datetime", "Date", "Json")):
                                self._current_fields[target.id] = fname
            elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._inspect_method(stmt)

        effective_model = self._current_model_name or (self._current_inherit if isinstance(self._current_inherit, str) else None)
        if effective_model:
            self.models.append({
                "module": self.module_name,
                "class_name": node.name,
                "model_name": effective_model,
                "inherit": self._current_inherit,
                "fields": self._current_fields,
                "actions": self._current_actions,
                "file": self.file_path,
                "line": node.lineno,
            })

        self.generic_visit(node)

        self._current_cls = prev_cls
        self._current_model_name = prev_model
        self._current_inherit = prev_inherit
        self._current_fields = prev_fields
        self._current_actions = prev_actions
        self._current_is_controller = prev_ctrl

    def _inspect_method(self, node: Union[ast.FunctionDef, ast.AsyncFunctionDef]) -> None:
        routes: List[str] = []
        auth = "user"
        methods: List[str] = ["GET", "POST"]

        for dec in node.decorator_list:
            if isinstance(dec, ast.Call):
                func_name = getattr(dec.func, "attr", None) or getattr(dec.func, "id", None)
                if func_name == "route":
                    for arg in dec.args:
                        val = self._eval_literal(arg)
                        if isinstance(val, str):
                            routes.append(val)
                        elif isinstance(val, (list, tuple)):
                            routes.extend(x for x in val if isinstance(x, str))
                    for kw in dec.keywords:
                        if kw.arg == "auth":
                            auth = str(self._eval_literal(kw.value) or "user")
                        elif kw.arg == "methods":
                            m = self._eval_literal(kw.value)
                            if isinstance(m, (list, tuple)):
                                methods = [str(x) for x in m]

        if routes:
            for r in routes:
                self.controllers.append({
                    "module": self.module_name,
                    "class_name": self._current_cls or "Unknown",
                    "method": node.name,
                    "route": r,
                    "auth": auth,
                    "methods": methods,
                    "file": self.file_path,
                    "line": node.lineno,
                })
            return

        if not node.name.startswith("_") or node.name.startswith("action_"):
            doc = ast.get_docstring(node) or ""
            is_write = any(h in node.name.lower() for h in WRITE_HINTS)
            self._current_actions.append({
                "name": node.name,
                "line": node.lineno,
                "doc": doc.strip().split("\n")[0] if doc else "",
                "is_write": is_write,
            })


# ==============================================================================
# SUBPROCESS & PODMAN EXECUTOR
# ==============================================================================

def _run(cmd: Sequence[str], *, cwd: Optional[Path] = None, check: bool = True, capture: bool = True, env: Optional[Dict[str, str]] = None) -> subprocess.CompletedProcess[str]:
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    
    try:
        res = subprocess.run(
            cmd,
            cwd=cwd,
            check=check,
            text=True,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None,
            env=full_env,
        )
        return res
    except subprocess.CalledProcessError as err:
        stderr_msg = err.stderr.strip() if err.stderr else ""
        stdout_msg = err.stdout.strip() if err.stdout else ""
        combined = f"{stderr_msg}\n{stdout_msg}".strip()
        raise CliError(f"command failed (exit code {err.returncode}): {' '.join(cmd)}\n{combined}", code=err.returncode)
    except FileNotFoundError:
        raise CliError(f"binary not found: {cmd[0]}", code=127)


def _ensure_podman() -> None:
    if not shutil.which("podman"):
        raise CliError("Podman binary not found. Please install podman.", code=127)


# ==============================================================================
# RUNTIME, WORKSPACE & PROFILE DISCOVERY
# ==============================================================================

def _resolve_runtime() -> Path:
    env_runtime = os.environ.get("ODOO_RUNTIME_PATH")
    if env_runtime:
        p = Path(env_runtime).resolve()
        if p.is_dir():
            return p
    for candidate in (Path("/opt/odoo17"), Path.home() / ".local/share/odoo17"):
        if candidate.is_dir():
            return candidate
    return Path("/opt/odoo17")


def _resolve_addons() -> Path:
    env_addons = os.environ.get("ODOO_ADDONS_PATH")
    if env_addons:
        p = Path(env_addons).resolve()
        if p.is_dir():
            return p
    for candidate in (Path.home() / "repos/etech/odoo/addons", Path.cwd() / "addons", Path.cwd()):
        if candidate.is_dir():
            return candidate
    return Path.cwd()


def _resolve_source_addons(runtime: Path) -> List[Path]:
    source_dir = runtime / ODOO_SOURCE_SUBPATH
    if not source_dir.is_dir():
        return []
    matches = list(source_dir.glob(SOURCE_ADDONS_GLOB))
    return [m for m in matches if m.is_dir()]


def _parse_manifest(manifest_path: Path) -> Dict[str, Any]:
    if not manifest_path.is_file():
        return {}
    try:
        content = manifest_path.read_text(encoding="utf-8")
        parsed = ast.literal_eval(content)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    return {}


def _discover_all_modules(addons_dir: Path) -> Dict[str, Dict[str, Any]]:
    modules: Dict[str, Dict[str, Any]] = {}
    if not addons_dir.is_dir():
        return modules

    for item in addons_dir.iterdir():
        if not item.is_dir() or item.name in IGNORED_ADDON_DIRS:
            continue
        manifest_file = item / "__manifest__.py"
        if manifest_file.is_file():
            manifest = _parse_manifest(manifest_file)
            modules[item.name] = {
                "name": item.name,
                "path": str(item),
                "summary": manifest.get("summary", ""),
                "author": manifest.get("author", ""),
                "depends": manifest.get("depends", []),
                "version": manifest.get("version", "17.0.1.0.0"),
                "installable": manifest.get("installable", True),
                "application": manifest.get("application", False),
                "auto_install": manifest.get("auto_install", False),
                "license": manifest.get("license", "LGPL-3"),
            }
    return modules


def _resolve_workspace() -> WorkspaceContext:
    runtime = _resolve_runtime()
    addons = _resolve_addons()
    config_path = runtime / ODOO_CONFIG_SUBPATH

    config = configparser.ConfigParser()
    if config_path.is_file():
        config.read(config_path)

    raw_db = config.get("options", "db_name", fallback=DEFAULT_DB_NAME)
    if raw_db in ("False", "None", ""):
        raw_db = DEFAULT_DB_NAME

    addons_paths = [addons]
    for sa in _resolve_source_addons(runtime):
        if sa not in addons_paths:
            addons_paths.append(sa)

    return WorkspaceContext(
        root=addons,
        config_path=config_path,
        config=config,
        addons_paths=addons_paths,
        effective_db_name=raw_db,
        runtime=runtime,
    )


def _load_workflow_profile(profile: str, workflow: str) -> WorkflowProfile:
    pfile = PROFILE_DIR / f"{profile}.json"
    if not pfile.is_file():
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
        database=db,
        modules=mods,
        test_modules=wf.get("test_modules", mods),
        lint_modules=lint_mods,
    )


def _resolve_target_paths(target: str, profile_name: str = "etech", *, for_lint: bool = False) -> List[Path]:
    addons = _resolve_addons()
    
    # 1. Single module direct directory check
    mod_path = addons / target
    if mod_path.is_dir():
        return [mod_path]
    
    # 2. Workflow resolution in profile
    try:
        profile = _load_workflow_profile(profile_name, target)
        mods_to_use = profile.lint_modules if for_lint else profile.test_modules
        resolved: List[Path] = []
        for m in mods_to_use:
            p = addons / m
            if p.is_dir():
                resolved.append(p)
        if resolved:
            return resolved
    except CliError:
        pass
    
    raise CliError(f"Target {target!r} is neither a local addon directory in {addons} nor a valid workflow in profile {profile_name!r}")


# ==============================================================================
# POSTGRESQL INTROSPECTION & POD INTERACTION
# ==============================================================================

def _exec_sql(sql: str, *, db: str = DEFAULT_DB_NAME) -> str:
    _ensure_podman()
    cmd = [
        "podman", "exec", "-i", DEFAULT_DB_CONTAINER,
        "psql", "-U", DEFAULT_DB_USER, "-d", db, "-q", "-X",
        "-c", sql
    ]
    res = _run(cmd, check=True)
    return res.stdout


def _exec_sql_json(sql: str, *, db: str = DEFAULT_DB_NAME) -> List[Dict[str, Any]]:
    wrapped = f"SELECT json_agg(t) FROM ({sql}) t;"
    raw = _exec_sql(wrapped, db=db).strip()
    match = re.search(r"(\[.*\])", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except Exception:
            pass
    return []


# ==============================================================================
# PODMAN RUNTIME ENGINE (START, STOP, DEV, TEST)
# ==============================================================================

def _get_pod_status(pod_name: str = DEFAULT_POD_NAME) -> Optional[str]:
    _ensure_podman()
    res = _run(["podman", "pod", "ps", "--filter", f"name={pod_name}", "--format", "{{.Status}}"], check=False)
    out = res.stdout.strip()
    return out if out else None


def _ensure_runtime_pod(ctx: WorkspaceContext, *, recreate: bool = False) -> None:
    _ensure_podman()
    status = _get_pod_status()
    if recreate and status:
        _stop_all(ctx)
        status = None

    if not status:
        # Create shared network Pod
        _run([
            "podman", "pod", "create",
            "--name", DEFAULT_POD_NAME,
            "-p", f"{DEFAULT_HTTP_PORT}:8069",
            "-p", f"127.0.0.1:{DEFAULT_POSTGRES_PORT}:5432",
        ])

    # Ensure Database Container
    db_status = _run(["podman", "ps", "-a", "--filter", f"name={DEFAULT_DB_CONTAINER}", "--format", "{{.Status}}"], check=False).stdout.strip()
    if not db_status:
        db_dir = ctx.runtime / ODOO_DATA_DB_SUBPATH
        db_dir.mkdir(parents=True, exist_ok=True)
        _run([
            "podman", "run", "-d",
            "--pod", DEFAULT_POD_NAME,
            "--name", DEFAULT_DB_CONTAINER,
            "-e", f"POSTGRES_USER={DEFAULT_DB_USER}",
            "-e", f"POSTGRES_PASSWORD={DEFAULT_DB_PASS}",
            "-e", f"POSTGRES_DB={DEFAULT_DB_NAME}",
            "-v", f"{db_dir}:/var/lib/postgresql/data/pgdata:Z",
            "-e", "PGDATA=/var/lib/postgresql/data/pgdata/pgroot",
            DEFAULT_POSTGRES_IMAGE,
        ])
        time.sleep(2)
    elif "Up" not in db_status:
        _run(["podman", "start", DEFAULT_DB_CONTAINER])
        time.sleep(1)


def _wait_for_http(url: str, timeout_sec: int = 30) -> bool:
    start = time.time()
    while time.time() - start < timeout_sec:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "odooctl-probe"})
            with urllib.request.urlopen(req, timeout=2) as resp:
                if resp.status in (200, 303, 404):
                    return True
        except (urllib.error.HTTPError, urllib.error.URLError):
            pass
        time.sleep(0.5)
    return False


def _stop_all(ctx: WorkspaceContext) -> None:
    _ensure_podman()
    for name in (DEFAULT_WEB_CONTAINER, DEFAULT_DB_CONTAINER):
        _run(["podman", "rm", "-f", name], check=False)
    _run(["podman", "pod", "rm", "-f", DEFAULT_POD_NAME], check=False)


def cmd_stop(args: argparse.Namespace) -> int:
    ctx = _resolve_workspace()
    _stop_all(ctx)
    if args.json:
        print(json.dumps({"status": "stopped", "pod": DEFAULT_POD_NAME, "containers": [DEFAULT_WEB_CONTAINER, DEFAULT_DB_CONTAINER]}))
    else:
        print(f"Odoo stack ({DEFAULT_POD_NAME}) stopped and cleaned up.")
    return 0


def cmd_dev(args: argparse.Namespace) -> int:
    ctx = _resolve_workspace()
    profile = _load_workflow_profile(args.profile, args.workflow)
    
    _ensure_runtime_pod(ctx)
    
    # Remove prior web container if hanging
    _run(["podman", "rm", "-f", DEFAULT_WEB_CONTAINER], check=False)

    source_dir = list(ctx.runtime.glob("source/odoo-*"))[0]
    addons_mount = ctx.root
    config_mount = ctx.runtime / "config"
    data_web = ctx.runtime / "data/web"
    data_web.mkdir(parents=True, exist_ok=True)

    modules_str = ",".join(profile.modules)

    cmd = [
        "podman", "run", "-it" if sys.stdin.isatty() else "-i",
        "--pod", DEFAULT_POD_NAME,
        "--name", DEFAULT_WEB_CONTAINER,
        "-e", "PYTHONPATH=/mnt/odoo-src",
        "-e", f"HOST={DEFAULT_DB_HOST}",
        "-e", f"PORT={DEFAULT_POSTGRES_PORT}",
        "-e", f"USER={DEFAULT_DB_USER}",
        "-e", f"PASSWORD={DEFAULT_DB_PASS}",
        "-v", f"{source_dir}:/mnt/odoo-src:ro,z",
        "-v", f"{addons_mount}:/mnt/custom-addons:z",
        "-v", f"{config_mount}:/etc/odoo:ro,z",
        "-v", f"{data_web}:/var/lib/odoo:z",
        DEFAULT_ODOO_IMAGE,
        "python3", "-m", "odoo",
        "-c", "/etc/odoo/odoo.conf",
        "-d", profile.database,
        "--db_host", DEFAULT_DB_HOST,
        "--db_port", str(DEFAULT_POSTGRES_PORT),
        "--db_user", DEFAULT_DB_USER,
        "--db_password", DEFAULT_DB_PASS,
        DEV_MODE_FLAGS,
    ]

    if modules_str:
        cmd.extend(["-i", modules_str, "-u", modules_str])
    try:
        print(f"Starting Odoo 17 dev server on http://localhost:{DEFAULT_HTTP_PORT} (db: {profile.database})")
        print(f"Modules: {modules_str}")
        print("Press Ctrl+C to stop.\n")
        subprocess.run(cmd, check=False)
    finally:
        _run(["podman", "rm", "-f", DEFAULT_WEB_CONTAINER], check=False)
    return 0


def cmd_test(args: argparse.Namespace) -> int:
    ctx = _resolve_workspace()
    
    # 1. Resolve Target Modules
    target = args.target
    profile_name = args.profile
    
    db_to_use = ctx.effective_db_name
    test_tags: List[str] = []

    # Check if target is a module directory
    mod_path = ctx.root / target
    if mod_path.is_dir():
        test_tags.append(f"/{target}")
        update_mods = [target]
    else:
        profile = _load_workflow_profile(profile_name, target)
        db_to_use = profile.database
        update_mods = profile.test_modules
        for m in profile.test_modules:
            test_tags.append(f"/{m}")

    _ensure_runtime_pod(ctx)

    source_dir = list(ctx.runtime.glob("source/odoo-*"))[0]
    addons_mount = ctx.root
    config_mount = ctx.runtime / "config"
    data_web = ctx.runtime / "data/web"

    tags_str = ",".join(test_tags)
    update_str = ",".join(update_mods)

    container_test_name = f"odoo-test-{int(time.time())}"

    cmd = [
        "podman", "run", "--rm", "-i",
        "--pod", DEFAULT_POD_NAME,
        "--name", container_test_name,
        "-e", "PYTHONPATH=/mnt/odoo-src",
        "-e", f"HOST={DEFAULT_DB_HOST}",
        "-e", f"PORT={DEFAULT_POSTGRES_PORT}",
        "-e", f"USER={DEFAULT_DB_USER}",
        "-e", f"PASSWORD={DEFAULT_DB_PASS}",
        "-v", f"{source_dir}:/mnt/odoo-src:ro,z",
        "-v", f"{addons_mount}:/mnt/custom-addons:z",
        "-v", f"{config_mount}:/etc/odoo:ro,z",
        "-v", f"{data_web}:/var/lib/odoo:z",
        DEFAULT_ODOO_IMAGE,
        "python3", "-m", "odoo",
        "-c", "/etc/odoo/odoo.conf",
        "-d", db_to_use,
        "--db_host", DEFAULT_DB_HOST,
        "--db_port", str(DEFAULT_POSTGRES_PORT),
        "--db_user", DEFAULT_DB_USER,
        "--db_password", DEFAULT_DB_PASS,
        "--test-enable",
        f"--test-tags={tags_str}",
        "--stop-after-init",
        "--log-level=test",
    ]

    if update_str:
        cmd.extend(["-i", update_str, "-u", update_str])
    print(f"Running isolated Odoo unit tests for {target} (tags: {tags_str}, db: {db_to_use})...\n")
    proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    output = proc.stdout

    # Parse and format output
    if args.json:
        has_failed = "ERROR" in output or "FAIL" in output or proc.returncode != 0
        summary_lines = [l for l in output.splitlines() if "odoo.tests.result:" in l or "FAILED" in l or "ERROR" in l]
        print(json.dumps({
            "target": target,
            "database": db_to_use,
            "exit_code": proc.returncode,
            "success": not has_failed,
            "summary": summary_lines,
            "output": output,
        }))
    else:
        print(output)
        if proc.returncode == 0 and "odoo.tests.result:" in output and "0 failed, 0 error(s)" in output:
            print("\n[OK] All Odoo unit tests passed successfully.")
        elif proc.returncode != 0:
            print("\n[FAIL] Test run failed.")

    return proc.returncode


def cmd_lint(args: argparse.Namespace) -> int:
    target_paths = _resolve_target_paths(args.target, args.profile, for_lint=True)
    
    cmd = [
        "uvx", "ruff", "check",
    ]
    if RUFF_CONFIG_PATH.is_file():
        cmd.extend(["--config", str(RUFF_CONFIG_PATH)])
    
    if args.fix:
        cmd.append("--fix")
    
    if args.json:
        cmd.extend(["--output-format", "json"])

    cmd.extend([str(p) for p in target_paths])

    proc = subprocess.run(cmd, check=False)
    return proc.returncode


def cmd_fmt(args: argparse.Namespace) -> int:
    target_paths = _resolve_target_paths(args.target, args.profile, for_lint=True)
    
    cmd = [
        "uvx", "ruff", "format",
    ]
    if RUFF_CONFIG_PATH.is_file():
        cmd.extend(["--config", str(RUFF_CONFIG_PATH)])

    if args.check:
        cmd.append("--check")

    cmd.extend([str(p) for p in target_paths])

    proc = subprocess.run(cmd, check=False)
    return proc.returncode


def cmd_logs(args: argparse.Namespace) -> int:
    _ensure_podman()
    cmd = ["podman", "logs", f"--tail={args.tail}"]
    if args.follow:
        cmd.append("-f")
    cmd.append(DEFAULT_WEB_CONTAINER)
    return subprocess.run(cmd, check=False).returncode


# ==============================================================================
# INTROSPECTION & DIAGNOSTIC SUBCOMMANDS
# ==============================================================================

def cmd_env_inspect(args: argparse.Namespace) -> int:
    ctx = _resolve_workspace()
    source_mods = [sa.name for sa in ctx.addons_paths if sa != ctx.root]
    local_mods = _discover_all_modules(ctx.root)

    data = {
        "status": "ready",
        "runtime_path": str(ctx.runtime),
        "custom_addons_path": str(ctx.root),
        "config_path": str(ctx.config_path),
        "effective_database": ctx.effective_db_name,
        "addons_paths": [str(p) for p in ctx.addons_paths],
        "local_modules_count": len(local_mods),
        "podman_pod": DEFAULT_POD_NAME,
        "pod_status": _get_pod_status() or "stopped",
    }
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        print(f"Odoo Runtime:        {data['runtime_path']}")
        print(f"Custom Addons:       {data['custom_addons_path']}")
        print(f"Effective Database:  {data['effective_database']}")
        print(f"Pod Status:          {data['pod_status']}")
        print(f"Local Addons Count:  {data['local_modules_count']}")
    return 0


def cmd_addons_list(args: argparse.Namespace) -> int:
    ctx = _resolve_workspace()
    mods = _discover_all_modules(ctx.root)
    if args.json:
        print(json.dumps(mods, indent=2))
    else:
        for name, info in sorted(mods.items()):
            print(f"{name:30} {info.get('version', ''):15} {info.get('summary', '')}")
    return 0


def cmd_module_inspect(args: argparse.Namespace) -> int:
    ctx = _resolve_workspace()
    mod_dir = ctx.root / args.module
    if not mod_dir.is_dir():
        raise CliError(f"Module not found: {mod_dir}")

    visitor = _OdooASTVisitor(args.module, str(mod_dir))
    for pyfile in mod_dir.rglob("*.py"):
        if any(ign in pyfile.parts for ign in IGNORED_ADDON_DIRS):
            continue
        try:
            tree = ast.parse(pyfile.read_text(encoding="utf-8"), filename=str(pyfile))
            visitor.file_path = str(pyfile.relative_to(ctx.root))
            visitor.visit(tree)
        except Exception:
            pass

    manifest = _parse_manifest(mod_dir / "__manifest__.py")
    res = {
        "module": args.module,
        "manifest": manifest,
        "models": visitor.models,
        "controllers": visitor.controllers,
    }
    if args.json:
        print(json.dumps(res, indent=2))
    else:
        print(f"=== Module: {args.module} ===")
        print(f"Summary: {manifest.get('summary', '')}")
        print(f"Models:  {len(visitor.models)}")
        for m in visitor.models:
            print(f"  - {m['model_name']} ({m['class_name']}) -> {len(m['fields'])} fields, {len(m['actions'])} actions")
        print(f"Routes:  {len(visitor.controllers)}")
        for c in visitor.controllers:
            print(f"  - {c['route']} [{','.join(c['methods'])}] -> {c['class_name']}.{c['method']}")
    return 0


def cmd_route_list(args: argparse.Namespace) -> int:
    ctx = _resolve_workspace()
    routes: List[Dict[str, Any]] = []

    target_dirs = [ctx.root / args.module] if args.module else [d for d in ctx.root.iterdir() if d.is_dir() and d.name not in IGNORED_ADDON_DIRS]

    for mdir in target_dirs:
        visitor = _OdooASTVisitor(mdir.name, str(mdir))
        for pyfile in mdir.rglob("*.py"):
            try:
                tree = ast.parse(pyfile.read_text(encoding="utf-8"), filename=str(pyfile))
                visitor.file_path = str(pyfile.relative_to(ctx.root))
                visitor.visit(tree)
            except Exception:
                pass
        routes.extend(visitor.controllers)

    if args.json:
        print(json.dumps(routes, indent=2))
    else:
        for r in sorted(routes, key=lambda x: x["route"]):
            print(f"{r['route']:40} {r['auth']:10} {r['module']:20} {r['class_name']}.{r['method']}")
    return 0


def cmd_db_summary(args: argparse.Namespace) -> int:
    ctx = _resolve_workspace()
    db = args.db or ctx.effective_db_name
    _ensure_runtime_pod(ctx)

    sql = f"""
    SELECT 
        current_database() AS database,
        pg_size_pretty(pg_database_size(current_database())) AS size,
        (SELECT count(*) FROM information_schema.tables WHERE table_schema='public') AS tables_count,
        (SELECT count(*) FROM ir_module_module WHERE state='installed') AS installed_modules_count
    """
    rows = _exec_sql_json(sql, db=db)
    summary = rows[0] if rows else {}
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"Database:          {summary.get('database')}")
        print(f"Size:              {summary.get('size')}")
        print(f"Tables:            {summary.get('tables_count')}")
        print(f"Installed Modules: {summary.get('installed_modules_count')}")
    return 0


def cmd_db_tables(args: argparse.Namespace) -> int:
    ctx = _resolve_workspace()
    db = args.db or ctx.effective_db_name
    _ensure_runtime_pod(ctx)

    sql = f"""
    SELECT 
        relname AS table_name,
        n_live_tup AS row_estimate,
        pg_size_pretty(pg_total_relation_size(c.oid)) AS total_size
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    JOIN pg_stat_user_tables s ON s.relid = c.oid
    WHERE n.nspname = 'public'
    ORDER BY pg_total_relation_size(c.oid) DESC
    LIMIT {args.limit};
    """
    rows = _exec_sql_json(sql, db=db)
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        for r in rows:
            print(f"{r['table_name']:40} {r['row_estimate']:10} rows  {r['total_size']:10}")
    return 0


def cmd_db_query(args: argparse.Namespace) -> int:
    ctx = _resolve_workspace()
    db = args.db or ctx.effective_db_name
    _ensure_runtime_pod(ctx)

    raw_sql = args.sql.strip()
    # Simple write safety check
    first_word = raw_sql.split()[0].upper() if raw_sql else ""
    if not args.unsafe and first_word not in ("SELECT", "EXPLAIN", "SHOW", "WITH"):
        raise CliError(f"Write query blocked by safety policy ({first_word}). Pass --unsafe to override.")

    if args.json:
        rows = _exec_sql_json(raw_sql, db=db)
        print(json.dumps(rows, indent=2))
    else:
        out = _exec_sql(raw_sql, db=db)
        print(out)
    return 0


def cmd_db_clone(args: argparse.Namespace) -> int:
    ctx = _resolve_workspace()
    _ensure_runtime_pod(ctx)

    source = args.source
    target = args.target

    print(f"Cloning database {source!r} -> {target!r}...")
    
    # 1. Terminate existing connections to source and target
    _exec_sql(f"""
        SELECT pg_terminate_backend(pid) FROM pg_stat_activity 
        WHERE datname IN ('{source}', '{target}') AND pid <> pg_backend_pid();
    """, db="postgres")

    # 2. Drop target if requested
    if args.force:
        _exec_sql(f"DROP DATABASE IF EXISTS \"{target}\";", db="postgres")

    # 3. Create database as template copy
    _exec_sql(f"CREATE DATABASE \"{target}\" WITH TEMPLATE \"{source}\" OWNER {DEFAULT_DB_USER};", db="postgres")

    if args.json:
        print(json.dumps({"status": "cloned", "source": source, "target": target}))
    else:
        print(f"[OK] Database successfully cloned: {target}")
    return 0


# ==============================================================================
# MAIN ENTRYPOINT & CLI PARSER
# ==============================================================================

def main(argv: Optional[Sequence[str]] = None) -> int:
    parent_parser = argparse.ArgumentParser(add_help=False)
    parent_parser.add_argument("--json", action="store_true", help="Emit raw JSON output for agent pipelines")
    parent_parser.add_argument("--profile", default="etech", help="Workflow profile name (default: etech)")

    parser = argparse.ArgumentParser(
        prog="odooctl",
        description="Autonomous Odoo 17 stack controller, test runner, and PostgreSQL inspector.",
        parents=[parent_parser],
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # Dev Command
    p_dev = subparsers.add_parser("dev", parents=[parent_parser], help="Start Odoo 17 dev server with hot-reload in foreground")
    p_dev.add_argument("workflow", default="crm", nargs="?", help="Workflow profile key (default: crm)")

    # Test Command
    p_test = subparsers.add_parser("test", parents=[parent_parser], help="Run isolated Odoo 17 unit tests")
    p_test.add_argument("target", default="crm", nargs="?", help="Module name or workflow profile key (default: crm)")

    # Lint Command
    p_lint = subparsers.add_parser("lint", parents=[parent_parser], help="Run Ruff linter on profile lint_modules")
    p_lint.add_argument("target", default="crm", nargs="?", help="Module name or workflow profile key (default: crm)")
    p_lint.add_argument("--fix", action="store_true", help="Auto-fix safe lint violations")

    # Fmt Command
    p_fmt = subparsers.add_parser("fmt", parents=[parent_parser], help="Run Ruff formatter on profile lint_modules")
    p_fmt.add_argument("target", default="crm", nargs="?", help="Module name or workflow profile key (default: crm)")
    p_fmt.add_argument("--check", action="store_true", help="Check formatting without modifying files")

    # Stop Command
    subparsers.add_parser("stop", parents=[parent_parser], help="Stop and tear down the Odoo Podman pod and containers")

    # Logs Command
    p_logs = subparsers.add_parser("logs", parents=[parent_parser], help="Tail logs of the active Odoo container")
    p_logs.add_argument("-f", "--follow", action="store_true", help="Follow log output")
    p_logs.add_argument("-n", "--tail", default=100, type=int, help="Number of lines to show")

    # Env Inspect
    subparsers.add_parser("env", parents=[parent_parser], help="Inspect workspace, runtime, and container environment")

    # Addons
    subparsers.add_parser("addons", parents=[parent_parser], help="List all discoverable custom addons")

    # Module Inspect
    p_mod = subparsers.add_parser("module", parents=[parent_parser], help="AST inspect models, fields, and controllers of an addon")
    p_mod.add_argument("module", help="Module directory name")

    # Routes
    p_routes = subparsers.add_parser("routes", parents=[parent_parser], help="List all exposed HTTP routes")
    p_routes.add_argument("module", nargs="?", help="Filter by specific module")

    # DB Summary
    p_dbsum = subparsers.add_parser("db-summary", parents=[parent_parser], help="PostgreSQL vitals, size, and module count")
    p_dbsum.add_argument("--db", help="Target database name")

    # DB Tables
    p_dbtables = subparsers.add_parser("db-tables", parents=[parent_parser], help="List largest tables by disk usage")
    p_dbtables.add_argument("--db", help="Target database name")
    p_dbtables.add_argument("--limit", type=int, default=20, help="Max tables to return")

    # DB Query
    p_query = subparsers.add_parser("db-query", parents=[parent_parser], help="Execute SQL query against PostgreSQL")
    p_query.add_argument("sql", help="SQL query string")
    p_query.add_argument("--db", help="Target database name")
    p_query.add_argument("--unsafe", action="store_true", help="Allow DDL/DML mutation queries")

    # DB Clone
    p_clone = subparsers.add_parser("db-clone", parents=[parent_parser], help="Clone template database using PostgreSQL engine")
    p_clone.add_argument("source", help="Source database name")
    p_clone.add_argument("target", help="Target database name")
    p_clone.add_argument("--force", action="store_true", help="Drop target if already exists")

    args = parser.parse_args(argv)

    cmd_map = {
        "dev": cmd_dev,
        "test": cmd_test,
        "lint": cmd_lint,
        "fmt": cmd_fmt,
        "stop": cmd_stop,
        "logs": cmd_logs,
        "env": cmd_env_inspect,
        "addons": cmd_addons_list,
        "module": cmd_module_inspect,
        "routes": cmd_route_list,
        "db-summary": cmd_db_summary,
        "db-tables": cmd_db_tables,
        "db-query": cmd_db_query,
        "db-clone": cmd_db_clone,
    }

    handler = cmd_map.get(args.command)
    if not handler:
        parser.print_help()
        return 1

    try:
        return handler(args)
    except CliError as err:
        if args.json:
            print(json.dumps({"error": str(err), "code": err.code}))
        else:
            print(f"Error: {err}", file=sys.stderr)
        return err.code


if __name__ == "__main__":
    sys.exit(main())
