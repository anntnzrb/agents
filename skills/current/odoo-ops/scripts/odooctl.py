#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Autonomous Odoo 17 stack controller, test runner, and PostgreSQL inspector."""

from __future__ import annotations

import argparse
import ast
import concurrent.futures
import configparser
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict, cast

import xml_view_linter

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

# CONFIGURATION & CONSTANTS
# ==============================================================================

# Script Directories
SCRIPT_DIR = Path(__file__).resolve().parent
SQL_DIR = SCRIPT_DIR / "sql"
PROFILE_DIR = SCRIPT_DIR.parent / "profiles"
CONFIG_DIR = SCRIPT_DIR.parent / "config"
RUFF_CONFIG_PATH = CONFIG_DIR / "ruff.toml"

# Network & Ports (Zero Magic Numbers)
DEFAULT_HTTP_PORT = int(os.environ.get("ODOO_HTTP_PORT", "8069"))
DEFAULT_POSTGRES_PORT = int(os.environ.get("POSTGRES_PORT", "5432"))
DEFAULT_DB_HOST = "127.0.0.1"
DEFAULT_DB_USER = "odoo"
DEFAULT_DB_PASS = "odoo"  # noqa: S105 - default dev password for local container
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
    "create",
    "write",
    "unlink",
    "commit",
    "rollback",
    "execute",
    "save",
    "update",
    "delete",
    "insert",
    "drop",
    "alter",
    "truncate",
    "flush",
}


# ==============================================================================
# DATA MODELS & ERROR TYPES
# ==============================================================================


class CliError(Exception):
    """Clean domain error with exit code."""

    code: int

    def __init__(self, message: str, code: int = 1) -> None:
        """Initialize domain error with exit code."""
        super().__init__(message)
        self.code = code


@dataclass
class WorkflowProfile:
    """Workflow profile configuration."""

    database: str
    modules: list[str]
    test_modules: list[str] = field(default_factory=list)
    lint_modules: list[str] = field(default_factory=list)


@dataclass
class WorkspaceContext:
    """Resolved workspace context with paths and configuration."""

    root: Path
    config_path: Path
    config: configparser.ConfigParser
    addons_paths: list[Path]
    effective_db_name: str
    runtime: Path


class ActionInfo(TypedDict):
    """Metadata for an AST-discovered model action."""

    name: str
    line: int
    doc: str
    is_write: bool


class ModelInfo(TypedDict):
    """Metadata for an AST-discovered Odoo model."""

    module: str
    class_name: str
    model_name: str
    inherit: str | list[str] | None
    fields: dict[str, str]
    actions: list[ActionInfo]
    file: str
    line: int


class ControllerInfo(TypedDict):
    """Metadata for an AST-discovered controller route."""

    module: str
    class_name: str
    method: str
    route: str
    auth: str
    methods: list[str]
    file: str
    line: int


# ==============================================================================
# RECURSIVE AST & SQL EXTRACTOR
# ==============================================================================


class _OdooASTVisitor(ast.NodeVisitor):
    module_name: str
    file_path: str
    models: list[ModelInfo]
    controllers: list[ControllerInfo]
    _current_cls: str | None
    _current_model_name: str | None
    _current_inherit: str | list[str] | None
    _current_fields: dict[str, str]
    _current_actions: list[ActionInfo]
    _current_is_controller: bool

    def __init__(self, module_name: str, file_path: str) -> None:
        """Initialize AST visitor for an Odoo addon."""
        super().__init__()
        self.module_name = module_name
        self.file_path = file_path
        self.models = []
        self.controllers = []
        self._current_cls = None
        self._current_model_name = None
        self._current_inherit = None
        self._current_fields = {}
        self._current_actions = []
        self._current_is_controller = False

    def _eval_literal(self, node: ast.AST) -> object:
        try:
            val: object = cast("object", ast.literal_eval(node))
        except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
            if isinstance(node, ast.Constant):
                return cast("object", node.value)
            return None
        else:
            return val

    def _is_controller_class(self, node: ast.ClassDef) -> bool:
        for base in node.bases:
            name = getattr(base, "id", None) or getattr(base, "attr", None)
            if name in ("Controller", "Home"):
                return True
        return False

    def _extract_field_type(self, stmt: ast.Assign) -> str | None:
        if not isinstance(stmt.value, ast.Call):
            return None
        func = stmt.value.func
        fname = getattr(func, "attr", None) or getattr(func, "id", None)
        if not isinstance(fname, str):
            return None
        valid_fields = {
            "Char",
            "Integer",
            "Many2one",
            "One2many",
            "Many2many",
            "Boolean",
            "Float",
            "Text",
            "Html",
            "Selection",
            "Binary",
            "Datetime",
            "Date",
            "Json",
        }
        if fname and (fname[0].isupper() or fname in valid_fields):
            return fname
        return None

    def _process_assign(self, stmt: ast.Assign) -> None:
        for target in stmt.targets:
            if not isinstance(target, ast.Name):
                continue
            if target.id == "_name":
                val = self._eval_literal(stmt.value)
                self._current_model_name = str(val) if val is not None else None
            elif target.id == "_inherit":
                val = self._eval_literal(stmt.value)
                if isinstance(val, str):
                    self._current_inherit = val
                elif isinstance(val, list):
                    items = cast("list[object]", val)
                    self._current_inherit = [str(item) for item in items]
            else:
                field_type = self._extract_field_type(stmt)
                if field_type is not None:
                    self._current_fields[target.id] = field_type

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # pyright: ignore[reportImplicitOverride]
        """Inspect class definitions for Odoo models and controllers."""
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
        self._current_is_controller = self._is_controller_class(node)

        for stmt in node.body:
            if isinstance(stmt, ast.Assign):
                self._process_assign(stmt)
            elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._inspect_method(stmt)

        effective_model: str | None = None
        inherit_val: object = getattr(self, "_current_inherit", None)
        if self._current_model_name:
            effective_model = self._current_model_name
        elif isinstance(inherit_val, str):
            effective_model = inherit_val

        if effective_model:
            self.models.append(
                ModelInfo(
                    module=self.module_name,
                    class_name=node.name,
                    model_name=effective_model,
                    inherit=self._current_inherit,
                    fields=self._current_fields,
                    actions=self._current_actions,
                    file=self.file_path,
                    line=node.lineno,
                )
            )

        self.generic_visit(node)

        self._current_cls = prev_cls
        self._current_model_name = prev_model
        self._current_inherit = prev_inherit
        self._current_fields = prev_fields
        self._current_actions = prev_actions
        self._current_is_controller = prev_ctrl

    def _extract_route_info(
        self, dec: ast.AST
    ) -> tuple[list[str], str, list[str]] | None:
        if not isinstance(dec, ast.Call):
            return None
        func_name = getattr(dec.func, "attr", None) or getattr(dec.func, "id", None)
        if func_name != "route":
            return None

        routes: list[str] = []
        auth = "user"
        methods: list[str] = ["GET", "POST"]

        for arg in dec.args:
            val = self._eval_literal(arg)
            if isinstance(val, str):
                routes.append(val)
            elif isinstance(val, (list, tuple)):
                items = cast("list[object] | tuple[object, ...]", val)
                routes.extend(x for x in items if isinstance(x, str))

        for kw in dec.keywords:
            if kw.arg == "auth":
                auth_val = self._eval_literal(kw.value)
                auth = str(auth_val) if auth_val is not None else "user"
            elif kw.arg == "methods":
                m = self._eval_literal(kw.value)
                if isinstance(m, (list, tuple)):
                    m_items = cast("list[object] | tuple[object, ...]", m)
                    methods = [str(x) for x in m_items]

        return routes, auth, methods

    def _inspect_method(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for dec in node.decorator_list:
            route_info = self._extract_route_info(dec)
            if route_info is not None:
                routes, auth, methods = route_info
                for r in routes:
                    self.controllers.append(
                        ControllerInfo(
                            module=self.module_name,
                            class_name=self._current_cls or "Unknown",
                            method=node.name,
                            route=r,
                            auth=auth,
                            methods=methods,
                            file=self.file_path,
                            line=node.lineno,
                        )
                    )
                return

        if not node.name.startswith("_") or node.name.startswith("action_"):
            doc = ast.get_docstring(node) or ""
            is_write = any(h in node.name.lower() for h in WRITE_HINTS)
            self._current_actions.append(
                ActionInfo(
                    name=node.name,
                    line=node.lineno,
                    doc=doc.strip().split("\n")[0] if doc else "",
                    is_write=is_write,
                )
            )


# ==============================================================================
# SUBPROCESS & PODMAN EXECUTOR
# ==============================================================================


def _run(
    cmd: Sequence[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
    capture: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Execute a subprocess command with environment and error wrapping."""
    full_env = os.environ.copy()
    if env:
        full_env.update(env)

    try:
        return subprocess.run(  # noqa: S603 - controlled toolchain invocation
            cmd,
            cwd=cwd,
            check=check,
            text=True,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None,
            env=full_env,
        )
    except subprocess.CalledProcessError as err:
        raw_stderr: object = getattr(err, "stderr", None)
        raw_stdout: object = getattr(err, "stdout", None)
        stderr_msg = raw_stderr.strip() if isinstance(raw_stderr, str) else ""
        stdout_msg = raw_stdout.strip() if isinstance(raw_stdout, str) else ""
        combined = f"{stderr_msg}\n{stdout_msg}".strip()
        msg = (
            f"command failed (exit code {err.returncode}): {' '.join(cmd)}\n{combined}"
        )
        raise CliError(msg, code=err.returncode) from err
    except FileNotFoundError as err:
        msg = f"binary not found: {cmd[0]}"
        raise CliError(msg, code=127) from err


def _ensure_podman() -> None:
    """Validate that podman binary is available in PATH."""
    if not shutil.which("podman"):
        msg = "Podman binary not found. Please install podman."
        raise CliError(msg, code=127)


# ==============================================================================
# RUNTIME, WORKSPACE & PROFILE DISCOVERY
# ==============================================================================


def _resolve_runtime() -> Path:
    """Resolve Odoo runtime directory path."""
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
    """Resolve custom addons directory path."""
    env_addons = os.environ.get("ODOO_ADDONS_PATH")
    if env_addons:
        p = Path(env_addons).resolve()
        if p.is_dir():
            return p
    for candidate in (
        Path.home() / "repos/etech/odoo/addons",
        Path.cwd() / "addons",
        Path.cwd(),
    ):
        if candidate.is_dir():
            return candidate
    return Path.cwd()


def _resolve_source_addons(runtime: Path) -> list[Path]:
    """Resolve upstream source addons paths."""
    source_dir = runtime / ODOO_SOURCE_SUBPATH
    if not source_dir.is_dir():
        return []
    matches = list(source_dir.glob(SOURCE_ADDONS_GLOB))
    return [m for m in matches if m.is_dir()]


def _parse_manifest(manifest_path: Path) -> dict[str, object]:
    """Parse an Odoo __manifest__.py file safely using AST literal evaluation."""
    if not manifest_path.is_file():
        return {}
    try:
        content = manifest_path.read_text(encoding="utf-8")
        parsed: object = cast("object", ast.literal_eval(content))
        if isinstance(parsed, dict):
            return cast("dict[str, object]", parsed)
    except (ValueError, TypeError, SyntaxError, OSError):
        pass
    return {}


def _discover_all_modules(addons_dir: Path) -> dict[str, dict[str, object]]:
    """Discover all installable Odoo modules in the given directory."""
    modules: dict[str, dict[str, object]] = {}
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
    """Resolve current workspace context, config, and addons paths."""
    runtime = _resolve_runtime()
    addons = _resolve_addons()
    config_path = runtime / ODOO_CONFIG_SUBPATH

    config = configparser.ConfigParser()
    if config_path.is_file():
        _ = config.read(config_path)

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
    """Load and parse workflow profile from JSON configuration."""
    pfile = PROFILE_DIR / f"{profile}.json"
    if not pfile.is_file():
        msg = f"workflow profile not found: {pfile}"
        raise CliError(msg)

    data_raw: object = cast("object", json.loads(pfile.read_text(encoding="utf-8")))
    data = cast("dict[str, object]", data_raw) if isinstance(data_raw, dict) else {}
    workflows_obj = data.get("workflows")
    workflows = (
        cast("dict[str, object]", workflows_obj)
        if isinstance(workflows_obj, dict)
        else {}
    )
    wf_obj = workflows.get(workflow)
    if not isinstance(wf_obj, dict):
        available = list(workflows.keys())
        msg = (
            f"workflow {workflow!r} not found in profile {profile!r}. "
            f"Available workflows: {available}"
        )
        raise CliError(msg)

    wf = cast("dict[str, object]", wf_obj)
    db_val = wf.get("database")
    db = str(db_val) if db_val and str(db_val) != "False" else DEFAULT_DB_NAME

    raw_mods: object = wf.get("modules")
    mods = (
        [str(m) for m in cast("list[object]", raw_mods)]
        if isinstance(raw_mods, list)
        else []
    )
    for dep in ("admin_units", "contact_extension"):
        if dep not in mods and (_resolve_addons() / dep).is_dir():
            mods.append(dep)

    raw_tests: object = wf.get("test_modules")
    test_mods = (
        [str(m) for m in cast("list[object]", raw_tests)]
        if isinstance(raw_tests, list)
        else mods
    )

    raw_lint_val: object = wf.get("lint_modules")
    if isinstance(raw_lint_val, list):
        lint_mods = [str(m) for m in cast("list[object]", raw_lint_val)]
    elif raw_tests is not None:
        lint_mods = test_mods
    else:
        lint_mods = mods

    return WorkflowProfile(
        database=db,
        modules=mods,
        test_modules=test_mods,
        lint_modules=lint_mods,
    )


def _resolve_target_paths(
    target: str, profile_name: str = "etech", *, for_lint: bool = False
) -> list[Path]:
    """Resolve target module paths from single module name or profile workflow."""
    addons = _resolve_addons()
    # 0. Direct file path check
    direct_file = Path(target) if Path(target).is_absolute() else (addons / target)
    if direct_file.is_file():
        return [direct_file]


    # 1. Single module direct directory check
    mod_path = addons / target
    if mod_path.is_dir():
        return [mod_path]

    # 2. Workflow resolution in profile
    try:
        profile = _load_workflow_profile(profile_name, target)
        mods_to_use = profile.lint_modules if for_lint else profile.test_modules
        resolved: list[Path] = []
        for m in mods_to_use:
            p = addons / m
            if p.is_dir():
                resolved.append(p)
        if resolved:
            return resolved
    except CliError:
        pass

    msg = (
        f"Target {target!r} is neither a local addon directory in {addons} "
        f"nor a valid workflow in profile {profile_name!r}"
    )
    raise CliError(msg)


# ==============================================================================
# POSTGRESQL INTROSPECTION & POD INTERACTION
# ==============================================================================


def _exec_sql(sql: str, *, db: str = DEFAULT_DB_NAME) -> str:
    """Execute SQL statement via podman psql container."""
    _ensure_podman()
    cmd = [
        "podman",
        "exec",
        "-i",
        DEFAULT_DB_CONTAINER,
        "psql",
        "-U",
        DEFAULT_DB_USER,
        "-d",
        db,
        "-q",
        "-X",
        "-c",
        sql,
    ]
    res = _run(cmd, check=True)
    return res.stdout


def _exec_sql_json(sql: str, *, db: str = DEFAULT_DB_NAME) -> list[dict[str, object]]:
    """Execute SQL query returning rows as a JSON list of dictionaries."""
    wrapped = f"SELECT json_agg(t) FROM ({sql}) t;"  # noqa: S608 - internal JSON aggregation wrapper
    raw = _exec_sql(wrapped, db=db).strip()
    match = re.search(r"(\[.*\])", raw, re.DOTALL)
    if match:
        try:
            parsed: object = cast("object", json.loads(match.group(1)))
            if isinstance(parsed, list):
                items = cast("list[object]", parsed)
                return [
                    cast("dict[str, object]", item)
                    for item in items
                    if isinstance(item, dict)
                ]
        except (json.JSONDecodeError, ValueError):
            pass
    return []


# ==============================================================================
# TYPED ARGPARSE HELPERS
# ==============================================================================


def _require_str(args: argparse.Namespace, key: str, default: str = "") -> str:
    """Extract required string from argparse namespace."""
    val: object = getattr(args, key, default)
    return str(val) if val is not None else default


def _optional_str(args: argparse.Namespace, key: str) -> str | None:
    """Extract optional string from argparse namespace."""
    val: object = getattr(args, key, None)
    return str(val) if val is not None else None


def _require_bool(args: argparse.Namespace, key: str, default: bool = False) -> bool:
    """Extract boolean flag from argparse namespace."""
    val: object = getattr(args, key, default)
    return bool(val)


def _require_int(args: argparse.Namespace, key: str, default: int = 0) -> int:
    """Extract integer value from argparse namespace."""
    val: object = getattr(args, key, default)
    return int(val) if isinstance(val, (int, str)) else default


def _optional_int(args: argparse.Namespace, key: str) -> int | None:
    """Extract optional integer from argparse namespace."""
    val: object = getattr(args, key, None)
    if val is None:
        return None
    if isinstance(val, int):
        return val
    if isinstance(val, str) and val.isdigit():
        return int(val)
    return None


# ==============================================================================
# PODMAN RUNTIME ENGINE (START, STOP, DEV, TEST)
# ==============================================================================


def _get_pod_status(pod_name: str = DEFAULT_POD_NAME) -> str | None:
    """Check status of podman pod."""
    _ensure_podman()
    res = _run(
        [
            "podman",
            "pod",
            "ps",
            "--filter",
            f"name={pod_name}",
            "--format",
            "{{.Status}}",
        ],
        check=False,
    )
    out = res.stdout.strip()
    return out or None


def _ensure_runtime_pod(ctx: WorkspaceContext, *, recreate: bool = False) -> None:
    """Ensure podman pod and postgres database container are initialized and running."""
    _ensure_podman()
    status = _get_pod_status()
    if recreate and status:
        _stop_all()
        status = None

    if not status:
        # Create shared network Pod
        _ = _run(
            [
                "podman",
                "pod",
                "create",
                "--name",
                DEFAULT_POD_NAME,
                "-p",
                f"{DEFAULT_HTTP_PORT}:8069",
                "-p",
                f"127.0.0.1:{DEFAULT_POSTGRES_PORT}:5432",
            ]
        )

    # Ensure Database Container
    db_status = _run(
        [
            "podman",
            "ps",
            "-a",
            "--filter",
            f"name={DEFAULT_DB_CONTAINER}",
            "--format",
            "{{.Status}}",
        ],
        check=False,
    ).stdout.strip()
    if not db_status:
        db_dir = ctx.runtime / ODOO_DATA_DB_SUBPATH
        db_dir.mkdir(parents=True, exist_ok=True)
        _ = _run(
            [
                "podman",
                "run",
                "-d",
                "--pod",
                DEFAULT_POD_NAME,
                "--name",
                DEFAULT_DB_CONTAINER,
                "-e",
                f"POSTGRES_USER={DEFAULT_DB_USER}",
                "-e",
                f"POSTGRES_PASSWORD={DEFAULT_DB_PASS}",
                "-e",
                f"POSTGRES_DB={DEFAULT_DB_NAME}",
                "-v",
                f"{db_dir}:/var/lib/postgresql/data/pgdata:Z",
                "-e",
                "PGDATA=/var/lib/postgresql/data/pgdata/pgroot",
                DEFAULT_POSTGRES_IMAGE,
            ]
        )
        time.sleep(2)
    elif "Up" not in db_status:
        _ = _run(["podman", "start", DEFAULT_DB_CONTAINER])
        time.sleep(1)


def _stop_all() -> None:
    """Stop and remove all Odoo stack containers and the pod."""
    _ensure_podman()
    for name in (DEFAULT_WEB_CONTAINER, DEFAULT_DB_CONTAINER):
        _ = _run(["podman", "rm", "-f", name], check=False)
    _ = _run(["podman", "pod", "rm", "-f", DEFAULT_POD_NAME], check=False)


def cmd_stop(args: argparse.Namespace) -> int:
    """Stop all running Odoo and Postgres containers and remove the pod."""
    _ = _resolve_workspace()
    _stop_all()
    json_mode = _require_bool(args, "json")
    if json_mode:
        print(
            json.dumps(
                {
                    "status": "stopped",
                    "pod": DEFAULT_POD_NAME,
                    "containers": [DEFAULT_WEB_CONTAINER, DEFAULT_DB_CONTAINER],
                }
            )
        )
    else:
        print(f"Odoo stack ({DEFAULT_POD_NAME}) stopped and cleaned up.")
    return 0


def cmd_dev(args: argparse.Namespace) -> int:
    """Start Odoo 17 dev server in foreground with hot reload enabled."""
    ctx = _resolve_workspace()
    profile_name = _require_str(args, "profile", "etech")
    workflow = _require_str(args, "workflow", "crm")
    profile = _load_workflow_profile(profile_name, workflow)

    _ensure_runtime_pod(ctx)

    # Remove prior web container if hanging
    _ = _run(["podman", "rm", "-f", DEFAULT_WEB_CONTAINER], check=False)

    source_matches = list(ctx.runtime.glob("source/odoo-*"))
    source_dir = (
        source_matches[0] if source_matches else ctx.runtime / "source/odoo-17.0"
    )
    addons_mount = ctx.root
    config_mount = ctx.runtime / "config"
    data_web = ctx.runtime / "data/web"
    data_web.mkdir(parents=True, exist_ok=True)

    modules_str = ",".join(profile.modules)

    cmd = [
        "podman",
        "run",
        "-it" if sys.stdin.isatty() else "-i",
        "--pod",
        DEFAULT_POD_NAME,
        "--name",
        DEFAULT_WEB_CONTAINER,
        "-e",
        "PYTHONPATH=/mnt/odoo-src",
        "-e",
        f"HOST={DEFAULT_DB_HOST}",
        "-e",
        f"PORT={DEFAULT_POSTGRES_PORT}",
        "-e",
        f"USER={DEFAULT_DB_USER}",
        "-e",
        f"PASSWORD={DEFAULT_DB_PASS}",
        "-v",
        f"{source_dir}:/mnt/odoo-src:ro,z",
        "-v",
        f"{addons_mount}:/mnt/custom-addons:z",
        "-v",
        f"{config_mount}:/etc/odoo:ro,z",
        "-v",
        f"{data_web}:/var/lib/odoo:z",
        DEFAULT_ODOO_IMAGE,
        "python3",
        "-m",
        "odoo",
        "-c",
        "/etc/odoo/odoo.conf",
        "-d",
        profile.database,
        "--db_host",
        DEFAULT_DB_HOST,
        "--db_port",
        str(DEFAULT_POSTGRES_PORT),
        "--db_user",
        DEFAULT_DB_USER,
        "--db_password",
        DEFAULT_DB_PASS,
        DEV_MODE_FLAGS,
    ]

    if modules_str:
        cmd.extend(["-i", modules_str, "-u", modules_str])
    try:
        banner = (
            f"Starting Odoo 17 dev server on http://localhost:{DEFAULT_HTTP_PORT} "
            f"(db: {profile.database})"
        )
        print(banner)
        print(f"Modules: {modules_str}")
        print("Press Ctrl+C to stop.\n")
        _ = subprocess.run(  # noqa: S603 - controlled podman dev execution
            cmd, check=False
        )
    finally:
        _ = _run(["podman", "rm", "-f", DEFAULT_WEB_CONTAINER], check=False)
    return 0


def _evaluate_odoo_test_result(exit_code: int, output: str) -> tuple[bool, list[str]]:
    """Accurately evaluate Odoo test run result against failure signatures."""
    summary_lines = [
        line
        for line in output.splitlines()
        if "odoo.tests.result:" in line
        or "odoo.modules.loading: Module" in line
        or "At least one test failed" in line
        or " FAIL: " in line
        or " ERROR: " in line
        or "odoo.tests.stats:" in line
    ]

    has_test_failures = (
        exit_code != 0
        or "At least one test failed" in output
        or any(
            re.search(r"\b[1-9]\d*\s+failed\b", line) for line in output.splitlines()
        )
        or any(
            re.search(r"\b[1-9]\d*\s+failures?\b", line) for line in output.splitlines()
        )
        or any(
            re.search(r"\b[1-9]\d*\s+errors?\b", line)
            for line in output.splitlines()
            if "odoo.tests.result:" in line or "odoo.modules.loading:" in line
        )
    )
    has_passed = (
        exit_code == 0
        and not has_test_failures
        and ("0 failed, 0 error(s)" in output or "0 failures, 0 errors" in output)
    )
    return has_passed, summary_lines


def _cleanup_stale_test_containers() -> None:
    """Clean up any leftover test containers from previously interrupted runs."""
    stale_check = _run(
        ["podman", "ps", "-a", "--filter", "name=odoo-test-", "--format", "{{.Names}}"],
        check=False,
    )
    for stale in stale_check.stdout.splitlines():
        stale_name = stale.strip()
        if stale_name.startswith("odoo-test-"):
            _ = _run(["podman", "rm", "-f", stale_name], check=False)


def _resolve_test_targets(
    ctx: WorkspaceContext, target: str, profile_name: str
) -> tuple[str, list[str], list[str]]:
    """Resolve database, test tags, and update modules for test execution."""
    mod_path = ctx.root / target
    if mod_path.is_dir():
        pfile = PROFILE_DIR / f"{profile_name}.json"
        if pfile.is_file():
            try:
                raw_data: object = json.loads(pfile.read_text(encoding="utf-8"))
                if isinstance(raw_data, dict):
                    workflows: object = raw_data.get("workflows")
                    if isinstance(workflows, dict):
                        for wf_data in workflows.values():
                            if isinstance(wf_data, dict):
                                raw_mods: object = wf_data.get("modules")
                                raw_test_mods: object = wf_data.get("test_modules")
                                mods: list[str] = (
                                    [str(m) for m in raw_mods]
                                    if isinstance(raw_mods, list)
                                    else []
                                ) + (
                                    [str(m) for m in raw_test_mods]
                                    if isinstance(raw_test_mods, list)
                                    else []
                                )
                                if target in mods:
                                    db_val: object = wf_data.get("database")
                                    db = (
                                        str(db_val) if db_val else ctx.effective_db_name
                                    )
                                    return db, [f"/{target}"], [target]
            except (json.JSONDecodeError, OSError):
                pass
        return ctx.effective_db_name, [f"/{target}"], [target]
    profile = _load_workflow_profile(profile_name, target)
    test_tags = [f"/{m}" for m in profile.test_modules]
    return profile.database, test_tags, profile.test_modules


def _build_test_cmd(
    ctx: WorkspaceContext,
    container_name: str,
    db_to_use: str,
    tags_str: str,
    update_str: str,
) -> list[str]:
    """Construct podman run command for unit test runner."""
    source_matches = list(ctx.runtime.glob("source/odoo-*"))
    source_dir = (
        source_matches[0] if source_matches else ctx.runtime / "source/odoo-17.0"
    )
    addons_mount = ctx.root
    config_mount = ctx.runtime / "config"
    data_web = ctx.runtime / "data/web"
    data_web.mkdir(parents=True, exist_ok=True)

    cmd = [
        "podman",
        "run",
        "--rm",
        "-i",
        "--pod",
        DEFAULT_POD_NAME,
        "--name",
        container_name,
        "-e",
        "PYTHONPATH=/mnt/odoo-src",
        "-e",
        f"HOST={DEFAULT_DB_HOST}",
        "-e",
        f"PORT={DEFAULT_POSTGRES_PORT}",
        "-e",
        f"USER={DEFAULT_DB_USER}",
        "-e",
        f"PASSWORD={DEFAULT_DB_PASS}",
        "-v",
        f"{source_dir}:/mnt/odoo-src:ro,z",
        "-v",
        f"{addons_mount}:/mnt/custom-addons:z",
        "-v",
        f"{config_mount}:/etc/odoo:ro,z",
        "-v",
        f"{data_web}:/var/lib/odoo:z",
        DEFAULT_ODOO_IMAGE,
        "python3",
        "-m",
        "odoo",
        "-c",
        "/etc/odoo/odoo.conf",
        "-d",
        db_to_use,
        "--db_host",
        DEFAULT_DB_HOST,
        "--db_port",
        str(DEFAULT_POSTGRES_PORT),
        "--db_user",
        DEFAULT_DB_USER,
        "--db_password",
        DEFAULT_DB_PASS,
        "--test-enable",
        f"--test-tags={tags_str}",
        "--stop-after-init",
        "--no-http",
        "--http-port=0",
        "--log-level=test",
    ]
    if update_str:
        cmd.extend(["-u", update_str])
    return cmd


def _stream_test_output(proc: subprocess.Popen[str], *, json_mode: bool) -> list[str]:
    """Stream process stdout to appropriate descriptor and collect lines."""
    output_lines: list[str] = []
    if proc.stdout is not None:
        raw_stream = cast("object", proc.stdout)
        iterator = cast("Iterable[object]", raw_stream)
        for raw_line in iterator:
            line = str(raw_line)
            output_lines.append(line)
            if json_mode:
                _ = sys.stderr.write(line)
                _ = sys.stderr.flush()
            else:
                _ = sys.stdout.write(line)
                _ = sys.stdout.flush()
    return output_lines


def _run_test_process(
    cmd: list[str], container_test_name: str, *, json_mode: bool
) -> tuple[int, str]:
    """Execute test container process with live output streaming and cleanup."""
    try:
        proc = subprocess.Popen(  # noqa: S603 - controlled podman test execution
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        output_lines = _stream_test_output(proc, json_mode=json_mode)
        exit_code = proc.wait()
    except KeyboardInterrupt:
        msg = f"\n[INTERRUPT] Cancelling test container {container_test_name}...\n"
        if json_mode:
            _ = sys.stderr.write(msg)
            _ = sys.stderr.flush()
        else:
            _ = sys.stdout.write(msg)
            _ = sys.stdout.flush()
        _ = _run(["podman", "stop", "-t", "2", container_test_name], check=False)
        raise
    finally:
        _ = _run(["podman", "rm", "-f", container_test_name], check=False)

    return exit_code, "".join(output_lines)


def _run_single_module_test(
    ctx: WorkspaceContext,
    mod: str,
    db_to_use: str,
    explicit_tags: str | None,
    index: int,
) -> tuple[str, bool, int, list[str], str, float]:
    """Execute test container process for a single module in isolation."""
    start_time = time.time()
    tags_str = explicit_tags or f"/{mod}"
    container_test_name = f"odoo-test-{mod}-{int(time.time())}-{index}"
    cmd = _build_test_cmd(ctx, container_test_name, db_to_use, tags_str, mod)
    exit_code, output = _run_test_process(cmd, container_test_name, json_mode=True)
    is_success, summary_lines = _evaluate_odoo_test_result(exit_code, output)
    elapsed = time.time() - start_time
    return mod, is_success, exit_code, summary_lines, output, elapsed


def _run_parallel_tests(
    ctx: WorkspaceContext,
    args: argparse.Namespace,
    db_to_use: str,
    update_mods: list[str],
) -> int:
    """Execute test suites for multiple modules concurrently."""
    target = _require_str(args, "target", "crm")
    json_mode = _require_bool(args, "json")
    jobs_val = _optional_int(args, "jobs")
    jobs = jobs_val if jobs_val is not None else 4

    _ensure_runtime_pod(ctx)
    _cleanup_stale_test_containers()

    count = len(update_mods)
    header = (
        f"Running isolated Odoo unit tests for {target} ({count} modules) "
        f"in parallel (jobs: {jobs}, db: {db_to_use})...\n"
    )
    stream = sys.stderr if json_mode else sys.stdout
    _ = stream.write(header)
    _ = stream.flush()

    results: list[tuple[str, bool, int, list[str], str, float]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as executor:
        future_to_mod = {
            executor.submit(_run_single_module_test, ctx, m, db_to_use, None, i): m
            for i, m in enumerate(update_mods)
        }
        for future in concurrent.futures.as_completed(future_to_mod):
            mod = future_to_mod[future]
            try:
                res = future.result()
                results.append(res)
                name, ok, _, summary, _, dur = res
                tag = "[OK]" if ok else "[FAIL]"
                stats = summary[0] if summary else f"{dur:.2f}s"
                if not json_mode:
                    print(f" {tag} {name:25} ({dur:.2f}s) -> {stats}")
            except (subprocess.SubprocessError, OSError, RuntimeError) as exc:
                results.append((mod, False, 1, [str(exc)], "", 0.0))
                if not json_mode:
                    print(f" [FAIL] {mod:25} (Error: {exc})")

    all_ok = all(r[1] for r in results)
    max_dur = max((r[5] for r in results), default=0.0)

    if json_mode:
        print(
            json.dumps(
                {
                    "target": target,
                    "database": db_to_use,
                    "parallel": True,
                    "jobs": jobs,
                    "success": all_ok,
                    "duration": round(max_dur, 2),
                    "modules": [
                        {
                            "module": r[0],
                            "success": r[1],
                            "exit_code": r[2],
                            "summary": r[3],
                            "duration": round(r[5], 2),
                        }
                        for r in results
                    ],
                }
            )
        )
    elif all_ok:
        print(f"\n[OK] All {len(results)} module test suites passed in {max_dur:.2f}s.")
    else:
        print("\n[FAIL] One or more module test suites failed.")

    return 0 if all_ok else 1


def cmd_test(args: argparse.Namespace) -> int:
    """Run isolated Odoo 17 unit tests for a module or workflow."""
    ctx = _resolve_workspace()
    target = _require_str(args, "target", "crm")
    profile_name = _require_str(args, "profile", "etech")
    json_mode = _require_bool(args, "json")
    explicit_tags = _optional_str(args, "tags")
    explicit_db = _optional_str(args, "db")
    parallel = _require_bool(args, "parallel")
    jobs_val = _optional_int(args, "jobs")
    jobs = jobs_val if jobs_val is not None else (4 if parallel else 1)

    db_to_use, test_tags, update_mods = _resolve_test_targets(ctx, target, profile_name)
    if explicit_db:
        db_to_use = explicit_db

    if (parallel or jobs > 1) and len(update_mods) > 1 and not explicit_tags:
        return _run_parallel_tests(ctx, args, db_to_use, update_mods)
    tags_str = explicit_tags or ",".join(test_tags)
    _ensure_runtime_pod(ctx)
    _cleanup_stale_test_containers()

    update_str = ",".join(update_mods)
    container_test_name = f"odoo-test-{int(time.time())}"

    cmd = _build_test_cmd(ctx, container_test_name, db_to_use, tags_str, update_str)
    header_msg = (
        f"Running isolated Odoo unit tests for {target} "
        f"(tags: {tags_str}, db: {db_to_use})...\n"
    )
    if json_mode:
        _ = sys.stderr.write(header_msg)
        _ = sys.stderr.flush()
    else:
        _ = sys.stdout.write(header_msg)
        _ = sys.stdout.flush()

    exit_code, output = _run_test_process(cmd, container_test_name, json_mode=json_mode)
    is_success, summary_lines = _evaluate_odoo_test_result(exit_code, output)

    if json_mode:
        print(
            json.dumps(
                {
                    "target": target,
                    "database": db_to_use,
                    "exit_code": exit_code,
                    "success": is_success,
                    "summary": summary_lines,
                    "output": output,
                }
            )
        )
    elif is_success:
        print("\n[OK] All Odoo unit tests passed successfully.")
    else:
        print("\n[FAIL] Test run failed.")

    return 0 if is_success else (exit_code if exit_code != 0 else 1)


def cmd_lint(args: argparse.Namespace) -> int:
    """Run Ruff linter on profile lint_modules or target."""
    target = _require_str(args, "target", "crm")
    profile = _require_str(args, "profile", "etech")
    fix = _require_bool(args, "fix")
    json_mode = _require_bool(args, "json")
    target_paths = _resolve_target_paths(target, profile, for_lint=True)

    cmd = ["uvx", "ruff", "check"]
    if RUFF_CONFIG_PATH.is_file():
        cmd.extend(["--config", str(RUFF_CONFIG_PATH)])

    if fix:
        cmd.append("--fix")

    if json_mode:
        cmd.extend(["--output-format", "json"])

    cmd.extend([str(p) for p in target_paths])

    proc = subprocess.run(  # noqa: S603 - controlled ruff execution
        cmd, check=False
    )
    return proc.returncode


def cmd_fmt(args: argparse.Namespace) -> int:
    """Run Ruff formatter on profile lint_modules or target."""
    target = _require_str(args, "target", "crm")
    profile = _require_str(args, "profile", "etech")
    check_mode = _require_bool(args, "check")
    target_paths = _resolve_target_paths(target, profile, for_lint=True)

    cmd = ["uvx", "ruff", "format"]
    if RUFF_CONFIG_PATH.is_file():
        cmd.extend(["--config", str(RUFF_CONFIG_PATH)])

    if check_mode:
        cmd.append("--check")

    cmd.extend([str(p) for p in target_paths])

    proc = subprocess.run(  # noqa: S603 - controlled ruff execution
        cmd, check=False
    )
    return proc.returncode


def cmd_lint_views(args: argparse.Namespace) -> int:
    """Run AST and semantic linter on Odoo 17 XML views."""
    ctx = _resolve_workspace()
    target = _require_str(args, "target", "crm")
    profile = _require_str(args, "profile", "etech")
    strict = _require_bool(args, "strict")
    json_mode = _require_bool(args, "json")
    all_mode = _require_bool(args, "all")

    linter = xml_view_linter.OdooXmlViewLinter(root_path=ctx.root)
    violations: list[xml_view_linter.ViewViolation] = []

    if all_mode:
        mods = _discover_all_modules(ctx.root)
        for mod_name in mods:
            mod_dir = ctx.root / mod_name
            if mod_dir.is_dir():
                violations.extend(linter.lint_module(mod_dir))
    else:
        target_paths = _resolve_target_paths(target, profile, for_lint=True)
        for p in target_paths:
            if p.is_dir():
                violations.extend(linter.lint_module(p))
    if json_mode:
        print(xml_view_linter.format_violations_json(violations))
    else:
        print(xml_view_linter.format_violations_human(violations))

    has_critical = any(
        v["severity"] == xml_view_linter.Severity.CRITICAL.value for v in violations
    )
    has_warning = any(
        v["severity"] == xml_view_linter.Severity.WARNING.value for v in violations
    )

    if has_critical:
        return 1
    if strict and has_warning:
        return 1
    return 0


def cmd_logs(args: argparse.Namespace) -> int:
    """Tail logs of the active Odoo container."""
    _ensure_podman()
    tail = _require_int(args, "tail", 100)
    follow = _require_bool(args, "follow")
    cmd = ["podman", "logs", f"--tail={tail}"]
    if follow:
        cmd.append("-f")
    cmd.append(DEFAULT_WEB_CONTAINER)
    proc = subprocess.run(  # noqa: S603 - controlled podman logs execution
        cmd, check=False
    )
    return proc.returncode


# ==============================================================================
# INTROSPECTION & DIAGNOSTIC SUBCOMMANDS
# ==============================================================================


def cmd_env_inspect(args: argparse.Namespace) -> int:
    """Inspect workspace, runtime, and container environment."""
    ctx = _resolve_workspace()
    local_mods = _discover_all_modules(ctx.root)
    json_mode = _require_bool(args, "json")

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
    if json_mode:
        print(json.dumps(data, indent=2))
    else:
        print(f"Odoo Runtime:        {data['runtime_path']}")
        print(f"Custom Addons:       {data['custom_addons_path']}")
        print(f"Effective Database:  {data['effective_database']}")
        print(f"Pod Status:          {data['pod_status']}")
        print(f"Local Addons Count:  {data['local_modules_count']}")
    return 0


def cmd_addons_list(args: argparse.Namespace) -> int:
    """List all discoverable custom addons in workspace."""
    ctx = _resolve_workspace()
    mods = _discover_all_modules(ctx.root)
    json_mode = _require_bool(args, "json")
    if json_mode:
        print(json.dumps(mods, indent=2))
    else:
        for name, info in sorted(mods.items()):
            summary = str(info.get("summary", ""))
            version = str(info.get("version", ""))
            print(f"{name:30} {version:15} {summary}")
    return 0


def _parse_python_tree(pyfile: Path) -> ast.AST | None:
    """Parse python source file into AST, ignoring syntax and OS errors."""
    try:
        return ast.parse(pyfile.read_text(encoding="utf-8"), filename=str(pyfile))
    except (SyntaxError, ValueError, OSError):
        return None


def cmd_module_inspect(args: argparse.Namespace) -> int:
    """AST inspect models, fields, and controllers of an addon."""
    ctx = _resolve_workspace()
    module = _require_str(args, "module")
    json_mode = _require_bool(args, "json")
    mod_dir = ctx.root / module
    if not mod_dir.is_dir():
        msg = f"Module not found: {mod_dir}"
        raise CliError(msg)

    visitor = _OdooASTVisitor(module, str(mod_dir))
    for pyfile in mod_dir.rglob("*.py"):
        if any(ign in pyfile.parts for ign in IGNORED_ADDON_DIRS):
            continue
        tree = _parse_python_tree(pyfile)
        if tree is not None:
            visitor.file_path = str(pyfile.relative_to(ctx.root))
            visitor.visit(tree)

    manifest = _parse_manifest(mod_dir / "__manifest__.py")
    res = {
        "module": module,
        "manifest": manifest,
        "models": visitor.models,
        "controllers": visitor.controllers,
    }
    if json_mode:
        print(json.dumps(res, indent=2))
    else:
        print(f"=== Module: {module} ===")
        print(f"Summary: {manifest.get('summary', '')}")
        print(f"Models:  {len(visitor.models)}")
        for m in visitor.models:
            model_line = (
                f"  - {m['model_name']} ({m['class_name']}) -> "
                f"{len(m['fields'])} fields, {len(m['actions'])} actions"
            )
            print(model_line)
        print(f"Routes:  {len(visitor.controllers)}")
        for c in visitor.controllers:
            routes_str = ",".join(c["methods"])
            route_line = (
                f"  - {c['route']} [{routes_str}] -> {c['class_name']}.{c['method']}"
            )
            print(route_line)
    return 0


def cmd_route_list(args: argparse.Namespace) -> int:
    """List all exposed HTTP routes in workspace or target module."""
    ctx = _resolve_workspace()
    module = _optional_str(args, "module")
    json_mode = _require_bool(args, "json")
    routes: list[ControllerInfo] = []

    target_dirs = (
        [ctx.root / module]
        if module
        else [
            d
            for d in ctx.root.iterdir()
            if d.is_dir() and d.name not in IGNORED_ADDON_DIRS
        ]
    )

    for mdir in target_dirs:
        visitor = _OdooASTVisitor(mdir.name, str(mdir))
        for pyfile in mdir.rglob("*.py"):
            tree = _parse_python_tree(pyfile)
            if tree is not None:
                visitor.file_path = str(pyfile.relative_to(ctx.root))
                visitor.visit(tree)
        routes.extend(visitor.controllers)

    if json_mode:
        print(json.dumps(routes, indent=2))
    else:
        for r in sorted(routes, key=lambda x: x["route"]):
            route_str = r["route"]
            auth_str = r["auth"]
            mod_str = r["module"]
            target_str = f"{r['class_name']}.{r['method']}"
            print(f"{route_str:40} {auth_str:10} {mod_str:20} {target_str}")
    return 0


def cmd_db_summary(args: argparse.Namespace) -> int:
    """Show PostgreSQL database summary statistics and installed module count."""
    ctx = _resolve_workspace()
    db = _optional_str(args, "db") or ctx.effective_db_name
    json_mode = _require_bool(args, "json")
    _ensure_runtime_pod(ctx)

    sql = """
    SELECT
        current_database() AS database,
        pg_size_pretty(pg_database_size(current_database())) AS size,
        (SELECT count(*) FROM information_schema.tables WHERE table_schema='public')
            AS tables_count,
        (SELECT count(*) FROM ir_module_module WHERE state='installed')
            AS installed_modules_count
    """
    rows = _exec_sql_json(sql, db=db)
    summary = rows[0] if rows else {}
    if json_mode:
        print(json.dumps(summary, indent=2))
    else:
        print(f"Database:          {summary.get('database')}")
        print(f"Size:              {summary.get('size')}")
        print(f"Tables:            {summary.get('tables_count')}")
        print(f"Installed Modules: {summary.get('installed_modules_count')}")
    return 0


def cmd_db_tables(args: argparse.Namespace) -> int:
    """List largest database tables by total relation size."""
    ctx = _resolve_workspace()
    db = _optional_str(args, "db") or ctx.effective_db_name
    limit = _require_int(args, "limit", 20)
    json_mode = _require_bool(args, "json")
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
    LIMIT {limit};
    """  # noqa: S608 - static introspection query with numeric limit
    rows = _exec_sql_json(sql, db=db)
    if json_mode:
        print(json.dumps(rows, indent=2))
    else:
        for r in rows:
            tbl = str(r.get("table_name", ""))
            est = str(r.get("row_estimate", ""))
            sz = str(r.get("total_size", ""))
            print(f"{tbl:40} {est:10} rows  {sz:10}")
    return 0


def cmd_db_query(args: argparse.Namespace) -> int:
    """Execute arbitrary SQL query with write-safety check."""
    ctx = _resolve_workspace()
    db = _optional_str(args, "db") or ctx.effective_db_name
    _ensure_runtime_pod(ctx)

    raw_sql = _require_str(args, "sql").strip()
    unsafe = _require_bool(args, "unsafe")
    json_mode = _require_bool(args, "json")

    # Simple write safety check
    first_word = raw_sql.split()[0].upper() if raw_sql else ""
    if not unsafe and first_word not in ("SELECT", "EXPLAIN", "SHOW", "WITH"):
        msg = (
            f"Write query blocked by safety policy ({first_word}). "
            "Pass --unsafe to override."
        )
        raise CliError(msg)

    if json_mode:
        rows = _exec_sql_json(raw_sql, db=db)
        print(json.dumps(rows, indent=2))
    else:
        out = _exec_sql(raw_sql, db=db)
        print(out)
    return 0


def cmd_db_clone(args: argparse.Namespace) -> int:
    """Clone a PostgreSQL database template to a new target database."""
    ctx = _resolve_workspace()
    _ensure_runtime_pod(ctx)

    source = _require_str(args, "source")
    target = _require_str(args, "target")
    force = _require_bool(args, "force")
    json_mode = _require_bool(args, "json")

    print(f"Cloning database {source!r} -> {target!r}...")

    # 1. Terminate existing connections to source and target
    term_sql = f"""
        SELECT pg_terminate_backend(pid) FROM pg_stat_activity
        WHERE datname IN ('{source}', '{target}') AND pid <> pg_backend_pid();
    """  # noqa: S608 - maintenance connection termination
    _ = _exec_sql(term_sql, db="postgres")

    # 2. Drop target if requested
    if force:
        drop_sql = f'DROP DATABASE IF EXISTS "{target}";'
        _ = _exec_sql(drop_sql, db="postgres")

    # 3. Create database as template copy
    create_sql = (
        f'CREATE DATABASE "{target}" WITH TEMPLATE "{source}" OWNER {DEFAULT_DB_USER};'
    )
    _ = _exec_sql(create_sql, db="postgres")

    if json_mode:
        print(json.dumps({"status": "cloned", "source": source, "target": target}))
    else:
        print(f"[OK] Database successfully cloned: {target}")
    return 0


# ==============================================================================
# MAIN ENTRYPOINT & CLI PARSER
# ==============================================================================


def _build_parser() -> argparse.ArgumentParser:
    """Construct CLI argument parser and subcommands for odooctl."""
    parent_parser = argparse.ArgumentParser(add_help=False)
    _ = parent_parser.add_argument(
        "--json", action="store_true", help="Emit raw JSON output for agent pipelines"
    )
    _ = parent_parser.add_argument(
        "--profile", default="etech", help="Workflow profile name (default: etech)"
    )

    app_desc = (
        "Autonomous Odoo 17 stack controller, test runner, and PostgreSQL inspector."
    )
    parser = argparse.ArgumentParser(
        prog="odooctl",
        description=app_desc,
        parents=[parent_parser],
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # Dev Command
    p_dev = subparsers.add_parser(
        "dev",
        parents=[parent_parser],
        help="Start Odoo 17 dev server with hot-reload in foreground",
    )
    _ = p_dev.add_argument(
        "workflow", default="crm", nargs="?", help="Workflow profile key (default: crm)"
    )

    # Test Command
    p_test = subparsers.add_parser(
        "test", parents=[parent_parser], help="Run isolated Odoo 17 unit tests"
    )
    _ = p_test.add_argument(
        "target",
        default="crm",
        nargs="?",
        help="Module name or workflow profile key (default: crm)",
    )
    _ = p_test.add_argument(
        "--tags",
        "--test-tags",
        dest="tags",
        help="Explicit test tags filter (e.g. :TestModel or /module)",
    )
    _ = p_test.add_argument(
        "--db",
        dest="db",
        help="Database name override",
    )
    _ = p_test.add_argument(
        "--parallel",
        action="store_true",
        help="Run module test suites concurrently in parallel containers",
    )
    _ = p_test.add_argument(
        "-j",
        "--jobs",
        type=int,
        dest="jobs",
        help="Number of concurrent test worker containers (default: 4 when --parallel)",
    )

    # Lint Command
    p_lint = subparsers.add_parser(
        "lint", parents=[parent_parser], help="Run Ruff linter on profile lint_modules"
    )
    _ = p_lint.add_argument(
        "target",
        default="crm",
        nargs="?",
        help="Module name or workflow profile key (default: crm)",
    )
    _ = p_lint.add_argument(
        "--fix", action="store_true", help="Auto-fix safe lint violations"
    )

    # Fmt Command
    p_fmt = subparsers.add_parser(
        "fmt",
        parents=[parent_parser],
        help="Run Ruff formatter on profile lint_modules",
    )
    _ = p_fmt.add_argument(
        "target",
        default="crm",
        nargs="?",
        help="Module name or workflow profile key (default: crm)",
    )
    _ = p_fmt.add_argument(
        "--check", action="store_true", help="Check formatting without modifying files"
    )

    # Lint Views Command
    p_lint_views = subparsers.add_parser(
        "lint-views",
        parents=[parent_parser],
        help="AST and semantic linter for Odoo 17 XML views",
    )
    _ = p_lint_views.add_argument(
        "target",
        default="crm",
        nargs="?",
        help="Module name or workflow profile key (default: crm)",
    )
    _ = p_lint_views.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as errors (exit code 1 on warnings)",
    )
    _ = p_lint_views.add_argument(
        "--all",
        action="store_true",
        help="Lint all discoverable custom addons in workspace",
    )

    # Stop Command
    _ = subparsers.add_parser(
        "stop",
        parents=[parent_parser],
        help="Stop and tear down the Odoo Podman pod and containers",
    )

    # Logs Command
    p_logs = subparsers.add_parser(
        "logs", parents=[parent_parser], help="Tail logs of the active Odoo container"
    )
    _ = p_logs.add_argument(
        "-f", "--follow", action="store_true", help="Follow log output"
    )
    _ = p_logs.add_argument(
        "-n", "--tail", default=100, type=int, help="Number of lines to show"
    )

    # Env Inspect
    _ = subparsers.add_parser(
        "env",
        parents=[parent_parser],
        help="Inspect workspace, runtime, and container environment",
    )

    # Addons
    _ = subparsers.add_parser(
        "addons", parents=[parent_parser], help="List all discoverable custom addons"
    )

    # Module Inspect
    p_mod = subparsers.add_parser(
        "module",
        parents=[parent_parser],
        help="AST inspect models, fields, and controllers of an addon",
    )
    _ = p_mod.add_argument("module", help="Module directory name")

    # Routes
    p_routes = subparsers.add_parser(
        "routes", parents=[parent_parser], help="List all exposed HTTP routes"
    )
    _ = p_routes.add_argument("module", nargs="?", help="Filter by specific module")

    # DB Summary
    p_dbsum = subparsers.add_parser(
        "db-summary",
        parents=[parent_parser],
        help="PostgreSQL vitals, size, and module count",
    )
    _ = p_dbsum.add_argument("--db", help="Target database name")

    # DB Tables
    p_dbtables = subparsers.add_parser(
        "db-tables", parents=[parent_parser], help="List largest tables by disk usage"
    )
    _ = p_dbtables.add_argument("--db", help="Target database name")
    _ = p_dbtables.add_argument(
        "--limit", type=int, default=20, help="Max tables to return"
    )

    # DB Query
    p_query = subparsers.add_parser(
        "db-query", parents=[parent_parser], help="Execute SQL query against PostgreSQL"
    )
    _ = p_query.add_argument("sql", help="SQL query string")
    _ = p_query.add_argument("--db", help="Target database name")
    _ = p_query.add_argument(
        "--unsafe", action="store_true", help="Allow DDL/DML mutation queries"
    )

    # DB Clone
    p_clone = subparsers.add_parser(
        "db-clone",
        parents=[parent_parser],
        help="Clone template database using PostgreSQL engine",
    )
    _ = p_clone.add_argument("source", help="Source database name")
    _ = p_clone.add_argument("target", help="Target database name")
    _ = p_clone.add_argument(
        "--force", action="store_true", help="Drop target if already exists"
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint and command dispatcher for odooctl."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    cmd_map = {
        "dev": cmd_dev,
        "test": cmd_test,
        "lint": cmd_lint,
        "fmt": cmd_fmt,
        "lint-views": cmd_lint_views,
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

    command_name = _require_str(args, "command")
    handler = cmd_map.get(command_name)
    if not handler:
        parser.print_help()
        return 1

    try:
        return handler(args)
    except CliError as err:
        json_mode = _require_bool(args, "json")
        if json_mode:
            print(json.dumps({"error": str(err), "code": err.code}))
        else:
            print(f"Error: {err}", file=sys.stderr)
        return err.code


if __name__ == "__main__":
    sys.exit(main())
