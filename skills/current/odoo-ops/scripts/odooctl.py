#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Autonomous Odoo 17 stack controller, test runner, and PostgreSQL inspector."""

from __future__ import annotations

import argparse
import ast
import base64
import concurrent.futures
import configparser
import contextlib
import gzip
import hashlib
import ipaddress
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from io import BufferedIOBase
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict, cast

try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore[assignment]

import xml_view_linter

if TYPE_CHECKING:
    from collections.abc import Generator, Iterable, Sequence

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
DEFAULT_HTTP_BIND = os.environ.get("ODOO_HTTP_BIND", "0.0.0.0")  # noqa: S104 - user-configurable pod bind
DEFAULT_TEST_HTTP_PORT = int(os.environ.get("ODOO_TEST_HTTP_PORT", "8079"))
DEFAULT_POSTGRES_PORT = int(os.environ.get("POSTGRES_PORT", "5432"))
DEFAULT_DB_HOST = "127.0.0.1"
DEFAULT_DB_USER = "odoo"
DEFAULT_DB_PASS = "odoo"  # noqa: S105 - default dev password for local container
DEFAULT_ADMIN_DB = "postgres"

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
    database_source: str = ""


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


def _is_local_container_endpoint(uri: str) -> bool:
    """Recognize local sockets and loopback Podman machine connections."""
    if uri.startswith("/"):
        return True
    try:
        parsed = urllib.parse.urlsplit(uri)
        host = parsed.hostname
    except ValueError:
        return False
    if parsed.scheme == "unix":
        return not parsed.netloc and bool(parsed.path)
    if parsed.scheme not in {"ssh", "tcp", "http", "https"} or not host:
        return False
    if host == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    else:
        return address.is_loopback


def _ensure_podman() -> None:
    """Validate that podman is available and operating on a local container host."""
    if not shutil.which("podman"):
        msg = "Podman binary not found. Please install podman."
        raise CliError(msg, code=127)

    container_host = os.environ.get("CONTAINER_HOST", "").strip()
    if not container_host:
        # This command reads local connection metadata; it does not contact a server.
        result = _run(["podman", "system", "connection", "list", "--format", "json"])
        connections = cast("object", json.loads(result.stdout))
        if not isinstance(connections, list):
            raise CliError("Cannot resolve the local Podman connection.")
        selected = os.environ.get("CONTAINER_CONNECTION")
        for connection in cast("list[object]", connections):
            if not isinstance(connection, dict):
                raise CliError("Invalid Podman connection metadata.")
            entry = cast("dict[str, object]", connection)
            is_selected = (
                entry.get("Name") == selected
                if selected
                else entry.get("Default") is True
            )
            if is_selected:
                endpoint = entry.get("URI")
                if not isinstance(endpoint, str):
                    raise CliError("Podman connection has no endpoint.")
                container_host = endpoint
                break
        if selected and not container_host:
            raise CliError("Selected Podman connection was not found.")
    if container_host and not _is_local_container_endpoint(container_host):
        raise CliError("Remote Podman host detected. Use the confirmed local replica.")


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


_SAFE_IDENTIFIER_RE = re.compile(r"\A[a-zA-Z0-9_-]+\Z")


def _validate_db_name(name: str) -> str:
    """Validate database identifier to prevent SQL injection and quoting attacks."""
    if not name or not _SAFE_IDENTIFIER_RE.fullmatch(name):
        msg = (
            f"Invalid database name {name!r}. Database identifiers must contain only "
            "alphanumeric characters, underscores, or hyphens."
        )
        raise CliError(msg)
    return name


def _resolve_effective_database(
    args: argparse.Namespace | None = None,
    *,
    profile_name: str | None = None,
    config: configparser.ConfigParser | None = None,
    require: bool = True,
) -> tuple[str, str]:
    """Resolve the effective database name and its configuration source.

    Precedence order:
    1. --db CLI flag (source: 'flag')
    2. POSTGRES_DB environment variable (source: 'env')
    3. Profile default workflow database (source: 'profile')
    4. db_name in odoo.conf (source: 'odoo.conf')

    If none resolves and require is True, raises CliError with exit code 2.
    """
    flag_db = _optional_str(args, "db") if args is not None else None
    if flag_db:
        return _validate_db_name(flag_db), "flag"

    env_db = os.environ.get("POSTGRES_DB", "").strip()
    if env_db:
        return _validate_db_name(env_db), "env"

    prof = _optional_str(args, "profile") if args is not None else None
    prof_name = prof or profile_name or "etech"
    if prof_name and _SAFE_IDENTIFIER_RE.match(prof_name):
        pfile = PROFILE_DIR / f"{prof_name}.json"
        if pfile.is_file() and pfile.resolve().parent == PROFILE_DIR.resolve():
            try:
                data_raw: object = cast(
                    "object", json.loads(pfile.read_text(encoding="utf-8"))
                )
                if isinstance(data_raw, dict):
                    workflows_obj = data_raw.get("workflows")
                    if isinstance(workflows_obj, dict):
                        wf_key = (
                            "crm"
                            if "crm" in workflows_obj
                            else next(iter(workflows_obj.keys()), None)
                        )
                        if wf_key and isinstance(workflows_obj[wf_key], dict):
                            db_val = workflows_obj[wf_key].get("database")
                            if db_val and str(db_val) not in ("False", "None", ""):
                                return _validate_db_name(str(db_val)), "profile"
            except (json.JSONDecodeError, OSError):
                pass

    if config is not None:
        raw_db = config.get("options", "db_name", fallback="").strip()
        if raw_db and raw_db not in ("False", "None", ""):
            return _validate_db_name(raw_db), "odoo.conf"

    if require:
        msg = (
            "Could not resolve effective database: please set the profile database, "
            "define POSTGRES_DB, or pass --db."
        )
        raise CliError(msg, code=2)

    return "", ""


def _resolve_workspace(
    args: argparse.Namespace | None = None,
    *,
    profile_name: str | None = None,
    require_db: bool = True,
) -> WorkspaceContext:
    """Resolve current workspace context, config, and addons paths."""
    runtime = _resolve_runtime()
    addons = _resolve_addons()
    config_path = runtime / ODOO_CONFIG_SUBPATH

    config = configparser.ConfigParser()
    if config_path.is_file():
        _ = config.read(config_path)

    effective_db, db_source = _resolve_effective_database(
        args,
        profile_name=profile_name,
        config=config,
        require=require_db,
    )

    addons_paths = [addons]
    for sa in _resolve_source_addons(runtime):
        if sa not in addons_paths:
            addons_paths.append(sa)

    return WorkspaceContext(
        root=addons,
        config_path=config_path,
        config=config,
        addons_paths=addons_paths,
        effective_db_name=effective_db,
        runtime=runtime,
        database_source=db_source,
    )


def _load_workflow_profile(profile: str, workflow: str) -> WorkflowProfile:
    """Load and parse workflow profile from JSON configuration."""
    if not profile or not _SAFE_IDENTIFIER_RE.match(profile):
        msg = f"invalid profile name: {profile!r}"
        raise CliError(msg)
    pfile = PROFILE_DIR / f"{profile}.json"
    if not pfile.is_file() or pfile.resolve().parent != PROFILE_DIR.resolve():
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
    if db_val and str(db_val) not in ("False", "None", ""):
        db = _validate_db_name(str(db_val))
    else:
        db, _ = _resolve_effective_database(profile_name=profile, require=True)

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


def _exec_sql(
    sql: str,
    *,
    db: str = DEFAULT_ADMIN_DB,
    readonly: bool = False,
    tuples_only: bool = False,
) -> str:
    """Execute SQL statement via podman psql container."""
    _ensure_podman()
    safe_db = _validate_db_name(db)
    final_sql = (
        f"BEGIN TRANSACTION READ ONLY;\n{sql}\n;\nROLLBACK;" if readonly else sql
    )
    cmd = [
        "podman",
        "exec",
        "-i",
        DEFAULT_DB_CONTAINER,
        "psql",
        "-U",
        DEFAULT_DB_USER,
        "-d",
        safe_db,
        "-q",
        "-X",
        "-v",
        "ON_ERROR_STOP=1",
    ]
    if tuples_only:
        cmd.extend(["-t", "-A"])
    cmd.extend(["-c", final_sql])
    res = _run(cmd, check=True)
    return res.stdout


def _exec_sql_json(
    sql: str, *, db: str = DEFAULT_ADMIN_DB, readonly: bool = False
) -> list[dict[str, object]]:
    """Execute SQL query returning rows as a JSON list of dictionaries."""
    clean_subquery = sql.strip().removesuffix(";").rstrip()
    wrapped = f"SELECT COALESCE(json_agg(t), '[]'::json) FROM ({clean_subquery}) t;"  # noqa: S608 - internal JSON aggregation wrapper
    raw = _exec_sql(wrapped, db=db, readonly=readonly, tuples_only=True).strip()
    try:
        parsed: object = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CliError(
            "Database query returned invalid JSON; no audit result is available."
        ) from exc
    if not isinstance(parsed, list) or any(
        not isinstance(item, dict) for item in parsed
    ):
        raise CliError("Database query did not return an array of records.")
    return cast("list[dict[str, object]]", parsed)


def _quote_literal(val: str) -> str:
    """Safely quote a SQL string literal by doubling single quotes."""
    return "'" + val.replace("'", "''") + "'"


def _get_state_dir() -> Path:
    """Resolve odoo-ops state directory."""
    if os.environ.get("ODOO_OPS_STATE_DIR"):
        return Path(os.environ["ODOO_OPS_STATE_DIR"]).expanduser()
    if os.environ.get("XDG_STATE_HOME"):
        return Path(os.environ["XDG_STATE_HOME"]).expanduser() / "odoo-ops"
    return Path.home() / ".local" / "state" / "odoo-ops"


def _ensure_dir_0700(path: Path) -> None:
    """Ensure directory exists with 0o700 permissions."""
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        path.chmod(0o700)


def _write_file_0600(path: Path, content: str) -> None:
    """Write text file with 0o600 permissions."""
    _ensure_dir_0700(path.parent)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        _ = f.write(content)
    with contextlib.suppress(OSError):
        path.chmod(0o600)


def _ab64_encode(data: bytes) -> str:
    """Encode bytes in passlib ab64 (base64 with '+' as '.' and '=' stripped)."""
    return base64.b64encode(data).decode("ascii").replace("+", ".").rstrip("=")


def _passlib_pbkdf2_sha512(password: str, salt: bytes, rounds: int = 600000) -> str:
    """Hash password in passlib pbkdf2-sha512 format compatible with Odoo 17."""
    digest = hashlib.pbkdf2_hmac("sha512", password.encode("utf-8"), salt, rounds)
    salt_ab64 = _ab64_encode(salt)
    checksum_ab64 = _ab64_encode(digest)
    return f"$pbkdf2-sha512${rounds}${salt_ab64}${checksum_ab64}"


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


@dataclass
class _LockState:
    depth: int = 0


_LOCK_STATE = _LockState()


@contextlib.contextmanager
def _op_lock() -> Generator[None, None, None]:
    """Exclusive file lock for pod creation and test execution."""
    if fcntl is None:
        yield
        return

    if _LOCK_STATE.depth > 0:
        _LOCK_STATE.depth += 1
        try:
            yield
        finally:
            _LOCK_STATE.depth -= 1
        return

    lock_file = Path(tempfile.gettempdir()) / "odoo-ops.lock"
    with lock_file.open("a+") as f:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError):
            print(
                "waiting for odoo-ops lock (another test/pod operation is running)...",
                file=sys.stderr,
            )
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)

        _LOCK_STATE.depth = 1
        try:
            yield
        finally:
            _LOCK_STATE.depth = 0
            with contextlib.suppress(OSError):
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def _ensure_runtime_pod(ctx: WorkspaceContext, *, recreate: bool = False) -> None:
    """Ensure podman pod and postgres database container are initialized and running."""
    with _op_lock():
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
                    f"{DEFAULT_HTTP_BIND}:{DEFAULT_HTTP_PORT}:8069",
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
            init_db = ctx.effective_db_name or DEFAULT_DB_USER
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
                    f"POSTGRES_DB={init_db}",
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
    """Stop running Odoo containers."""
    _ensure_podman()
    only_web = _require_bool(args, "web")
    json_mode = _require_bool(args, "json")

    if only_web:
        _ = _run(["podman", "stop", DEFAULT_WEB_CONTAINER], check=False)
        _ = _run(["podman", "rm", "-f", DEFAULT_WEB_CONTAINER], check=False)
        if json_mode:
            print(
                json.dumps(
                    {
                        "status": "stopped",
                        "container": DEFAULT_WEB_CONTAINER,
                    }
                )
            )
        else:
            print(f"Container {DEFAULT_WEB_CONTAINER} stopped and removed.")
        return 0

    _stop_all()
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
    ctx = _resolve_workspace(args)
    profile_name = _require_str(args, "profile", "etech")
    workflow = _require_str(args, "workflow", "crm")
    profile = _load_workflow_profile(profile_name, workflow)
    db_to_use = _optional_str(args, "db") or profile.database

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
        db_to_use,
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
            f"(db: {db_to_use})"
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
    executed_tests = max(
        (int(count) for count in re.findall(r"of (\d+) tests", output)), default=0
    )
    has_passed = (
        exit_code == 0
        and not has_test_failures
        and executed_tests > 0
        and ("0 failed, 0 error(s)" in output or "0 failures, 0 errors" in output)
    )
    return has_passed, summary_lines


def _extract_test_counts(output: str) -> tuple[int, int, int] | None:
    """Extract (tests, failed, errors) from Odoo test runner output if present."""
    pattern = re.compile(
        r"(\d+)\s+fail(?:ed|ures?),?\s+(\d+)\s+errors?(?:\(s\))?\s+of\s+(\d+)\s+tests",
        re.IGNORECASE,
    )
    for line in reversed(output.splitlines()):
        if "odoo.tests.result:" in line or "odoo.modules.loading:" in line:
            match = pattern.search(line)
            if match:
                f = int(match.group(1))
                e = int(match.group(2))
                t = int(match.group(3))
                return t, f, e

    for line in reversed(output.splitlines()):
        match = pattern.search(line)
        if match:
            return int(match.group(3)), int(match.group(1)), int(match.group(2))

    return None


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


_FAILED_TEST_RE = re.compile(
    r"\b(?:FAIL|ERROR):\s*"
    r"(?:"
    r"([a-zA-Z0-9_]+)\s*\(([a-zA-Z0-9_.]+)\)"
    r"|"
    r"([a-zA-Z0-9_]+(?:\.[a-zA-Z0-9_]+)+)"
    r")"
)


def _parse_failed_tests(output: str) -> set[str]:
    """Parse failing test identifiers from Odoo test runner output."""
    failed: set[str] = set()
    for line in output.splitlines():
        match = _FAILED_TEST_RE.search(line)
        if not match:
            continue
        method_name, inside_parens, dotted_id = match.groups()
        if inside_parens:
            parts = inside_parens.split(".")
            if method_name and parts[-1] != method_name:
                failed.add(f"{parts[-1]}.{method_name}")
            elif len(parts) >= 2:
                failed.add(f"{parts[-2]}.{parts[-1]}")
            else:
                failed.add(inside_parens)
        elif dotted_id:
            parts = dotted_id.split(".")
            if len(parts) >= 2:
                failed.add(f"{parts[-2]}.{parts[-1]}")
            else:
                failed.add(dotted_id)
    return failed


def _run_baseline_test_comparison(
    ctx: WorkspaceContext,
    target: str,
    db_to_use: str,
    *,
    test_tags: list[str],
    update_mods: list[str],
    explicit_tags: str | None,
    baseline_ref: str,
    json_mode: bool,
) -> int:
    """Compare tests by running baseline ref first, then current workspace."""
    rev_parse = subprocess.run(
        [
            "git",
            "-C",
            str(ctx.root),
            "rev-parse",
            "--verify",
            f"{baseline_ref}^{{commit}}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if rev_parse.returncode != 0:
        msg = f"Invalid baseline ref or not a git repository: {baseline_ref!r}"
        raise CliError(msg, code=2)

    _ensure_runtime_pod(ctx)
    _cleanup_stale_test_containers()

    tags_str = explicit_tags or ",".join(test_tags)
    update_str = ",".join(update_mods)

    tmpdir = tempfile.mkdtemp(prefix="odoo-baseline-")
    worktree_path = Path(tmpdir)
    with contextlib.suppress(OSError):
        worktree_path.rmdir()

    try:
        add_res = subprocess.run(
            [
                "git",
                "-C",
                str(ctx.root),
                "worktree",
                "add",
                "--detach",
                str(worktree_path),
                baseline_ref,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if add_res.returncode != 0:
            err_msg = add_res.stderr.strip() or "git worktree add failed"
            msg = (
                f"Failed to create git worktree for baseline {baseline_ref!r}: "
                f"{err_msg}"
            )
            raise CliError(msg, code=2)

        # Baseline suite runs FIRST so DB ends at current code schema
        container_base_name = f"odoo-test-base-{int(time.time())}"
        cmd_base = _build_test_cmd(
            ctx,
            container_base_name,
            db_to_use,
            tags_str,
            update_str,
            source_root=worktree_path,
        )
        header_base = (
            f"Running baseline Odoo unit tests for {target} on ref {baseline_ref} "
            f"(tags: {tags_str}, db: {db_to_use})...\n"
        )
        if json_mode:
            _ = sys.stderr.write(header_base)
            _ = sys.stderr.flush()
        else:
            _ = sys.stdout.write(header_base)
            _ = sys.stdout.flush()

        exit_base, output_base = _run_test_process(
            cmd_base, container_base_name, json_mode=json_mode
        )
        is_success_base, summary_base = _evaluate_odoo_test_result(
            exit_base, output_base
        )
        baseline_failures = _parse_failed_tests(output_base)

        _cleanup_stale_test_containers()

        # Current suite runs SECOND
        container_curr_name = f"odoo-test-curr-{int(time.time())}"
        cmd_curr = _build_test_cmd(
            ctx,
            container_curr_name,
            db_to_use,
            tags_str,
            update_str,
            source_root=ctx.root,
        )
        header_curr = (
            f"Running current Odoo unit tests for {target} "
            f"(tags: {tags_str}, db: {db_to_use})...\n"
        )
        if json_mode:
            _ = sys.stderr.write(header_curr)
            _ = sys.stderr.flush()
        else:
            _ = sys.stdout.write(header_curr)
            _ = sys.stdout.flush()

        exit_curr, output_curr = _run_test_process(
            cmd_curr, container_curr_name, json_mode=json_mode
        )
        is_success_curr, summary_curr = _evaluate_odoo_test_result(
            exit_curr, output_curr
        )
        current_failures = _parse_failed_tests(output_curr)
    finally:
        _ = subprocess.run(
            [
                "git",
                "-C",
                str(ctx.root),
                "worktree",
                "remove",
                "--force",
                str(worktree_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        _ = subprocess.run(
            ["git", "-C", str(ctx.root), "worktree", "prune"],
            capture_output=True,
            text=True,
            check=False,
        )
        shutil.rmtree(worktree_path, ignore_errors=True)

    new_failures = sorted(current_failures - baseline_failures)
    preexisting = sorted(current_failures & baseline_failures)
    fixed = sorted(baseline_failures - current_failures)

    if json_mode:
        print(
            json.dumps(
                {
                    "baseline_ref": baseline_ref,
                    "new_failures": new_failures,
                    "preexisting": preexisting,
                    "fixed": fixed,
                    "current": {
                        "exit_code": exit_curr,
                        "success": is_success_curr,
                        "summary": summary_curr,
                        "failures": sorted(current_failures),
                    },
                    "baseline": {
                        "exit_code": exit_base,
                        "success": is_success_base,
                        "summary": summary_base,
                        "failures": sorted(baseline_failures),
                    },
                },
                indent=2,
            )
        )
    else:
        print(f"\nnew failures ({len(new_failures)}):")
        for fid in new_failures:
            print(f"  {fid}")
        print(f"\npre-existing ({len(preexisting)}):")
        for fid in preexisting:
            print(f"  {fid}")
        print(f"\nfixed ({len(fixed)}):")
        for fid in fixed:
            print(f"  {fid}")

        print(
            f"\nRESULT baseline={baseline_ref} new={len(new_failures)} "
            f"preexisting={len(preexisting)} fixed={len(fixed)}"
        )

    return 0 if len(new_failures) == 0 else 1


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
    *,
    source_root: Path | None = None,
) -> list[str]:
    """Construct podman run command for unit test runner."""
    source_matches = list(ctx.runtime.glob("source/odoo-*"))
    source_dir = (
        source_matches[0] if source_matches else ctx.runtime / "source/odoo-17.0"
    )
    addons_mount = source_root if source_root is not None else ctx.root
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
        f"--http-port={DEFAULT_TEST_HTTP_PORT}",
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

    if not json_mode:
        total_tests = 0
        total_failed = 0
        total_errors = 0
        has_counts = False
        for res_item in results:
            c = _extract_test_counts(res_item[4])
            if c is not None:
                has_counts = True
                total_tests += c[0]
                total_failed += c[1]
                total_errors += c[2]
        if has_counts:
            print(
                f"RESULT tests={total_tests} failed={total_failed} errors={total_errors}"
            )

    return 0 if all_ok else 1


def cmd_test(args: argparse.Namespace) -> int:
    """Run isolated Odoo 17 unit tests for a module or workflow."""
    with _op_lock():
        ctx = _resolve_workspace(args)
        target = _require_str(args, "target", "crm")
        profile_name = _require_str(args, "profile", "etech")
        json_mode = _require_bool(args, "json")
        explicit_tags = _optional_str(args, "tags")
        explicit_db = _optional_str(args, "db")
        parallel = _require_bool(args, "parallel")
        jobs_val = _optional_int(args, "jobs")
        jobs = jobs_val if jobs_val is not None else (4 if parallel else 1)

        db_to_use, test_tags, update_mods = _resolve_test_targets(
            ctx, target, profile_name
        )
        if explicit_db:
            db_to_use = explicit_db

        if "_seed_" in db_to_use:
            msg = (
                f"Refusing to execute tests on untouchable seed database "
                f"{db_to_use!r}. Clone to a work database first (e.g., db-clone)."
            )
            raise CliError(msg, code=2)

        baseline_ref = _optional_str(args, "baseline")
        if baseline_ref:
            return _run_baseline_test_comparison(
                ctx,
                target,
                db_to_use,
                test_tags=test_tags,
                update_mods=update_mods,
                explicit_tags=explicit_tags,
                baseline_ref=baseline_ref,
                json_mode=json_mode,
            )

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

        exit_code, output = _run_test_process(
            cmd, container_test_name, json_mode=json_mode
        )
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

        if not json_mode:
            counts = _extract_test_counts(output)
            if counts is not None:
                tests_count, failed_count, errors_count = counts
                print(
                    f"RESULT tests={tests_count} failed={failed_count} errors={errors_count}"
                )

        return 0 if is_success else (exit_code if exit_code != 0 else 1)


def cmd_lint(args: argparse.Namespace) -> int:
    """Run Ruff Python and XML view linters on profile lint_modules or target."""
    target = _require_str(args, "target", "crm")
    profile = _require_str(args, "profile", "etech")
    fix = _require_bool(args, "fix")
    json_mode = _require_bool(args, "json")
    strict = _require_bool(args, "strict")
    skip_views = _require_bool(args, "skip_views")
    target_paths = _resolve_target_paths(target, profile, for_lint=True)

    cmd = ["uvx", "ruff", "check"]
    if RUFF_CONFIG_PATH.is_file():
        cmd.extend(["--config", str(RUFF_CONFIG_PATH)])

    if fix:
        cmd.append("--fix")

    if json_mode:
        cmd.extend(["--output-format", "json"])

    cmd.extend([str(p) for p in target_paths])

    if skip_views:
        proc = subprocess.run(  # noqa: S603 - controlled ruff execution
            cmd, check=False
        )
        return proc.returncode

    ctx = _resolve_workspace()
    linter = xml_view_linter.OdooXmlViewLinter(root_path=ctx.root)
    violations: list[xml_view_linter.ViewViolation] = []
    for p in target_paths:
        if p.is_file() and p.suffix.lower() == ".xml":
            violations.extend(linter.lint_file(p))
        elif p.is_dir():
            violations.extend(linter.lint_module(p))

    has_critical = any(
        v["severity"] == xml_view_linter.Severity.CRITICAL.value for v in violations
    )
    has_warning = any(
        v["severity"] == xml_view_linter.Severity.WARNING.value for v in violations
    )
    views_failed = has_critical or (strict and has_warning)

    if json_mode:
        proc = subprocess.run(  # noqa: S603 - controlled ruff execution
            cmd, capture_output=True, text=True, check=False
        )
        try:
            ruff_json = json.loads(proc.stdout) if proc.stdout.strip() else []
        except Exception:
            ruff_json = proc.stdout.strip()

        combined_success = proc.returncode == 0 and not views_failed
        combined_payload = {
            "success": combined_success,
            "ruff_exit_code": proc.returncode,
            "python_violations": ruff_json,
            "view_violations": violations,
            "total_python_violations": len(ruff_json)
            if isinstance(ruff_json, list)
            else (1 if proc.returncode != 0 else 0),
            "total_view_violations": len(violations),
        }
        print(json.dumps(combined_payload, indent=2))
        return (
            0 if combined_success else (proc.returncode if proc.returncode != 0 else 1)
        )

    proc = subprocess.run(  # noqa: S603 - controlled ruff execution
        cmd, check=False
    )
    print("\n--- Odoo 17 XML View Linter ---")
    print(xml_view_linter.format_violations_human(violations))

    if proc.returncode != 0:
        return proc.returncode
    if views_failed:
        return 1
    return 0


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


def _get_latest_test_container() -> str | None:
    """Find the most recently created odoo-test-* container."""
    _ensure_podman()
    res = _run(
        ["podman", "ps", "-a", "--filter", "name=odoo-test-", "--format", "json"],
        check=False,
    )
    out = res.stdout.strip()
    if out:
        try:
            parsed: object = json.loads(out)
            if isinstance(parsed, list) and parsed:

                def _created_ts(item: dict[str, object]) -> float:
                    created = item.get("Created")
                    if isinstance(created, (int, float)):
                        return float(created)
                    return 0.0

                valid_items = [
                    x for x in cast("list[object]", parsed) if isinstance(x, dict)
                ]
                sorted_items = sorted(valid_items, key=_created_ts, reverse=True)
                for item in sorted_items:
                    names: object = item.get("Names")
                    if isinstance(names, list) and names:
                        name = str(names[0]).lstrip("/")
                        if name.startswith("odoo-test-"):
                            return name
                    elif isinstance(names, str) and names.startswith("odoo-test-"):
                        return names.lstrip("/")
        except json.JSONDecodeError:
            pass

    names_res = _run(
        ["podman", "ps", "-a", "--filter", "name=odoo-test-", "--format", "{{.Names}}"],
        check=False,
    )
    names = [
        n.strip().lstrip("/")
        for n in names_res.stdout.splitlines()
        if n.strip().lstrip("/").startswith("odoo-test-")
    ]
    return names[0] if names else None


def cmd_logs(args: argparse.Namespace) -> int:
    """Tail logs of the active Odoo container."""
    _ensure_podman()
    tail = _require_int(args, "tail", 100)
    follow = _require_bool(args, "follow")
    target_type = _require_str(args, "container", "web")

    if target_type == "web":
        target = DEFAULT_WEB_CONTAINER
    elif target_type == "db":
        target = DEFAULT_DB_CONTAINER
    elif target_type == "test":
        latest = _get_latest_test_container()
        if not latest:
            msg = "No test containers found (no odoo-test-* container exists)."
            raise CliError(msg)
        target = latest
    else:
        target = DEFAULT_WEB_CONTAINER

    cmd = ["podman", "logs", f"--tail={tail}"]
    if follow:
        cmd.append("-f")
    cmd.append(target)
    proc = subprocess.run(  # noqa: S603 - controlled podman logs execution
        cmd, check=False
    )
    return proc.returncode


# ==============================================================================
# INTROSPECTION & DIAGNOSTIC SUBCOMMANDS
# ==============================================================================


def _is_db_container_running() -> bool:
    """Check whether the database container is currently running."""
    _ensure_podman()
    res = _run(
        [
            "podman",
            "ps",
            "--filter",
            f"name={DEFAULT_DB_CONTAINER}",
            "--filter",
            "status=running",
            "--format",
            "{{.Names}}",
        ],
        check=False,
    )
    return bool(res.stdout.strip())


def cmd_env_inspect(args: argparse.Namespace) -> int:
    """Inspect workspace, runtime, and container environment."""
    ctx = _resolve_workspace(args)
    local_mods = _discover_all_modules(ctx.root)
    json_mode = _require_bool(args, "json")

    data: dict[str, object] = {
        "status": "ready",
        "runtime_path": str(ctx.runtime),
        "custom_addons_path": str(ctx.root),
        "config_path": str(ctx.config_path),
        "effective_database": ctx.effective_db_name,
        "database_source": ctx.database_source,
        "addons_paths": [str(p) for p in ctx.addons_paths],
        "local_modules_count": len(local_mods),
        "podman_pod": DEFAULT_POD_NAME,
        "pod_status": _get_pod_status() or "stopped",
    }

    if _is_db_container_running():
        safe_db = _validate_db_name(ctx.effective_db_name)
        check_sql = f"SELECT 1 FROM pg_database WHERE datname = '{safe_db}';"  # noqa: S608 - validated db name
        try:
            check_out = _exec_sql(check_sql, db="postgres", tuples_only=True).strip()
            db_exists = check_out == "1"
            data["database_exists"] = db_exists
            if not db_exists:
                list_sql = (
                    "SELECT datname FROM pg_database "
                    "WHERE NOT datistemplate AND datname <> 'postgres' "
                    "ORDER BY datname;"
                )
                avail_out = _exec_sql(list_sql, db="postgres", tuples_only=True).strip()
                avail_dbs = [d.strip() for d in avail_out.splitlines() if d.strip()]
                data["available_databases"] = avail_dbs
        except CliError:
            pass

    if json_mode:
        print(json.dumps(data, indent=2))
    else:
        print(f"Odoo Runtime:        {data['runtime_path']}")
        print(f"Custom Addons:       {data['custom_addons_path']}")
        print(
            f"Effective Database:  {data['effective_database']} "
            f"(source: {data['database_source']})"
        )
        print(f"Pod Status:          {data['pod_status']}")
        print(f"Local Addons Count:  {data['local_modules_count']}")
        if "database_exists" in data:
            print(f"Database Exists:     {data['database_exists']}")
            if not data["database_exists"] and "available_databases" in data:
                avail_list = cast("list[str]", data["available_databases"])
                avail_str = ", ".join(avail_list) or "none"
                print(f"Available DBs:       {avail_str}")
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

    if module:
        mod_dir = ctx.root / module
        if not mod_dir.is_dir():
            msg = f"Module not found: {mod_dir}"
            raise CliError(msg)
        target_dirs = [mod_dir]
    else:
        target_dirs = [
            d
            for d in ctx.root.iterdir()
            if d.is_dir() and d.name not in IGNORED_ADDON_DIRS
        ]

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
    ctx = _resolve_workspace(args)
    db = ctx.effective_db_name
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
    ctx = _resolve_workspace(args)
    db = ctx.effective_db_name
    limit = max(1, _require_int(args, "limit", 20))
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


def _strip_sql_comments(sql: str) -> str:
    """Remove SQL comments (line and block) and leading/trailing whitespace."""
    no_block = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    no_line = re.sub(r"--[^\n]*", " ", no_block)
    return no_line.strip()


def _is_mutation_query(clean_sql: str) -> bool:
    """Detect whether a query is a DDL/DML mutation rather than a plain SELECT."""
    match = re.match(r"^([a-zA-Z]+)", clean_sql)
    first_word = match.group(1).upper() if match else ""
    if first_word in (
        "INSERT",
        "UPDATE",
        "DELETE",
        "CREATE",
        "ALTER",
        "DROP",
        "TRUNCATE",
    ):
        return True
    if first_word == "WITH":
        return bool(
            re.search(
                r"\b(INSERT\s+INTO|UPDATE|DELETE\s+FROM)\b",
                clean_sql,
                re.IGNORECASE,
            )
        )
    return False


def cmd_db_query(args: argparse.Namespace) -> int:
    """Execute arbitrary SQL query with read-only transaction safety check."""
    json_mode = _require_bool(args, "json")
    try:
        raw_sql = ""
        file_arg = _optional_str(args, "file")
        sql_arg = _optional_str(args, "sql")

        if file_arg:
            if file_arg == "-":
                raw_sql = sys.stdin.read()
            else:
                fpath = Path(file_arg)
                if not fpath.is_file():
                    msg = f"SQL file not found: {fpath}"
                    raise CliError(msg)
                raw_sql = fpath.read_text(encoding="utf-8")
        elif sql_arg:
            raw_sql = sys.stdin.read() if sql_arg == "-" else sql_arg

        raw_sql = raw_sql.strip()
        if not raw_sql:
            msg = "SQL query string cannot be empty."
            raise CliError(msg)

        unsafe = _require_bool(args, "unsafe")

        if not unsafe:
            clean_check = raw_sql.rstrip(";").strip()
            if ";" in clean_check:
                msg = (
                    "Multi-statement queries are blocked without --unsafe. "
                    "Pass --unsafe to execute multi-statement SQL on local replica."
                )
                raise CliError(msg)

        ctx = _resolve_workspace(args)
        db = ctx.effective_db_name
        _ensure_runtime_pod(ctx)

        clean_sql = _strip_sql_comments(raw_sql).rstrip(";").strip()

        if json_mode:
            if unsafe and _is_mutation_query(clean_sql):
                has_returning = bool(
                    re.search(r"\bRETURNING\b", clean_sql, re.IGNORECASE)
                )
                if has_returning:
                    wrapped = (
                        f"WITH _r AS ({clean_sql}) "  # noqa: S608 - user DML with returning
                        "SELECT COALESCE(json_agg(_r), '[]'::json) FROM _r;"
                    )
                    raw_out = _exec_sql(
                        wrapped, db=db, readonly=False, tuples_only=True
                    ).strip()
                    try:
                        rows = json.loads(raw_out)
                    except json.JSONDecodeError as exc:
                        msg = "Failed to parse JSON result from RETURNING query."
                        raise CliError(msg) from exc
                    print(
                        json.dumps(
                            {"ok": True, "status": "SUCCESS", "rows": rows},
                            indent=2,
                        )
                    )
                else:
                    out = _exec_sql(raw_sql, db=db, readonly=False)
                    status_line = out.strip().splitlines()[-1] if out.strip() else ""
                    print(
                        json.dumps(
                            {"ok": True, "status": status_line, "rows": []},
                            indent=2,
                        )
                    )
            else:
                rows = _exec_sql_json(raw_sql, db=db, readonly=not unsafe)
                print(json.dumps(rows, indent=2))
        else:
            out = _exec_sql(raw_sql, db=db, readonly=not unsafe)
            print(out)

    except CliError as err:
        if json_mode:
            print(json.dumps({"ok": False, "error": str(err)}))
            return err.code if err.code != 0 else 1
        raise
    else:
        return 0


def _filestore_path(ctx: WorkspaceContext, db_name: str) -> Path:
    """Return the host path of a database filestore inside the runtime data dir."""
    return (
        ctx.runtime
        / "data"
        / "web"
        / ".local"
        / "share"
        / "Odoo"
        / "filestore"
        / _validate_db_name(db_name)
    )


def _regenerate_db_uuid(db_name: str) -> None:
    """Drop the copied ``database.uuid`` so Odoo issues a fresh one on next load.

    ``CREATE DATABASE ... TEMPLATE`` and SQL restores copy the identifier, and two
    databases sharing a uuid confuse telemetry and anything keyed on database
    identity. Odoo regenerates the parameter because it is declared in
    ``ir.config_parameter._default_parameters`` and initialized when missing.
    """
    _ = _exec_sql(
        "DELETE FROM ir_config_parameter WHERE key = 'database.uuid';",
        db=db_name,
    )


def _copy_filestore(ctx: WorkspaceContext, source: str, target: str) -> bool:
    """Copy a database filestore, warning when the source has none.

    A raw SQL clone never carries the filestore, so attachments and downloads
    fail with ``FileNotFoundError`` unless the directory is copied too.
    """
    from_fs = _filestore_path(ctx, source)
    to_fs = _filestore_path(ctx, target)
    if not from_fs.is_dir() or not any(from_fs.iterdir()):
        print(
            f"[WARN] {source!r} has no filestore: attachments will not resolve "
            f"in {target!r}."
        )
        return False
    _ = shutil.copytree(from_fs, to_fs, dirs_exist_ok=True)
    print(f"[OK] Filestore copied: {from_fs} -> {to_fs}")
    return True


def _pipe_stream_to_psql(stream: BufferedIOBase, db_name: str, dump_path: Path) -> None:
    """Pipe an open dump stream into psql inside the database container."""
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
        _validate_db_name(db_name),
        "-X",
        "-v",
        "ON_ERROR_STOP=1",
    ]
    with subprocess.Popen(cmd, stdin=subprocess.PIPE) as proc:
        if proc.stdin is None:
            msg = "psql stdin is not available"
            raise CliError(msg)
        _ = shutil.copyfileobj(stream, proc.stdin)
        proc.stdin.close()
        if proc.wait() != 0:
            msg = f"psql restore failed for {dump_path}"
            raise CliError(msg)


def _stream_dump_to_psql(dump_path: Path, db_name: str) -> None:
    """Stream a plain or gzip-compressed SQL dump into psql in the DB container."""
    if dump_path.suffix == ".gz":
        with gzip.open(dump_path, "rb") as stream:
            _pipe_stream_to_psql(stream, db_name, dump_path)
    else:
        with dump_path.open("rb") as stream:
            _pipe_stream_to_psql(stream, db_name, dump_path)


def cmd_db_restore(args: argparse.Namespace) -> int:
    """Restore a SQL dump into a new local replica database.

    Restores plain or gzip-compressed SQL dumps, which is the format the DBA
    delivers. Neutralization and data masking happen before the dump reaches
    this runtime, and a SQL dump carries no filestore.
    """
    dump_path = Path(_require_str(args, "dump")).expanduser()
    target = _validate_db_name(_require_str(args, "target"))
    force = _require_bool(args, "force")
    json_mode = _require_bool(args, "json")

    if not dump_path.is_file():
        msg = f"Dump file not found: {dump_path}"
        raise CliError(msg)
    if dump_path.suffix not in {".sql", ".gz"}:
        msg = (
            f"Unsupported dump format {dump_path.suffix!r}: this command restores "
            "plain or gzip-compressed SQL dumps only."
        )
        raise CliError(msg)

    ctx = _resolve_workspace()
    _ensure_runtime_pod(ctx)

    existing = _exec_sql_json(
        f"SELECT datname FROM pg_database WHERE datname = '{target}';",  # noqa: S608 - validated database identifier
        db="postgres",
    )
    if existing and not force:
        msg = (
            f"Target database {target!r} already exists. Pass --force to drop and "
            "recreate it (destructive)."
        )
        raise CliError(msg)

    size_mib = dump_path.stat().st_size / (1024 * 1024)
    print(f"Restoring {dump_path.name} ({size_mib:.0f} MiB) -> {target!r}...")

    drop_sql = f'DROP DATABASE IF EXISTS "{target}";'  # noqa: S608 - validated database identifier
    _ = _exec_sql(drop_sql, db="postgres")
    create_sql = (
        f'CREATE DATABASE "{target}" OWNER "{_validate_db_name(DEFAULT_DB_USER)}";'  # noqa: S608 - validated database identifier
    )
    _ = _exec_sql(create_sql, db="postgres")

    started = time.monotonic()
    _stream_dump_to_psql(dump_path, target)
    _regenerate_db_uuid(target)
    elapsed = time.monotonic() - started

    print(
        f"[WARN] A SQL dump carries no filestore: attachments will not resolve in "
        f"{target!r}."
    )
    if json_mode:
        print(
            json.dumps(
                {"status": "restored", "target": target, "seconds": round(elapsed, 1)}
            )
        )
    else:
        print(f"[OK] Database restored: {target} in {elapsed:.0f}s")
    return 0


def cmd_db_clone(args: argparse.Namespace) -> int:
    """Clone a PostgreSQL database template to a new target database."""
    source = _validate_db_name(_require_str(args, "source"))
    target = _validate_db_name(_require_str(args, "target"))
    if source == target:
        msg = f"Source and target database names cannot be identical ({source!r})."
        raise CliError(msg)

    owner = _validate_db_name(DEFAULT_DB_USER)
    force = _require_bool(args, "force")
    json_mode = _require_bool(args, "json")

    ctx = _resolve_workspace(args, require_db=False)
    _ensure_runtime_pod(ctx)

    print(f"Cloning database {source!r} -> {target!r}...")

    # 1. Terminate existing connections to source and target
    term_sql = (
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "  # noqa: S608 - validated database identifiers
        f"WHERE datname IN ('{source}', '{target}') AND pid <> pg_backend_pid();"
    )
    _ = _exec_sql(term_sql, db="postgres")

    # 2. Drop target if requested
    if force:
        drop_sql = f'DROP DATABASE IF EXISTS "{target}";'
        _ = _exec_sql(drop_sql, db="postgres")

    # 3. Create database as template copy
    create_sql = f'CREATE DATABASE "{target}" WITH TEMPLATE "{source}" OWNER "{owner}";'  # noqa: S608 - create database with validated identifiers
    _ = _exec_sql(create_sql, db="postgres")

    # 4. A template copy is neither filestore-aware nor uuid-unique
    _ = _copy_filestore(ctx, source, target)
    _regenerate_db_uuid(target)

    if json_mode:
        print(json.dumps({"status": "cloned", "source": source, "target": target}))
    else:
        print(f"[OK] Database successfully cloned: {target}")
    return 0


def _remove_filestore(ctx: WorkspaceContext, db_name: str) -> bool:
    """Remove database filestore directory, handling UID permissions."""
    fs_path = _filestore_path(ctx, db_name)
    if not fs_path.exists():
        return False
    try:
        shutil.rmtree(fs_path)
    except OSError:
        res = _run(["podman", "unshare", "rm", "-rf", str(fs_path)], check=False)
        return res.returncode == 0 or not fs_path.exists()
    else:
        return True


def cmd_db_list(args: argparse.Namespace) -> int:
    """List local databases and their disk sizes (excluding templates/postgres)."""
    ctx = _resolve_workspace(args, require_db=False)
    json_mode = _require_bool(args, "json")
    _ensure_runtime_pod(ctx)

    sql = """
    SELECT
        datname AS name,
        pg_size_pretty(pg_database_size(datname)) AS size,
        pg_database_size(datname) AS size_bytes
    FROM pg_database
    WHERE NOT datistemplate AND datname <> 'postgres'
    ORDER BY datname;
    """
    rows = _exec_sql_json(sql, db="postgres")
    if json_mode:
        print(json.dumps(rows, indent=2))
    elif not rows:
        print("No databases found.")
    else:
        for r in rows:
            name = str(r.get("name", ""))
            size = str(r.get("size", ""))
            print(f"{name:40} {size}")
    return 0


def cmd_db_drop(args: argparse.Namespace) -> int:
    """Drop a local PostgreSQL database and its filestore."""
    name = _require_str(args, "name")
    db_name = _validate_db_name(name)
    force = _require_bool(args, "force")
    allow_seed = _require_bool(args, "allow_seed")
    json_mode = _require_bool(args, "json")

    if not force:
        msg = "Refusing to drop database without --force."
        raise CliError(msg, code=2)

    if "_seed_" in db_name and not allow_seed:
        msg = (
            f"Refusing to drop seed database {db_name!r}. "
            "Seed databases are protected. Pass --allow-seed if you are certain."
        )
        raise CliError(msg, code=2)

    ctx = _resolve_workspace(args, require_db=False)
    _ensure_runtime_pod(ctx)

    check_sql = f"SELECT 1 FROM pg_database WHERE datname = '{db_name}';"  # noqa: S608 - validated db name
    exists_rows = _exec_sql_json(check_sql, db="postgres")
    db_exists = bool(exists_rows)

    if db_exists:
        term_sql = (
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "  # noqa: S608 - validated db name
            f"WHERE datname = '{db_name}' AND pid <> pg_backend_pid();"
        )
        _ = _exec_sql(term_sql, db="postgres")
        drop_sql = f'DROP DATABASE IF EXISTS "{db_name}";'  # noqa: S608 - validated db name
        _ = _exec_sql(drop_sql, db="postgres")
        fs_removed = _remove_filestore(ctx, db_name)

        if json_mode:
            print(
                json.dumps(
                    {
                        "status": "dropped",
                        "database": db_name,
                        "filestore_removed": fs_removed,
                    },
                    indent=2,
                )
            )
        else:
            print(f"[OK] Database dropped: {db_name}")
    elif json_mode:
        print(
            json.dumps(
                {
                    "status": "not_found",
                    "database": db_name,
                    "message": f"Database {db_name!r} does not exist.",
                },
                indent=2,
            )
        )
    else:
        print(f"[INFO] Database {db_name!r} does not exist (nothing to drop).")
    return 0


def cmd_shell(args: argparse.Namespace) -> int:
    """Run Python ORM code against the local replica (local replica only; never production)."""
    ctx = _resolve_workspace(args)
    db = ctx.effective_db_name

    if "_seed_" in db:
        msg = (
            f"Refusing to execute shell on untouchable seed database {db!r}. "
            "Clone to a work database first (e.g., db-clone)."
        )
        raise CliError(msg, code=2)

    script_source = _optional_str(args, "file") or _optional_str(args, "script")
    if not script_source:
        msg = "Script must be provided via --file PATH or '-' from stdin."
        raise CliError(msg, code=2)

    if script_source == "-":
        script_code = sys.stdin.read()
    else:
        spath = Path(script_source)
        if not spath.is_file():
            msg = f"Script file not found: {spath}"
            raise CliError(msg)
        script_code = spath.read_text(encoding="utf-8")

    rollback = _require_bool(args, "rollback")
    suffix = "\nenv.cr.rollback()\n" if rollback else "\nenv.cr.commit()\n"
    full_script = script_code.rstrip() + "\n" + suffix

    _ensure_podman()
    web_status = _run(
        [
            "podman",
            "ps",
            "--filter",
            f"name={DEFAULT_WEB_CONTAINER}",
            "--filter",
            "status=running",
            "--format",
            "{{.Names}}",
        ],
        check=False,
    ).stdout.strip()
    if not web_status:
        msg = (
            f"Container {DEFAULT_WEB_CONTAINER!r} is not running. "
            "Please start the development server first using 'dev'."
        )
        raise CliError(msg, code=1)

    cmd = [
        "podman",
        "exec",
        "-i",
        DEFAULT_WEB_CONTAINER,
        "odoo",
        "shell",
        "-c",
        "/etc/odoo/odoo.conf",
        "-d",
        db,
        "--no-http",
    ]
    proc = subprocess.run(  # noqa: S603 - controlled podman exec odoo shell execution
        cmd,
        input=full_script,
        text=True,
        check=False,
    )
    return proc.returncode


def cmd_auth_temp(args: argparse.Namespace) -> int:
    """Set temporary random password for user on local replica (local replica only)."""
    ctx = _resolve_workspace(args)
    db = ctx.effective_db_name

    if "_seed_" in db:
        msg = (
            f"Refusing to execute auth-temp on untouchable seed database {db!r}. "
            "Clone to a work database first (e.g., db-clone)."
        )
        raise CliError(msg, code=2)

    _ensure_runtime_pod(ctx)

    login_arg = _optional_str(args, "login")
    if login_arg:
        quoted_login = _quote_literal(login_arg)
        find_sql = (
            f"SELECT id, login, password FROM res_users "  # noqa: S608 - login quoted by _quote_literal
            f"WHERE login = {quoted_login};"
        )
    else:
        find_sql = "SELECT id, login, password FROM res_users WHERE id = 2;"

    rows = _exec_sql_json(find_sql, db=db)
    if not rows:
        target_desc = f"with login {login_arg!r}" if login_arg else "with id 2"
        msg = f"User {target_desc} not found in database {db!r}."
        raise CliError(msg, code=1)

    user_row = rows[0]
    user_id = int(cast("int | str", user_row["id"]))
    user_login = str(user_row["login"])
    current_hash = str(user_row.get("password") or "")

    state_dir = _get_state_dir()
    auth_dir = state_dir / "auth"
    backup_path = auth_dir / f"{db}__{user_id}.json"

    if not backup_path.is_file():
        backup_data = {
            "db": db,
            "user_id": user_id,
            "login": user_login,
            "password_hash": current_hash,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        _write_file_0600(
            backup_path,
            json.dumps(backup_data, indent=2, sort_keys=True, ensure_ascii=False),
        )

    temp_password = secrets.token_urlsafe(18)
    salt = secrets.token_bytes(16)
    new_hash = _passlib_pbkdf2_sha512(temp_password, salt)

    update_sql = (
        f"UPDATE res_users SET password = {_quote_literal(new_hash)} "  # noqa: S608 - hash quoted, user_id is int
        f"WHERE id = {user_id};"
    )
    _ = _exec_sql(update_sql, db=db, readonly=False)

    url = f"http://127.0.0.1:{DEFAULT_HTTP_PORT}/web/login?db={db}"
    restore_cmd = (
        f"cli.py auth-restore --db {db} --login {user_login}"
        if login_arg
        else f"cli.py auth-restore --db {db}"
    )

    json_mode = _require_bool(args, "json")
    if json_mode:
        print(
            json.dumps(
                {
                    "login": user_login,
                    "password": temp_password,
                    "url": url,
                    "restore": restore_cmd,
                    "restore_with": restore_cmd,
                },
                indent=2,
            )
        )
    else:
        print(f"Login:    {user_login}")
        print(f"Password: {temp_password}")
        print(f"URL:      {url}")
        print(f"restore with: {restore_cmd}")

    return 0


def cmd_auth_restore(args: argparse.Namespace) -> int:
    """Restore original password hash for user on local replica (local replica only)."""
    ctx = _resolve_workspace(args)
    db = ctx.effective_db_name

    if "_seed_" in db:
        msg = (
            f"Refusing to execute auth-restore on untouchable seed database {db!r}. "
            "Clone to a work database first (e.g., db-clone)."
        )
        raise CliError(msg, code=2)

    _ensure_runtime_pod(ctx)

    login_arg = _optional_str(args, "login")
    state_dir = _get_state_dir()
    auth_dir = state_dir / "auth"

    if login_arg:
        quoted_login = _quote_literal(login_arg)
        find_sql = (
            f"SELECT id, login FROM res_users "  # noqa: S608 - login quoted by _quote_literal
            f"WHERE login = {quoted_login};"
        )
        rows = _exec_sql_json(find_sql, db=db)
        if not rows:
            msg = f"User with login {login_arg!r} not found in database {db!r}."
            raise CliError(msg, code=1)
        user_id = int(cast("int | str", rows[0]["id"]))
        user_login = str(rows[0]["login"])
        backup_path = auth_dir / f"{db}__{user_id}.json"
    else:
        backup_path = auth_dir / f"{db}__2.json"
        if not backup_path.is_file() and auth_dir.is_dir():
            candidates = sorted(auth_dir.glob(f"{db}__*.json"))
            if len(candidates) == 1:
                backup_path = candidates[0]

    if not backup_path.is_file():
        msg = f"No auth backup found for database {db!r}."
        raise CliError(msg, code=1)

    try:
        backup_data = cast(
            "dict[str, object]",
            json.loads(backup_path.read_text(encoding="utf-8")),
        )
    except (json.JSONDecodeError, OSError) as exc:
        msg = f"Failed to read auth backup file: {backup_path}"
        raise CliError(msg, code=1) from exc

    user_id = int(cast("int | str", backup_data["user_id"]))
    user_login = str(backup_data.get("login") or login_arg or "admin")
    original_hash = str(backup_data.get("password_hash") or "")

    update_sql = (
        f"UPDATE res_users SET password = {_quote_literal(original_hash)} "  # noqa: S608 - hash quoted, user_id is int
        f"WHERE id = {user_id};"
    )
    _ = _exec_sql(update_sql, db=db, readonly=False)

    verify_sql = f"SELECT password FROM res_users WHERE id = {user_id};"  # noqa: S608 - id
    verify_rows = _exec_sql_json(verify_sql, db=db)
    actual_hash = str(verify_rows[0].get("password") or "") if verify_rows else None
    if actual_hash != original_hash:
        msg = (
            f"Verification failed: password hash in database does not match "
            f"backup for {user_login!r}."
        )
        raise CliError(msg, code=1)

    try:
        backup_path.unlink()
    except OSError as exc:
        msg = f"Failed to delete backup file after verification: {backup_path}"
        raise CliError(msg, code=1) from exc

    json_mode = _require_bool(args, "json")
    if json_mode:
        print(
            json.dumps(
                {
                    "status": "restored",
                    "login": user_login,
                    "database": db,
                },
                indent=2,
            )
        )
    else:
        print(f"restored {user_login} on {db}")

    return 0


def cmd_health(args: argparse.Namespace) -> int:
    """Probe health and readiness of the local Odoo web server."""
    port = _require_int(args, "port", DEFAULT_HTTP_PORT)
    wait_sec = max(0, _require_int(args, "wait", 0))
    json_mode = _require_bool(args, "json")

    url = f"http://127.0.0.1:{port}/web/login"
    start_time = time.monotonic()

    def _probe_once() -> tuple[bool, str]:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "odoo-ops-health"},
        )
        try:
            with urllib.request.urlopen(req, timeout=3.0) as resp:  # noqa: S310 - internal loopback readiness probe
                status = resp.status
                if status == 200:
                    return True, str(status)
                return False, f"HTTP {status}"
        except urllib.error.HTTPError as err:
            if err.code == 200:
                return True, str(err.code)
            return False, f"HTTP {err.code}"
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            return False, str(err)

    ready = False
    reason_or_status = ""
    while True:
        ready, reason_or_status = _probe_once()
        if ready:
            break
        if wait_sec <= 0 or (time.monotonic() - start_time) >= wait_sec:
            break
        time.sleep(min(2.0, max(0.1, wait_sec - (time.monotonic() - start_time))))

    if ready:
        if json_mode:
            print(json.dumps({"ready": True, "status": 200, "url": url}))
        else:
            print(f"ready {reason_or_status}")
        return 0

    if json_mode:
        print(json.dumps({"ready": False, "reason": reason_or_status, "url": url}))
    else:
        print(f"not ready: {reason_or_status}")
    return 1


def cmd_prune(args: argparse.Namespace) -> int:
    """Remove stale odoo-test-* containers."""
    _ensure_podman()
    json_mode = _require_bool(args, "json")

    res = _run(
        ["podman", "ps", "-a", "--filter", "name=odoo-test-", "--format", "{{.Names}}"],
        check=False,
    )
    containers = [
        line.strip().lstrip("/")
        for line in res.stdout.splitlines()
        if line.strip().lstrip("/").startswith("odoo-test-")
    ]

    if containers:
        _ = _run(["podman", "rm", "-f", *containers], check=False)

    if json_mode:
        print(json.dumps({"removed": containers, "count": len(containers)}, indent=2))
    elif containers:
        print(f"Removed {len(containers)} test container(s):")
        for c in containers:
            print(f"  - {c}")
    else:
        print("No test containers to prune.")
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
    _ = p_dev.add_argument("--db", help="Target database name override")

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
    _ = p_test.add_argument(
        "--baseline",
        nargs="?",
        const="HEAD",
        default=None,
        metavar="REF",
        help=(
            "Compare test results against a baseline git commit or ref "
            "(default: HEAD). Baseline suite runs first so DB ends at "
            "current code schema."
        ),
    )

    # Lint Command
    p_lint = subparsers.add_parser(
        "lint",
        parents=[parent_parser],
        help="Run Python (Ruff) and XML view linters on profile lint_modules",
    )
    _ = p_lint.add_argument(
        "target",
        default="crm",
        nargs="?",
        help="Module name or workflow profile key (default: crm)",
    )
    _ = p_lint.add_argument(
        "--fix", action="store_true", help="Auto-fix safe Python lint violations"
    )
    _ = p_lint.add_argument(
        "--strict",
        action="store_true",
        help="Treat XML view warnings as errors (exit code 1 on warnings)",
    )
    _ = p_lint.add_argument(
        "--skip-views",
        action="store_true",
        help="Skip XML view linting and only run Ruff Python checks",
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
    p_stop = subparsers.add_parser(
        "stop",
        parents=[parent_parser],
        help="Stop and tear down the Odoo Podman pod and containers",
    )
    _ = p_stop.add_argument(
        "--web",
        action="store_true",
        help="Stop only the odoo-web container (keep pod and postgres running)",
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
    _ = p_logs.add_argument(
        "-c",
        "--container",
        choices=["web", "db", "test"],
        default="web",
        help="Target container to tail: web, db, or test (default: web)",
    )

    # Env Inspect
    p_env = subparsers.add_parser(
        "env",
        parents=[parent_parser],
        help="Inspect workspace, runtime, and container environment",
    )
    _ = p_env.add_argument("--db", help="Target database name")

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
    _ = p_query.add_argument(
        "sql",
        nargs="?",
        default=None,
        help="SQL query string, or '-' to read from stdin (prefer --file for long queries)",
    )
    _ = p_query.add_argument(
        "--file",
        "-f",
        help="Read SQL from file, or '-' to read from stdin (prefer temp file for long queries)",
    )
    _ = p_query.add_argument("--db", help="Target database name")
    _ = p_query.add_argument(
        "--unsafe", action="store_true", help="Allow DDL/DML mutation queries"
    )

    # DB List
    _ = subparsers.add_parser(
        "db-list",
        parents=[parent_parser],
        help="List local databases and their disk sizes (excluding templates/postgres)",
    )

    # DB Drop
    p_drop = subparsers.add_parser(
        "db-drop",
        parents=[parent_parser],
        help="Drop a local PostgreSQL database and its filestore",
    )
    _ = p_drop.add_argument("name", help="Database name to drop")
    _ = p_drop.add_argument(
        "--force", action="store_true", help="Force drop of database (required)"
    )
    _ = p_drop.add_argument(
        "--allow-seed",
        action="store_true",
        help="Allow dropping a seed database containing '_seed_'",
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

    # DB Restore
    p_restore = subparsers.add_parser(
        "db-restore",
        parents=[parent_parser],
        help="Restore a plain or gzip SQL dump into a new local replica database",
    )
    _ = p_restore.add_argument("dump", help="Path to the .sql or .sql.gz dump")
    _ = p_restore.add_argument("target", help="Target database name")
    _ = p_restore.add_argument(
        "--force", action="store_true", help="Drop target if already exists"
    )

    # Shell Command
    p_shell = subparsers.add_parser(
        "shell",
        parents=[parent_parser],
        help="Run Python ORM code against the local replica (local replica only; never production)",
    )
    _ = p_shell.add_argument(
        "script",
        nargs="?",
        default=None,
        help="Path to Python script or '-' from stdin (optional if --file given)",
    )
    _ = p_shell.add_argument(
        "--file",
        "-f",
        help="Path to Python script, or '-' to read from stdin",
    )
    _ = p_shell.add_argument("--db", help="Target database name")
    _ = p_shell.add_argument(
        "--rollback",
        action="store_true",
        help="Rollback transaction at script end instead of committing",
    )

    # Health Command
    p_health = subparsers.add_parser(
        "health",
        parents=[parent_parser],
        help="Probe health and readiness of the local Odoo web server",
    )
    _ = p_health.add_argument(
        "--port",
        type=int,
        default=DEFAULT_HTTP_PORT,
        help=f"Port of the Odoo web server (default: {DEFAULT_HTTP_PORT})",
    )
    _ = p_health.add_argument(
        "--wait",
        type=int,
        default=0,
        help="Wait/poll timeout in seconds until ready (default: 0)",
    )

    # Prune Command
    _ = subparsers.add_parser(
        "prune",
        parents=[parent_parser],
        help="Remove stale odoo-test-* containers",
    )

    # Auth-Temp Command
    p_auth_temp = subparsers.add_parser(
        "auth-temp",
        parents=[parent_parser],
        help="Set temporary random password on local replica (requires pod running)",
        description=(
            "Set temporary random password for user on local replica. "
            "Requires the local pod running (same as db-query)."
        ),
    )
    _ = p_auth_temp.add_argument("--db", help="Target database name override")
    _ = p_auth_temp.add_argument(
        "--login", help="User login (default: user id 2 / base.user_admin)"
    )

    # Auth-Restore Command
    p_auth_restore = subparsers.add_parser(
        "auth-restore",
        parents=[parent_parser],
        help="Restore original password hash on local replica (requires pod running)",
        description=(
            "Restore original password hash for user on local replica. "
            "Requires the local pod running (same as db-query)."
        ),
    )
    _ = p_auth_restore.add_argument("--db", help="Target database name override")
    _ = p_auth_restore.add_argument(
        "--login", help="User login (default: user id 2 / base.user_admin)"
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
        "db-restore": cmd_db_restore,
        "db-list": cmd_db_list,
        "db-drop": cmd_db_drop,
        "shell": cmd_shell,
        "health": cmd_health,
        "prune": cmd_prune,
        "auth-temp": cmd_auth_temp,
        "auth-restore": cmd_auth_restore,
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
