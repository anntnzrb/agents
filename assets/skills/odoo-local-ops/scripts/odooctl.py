#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# ///
"""Local Odoo workspace inspector and PostgreSQL helper."""

from __future__ import annotations

import argparse
import ast
import configparser
import csv
import io
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any, Iterable

SCRIPT_DIR = Path(__file__).resolve().parent
SQL_DIR = SCRIPT_DIR / "sql"
ROOT_MARKERS = ("odoo.conf", "odoo-bin", "addons", "docker-compose.yml")
DEFAULT_COMPOSE_RUNTIME = Path("/Users/Shared/odoo17")
RUNTIME_DIR_ENV = "ODOO17_RUNTIME_DIR"
LOCAL_DEFAULT_DB = "etech"
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
    "patch",
    "post",
    "put",
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
PROJECT_TOKEN_RE = re.compile(r"\$PROJECT_DIR\$")


class CliError(RuntimeError):
    """Raised for actionable command failures."""


@dataclass(frozen=True)
class RuntimeContext:
    backend: str
    root: Path
    config_path: Path
    config: dict[str, str]
    addons_paths: list[Path]
    compose_command: tuple[str, ...] | None = None
    env: dict[str, str] | None = None


@dataclass(frozen=True)
class WorkspaceContext:
    root: Path
    config_path: Path
    config: dict[str, str]
    addons_paths: list[Path]
    effective_db_name: str | None
    runtime: RuntimeContext


def _strip_quotes(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _normalize_config_value(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if cleaned == "":
        return None
    if cleaned.lower() in {"false", "none", "null"}:
        return None
    return cleaned


def _redact_mapping(data: dict[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, value in data.items():
        lowered = key.lower()
        if any(token in lowered for token in SECRET_TOKENS):
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


def _emit_text(value: Any, indent: int = 0) -> None:
    pad = " " * indent
    if isinstance(value, dict):
        for key in sorted(value):
            item = value[key]
            if isinstance(item, (dict, list)):
                print(f"{pad}{key}:")
                _emit_text(item, indent + 2)
            else:
                print(f"{pad}{key}: {item}")
        return
    if isinstance(value, list):
        for item in value:
            if isinstance(item, (dict, list)):
                print(f"{pad}-")
                _emit_text(item, indent + 2)
            else:
                print(f"{pad}- {item}")
        return
    print(f"{pad}{value}")


def emit_result(args: argparse.Namespace, payload: Any) -> int:
    if getattr(args, "json", False):
        json.dump(
            payload, sys.stdout, indent=2, ensure_ascii=False, default=_json_default
        )
        sys.stdout.write("\n")
    else:
        _emit_text(payload)
    return 0


def _fail(
    args: argparse.Namespace | None, message: str, *, checked: list[str] | None = None
) -> int:
    payload: dict[str, Any] = {"error": message}
    if checked:
        payload["checked"] = checked
    if args is not None and getattr(args, "json", False):
        json.dump(payload, sys.stderr, indent=2, ensure_ascii=False)
        sys.stderr.write("\n")
    else:
        print(f"odooctl: {message}", file=sys.stderr)
        if checked:
            for item in checked:
                print(f"  checked: {item}", file=sys.stderr)
    return 2


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    parts = [part.strip() for part in value.split(",")]
    return [part for part in parts if part]


def _replace_project_tokens(value: str | None, root: Path) -> str | None:
    if not value:
        return value
    # Use a callable replacement so Windows backslashes are treated literally
    # instead of as regex replacement escapes (for example "\U" in "\Users").
    return PROJECT_TOKEN_RE.sub(lambda _match: str(root), value)


def _windows_to_local_path(text: str) -> Path:
    raw = _replace_project_tokens(text, Path.cwd()) or text
    candidate = Path(raw).expanduser()
    if candidate.exists():
        return candidate.resolve()
    if len(raw) >= 3 and raw[1:3] == ":\\":
        drive = raw[0].lower()
        suffix = raw[3:].replace("\\", "/")
        mapped = Path(f"/mnt/{drive}/{suffix}")
        if mapped.exists():
            return mapped.resolve()
        return mapped
    if len(raw) >= 3 and raw[1:3] == ":/":
        drive = raw[0].lower()
        suffix = raw[3:]
        mapped = Path(f"/mnt/{drive}/{suffix}")
        if mapped.exists():
            return mapped.resolve()
        return mapped
    return candidate


def _safe_child_dirs(path: Path) -> list[Path]:
    try:
        return sorted(
            child
            for child in path.iterdir()
            if not child.name.startswith(".") and child.is_dir()
        )
    except OSError:
        return []


def _looks_like_host_workspace(path: Path) -> bool:
    try:
        return (path / "odoo.conf").is_file() or (
            (path / "odoo-bin").is_file()
            and ((path / "addons").is_dir() or (path / "odoo" / "addons").is_dir())
        )
    except OSError:
        return False


def _looks_like_compose_runtime(path: Path) -> bool:
    try:
        return (path / "docker-compose.yml").is_file() and (
            path / "config" / "odoo.conf"
        ).is_file()
    except OSError:
        return False


def _discover_root(start: Path) -> Path:
    start = start.resolve()
    seen: set[str] = set()
    for anchor in (start, *start.parents):
        for candidate in (anchor, *_safe_child_dirs(anchor)):
            key = str(candidate)
            if key in seen:
                continue
            seen.add(key)
            if _looks_like_host_workspace(candidate) or _looks_like_compose_runtime(
                candidate
            ):
                return candidate
    raise CliError(
        f"could not discover Odoo workspace from {start}; run from inside the Odoo install tree/runtime or pass --root"
    )


def _read_config(config_path: Path) -> dict[str, str]:
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    try:
        loaded = parser.read(config_path, encoding="utf-8")
    except configparser.Error as exc:
        raise CliError(f"failed to parse {config_path}: {exc}") from exc
    if not loaded or "options" not in parser:
        raise CliError(f"missing [options] section in {config_path}")
    return {key: value for key, value in parser["options"].items()}


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise CliError(f"failed to read env file {path}: {exc}") from exc
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if not key:
            continue
        values[key] = _strip_quotes(value.strip()) or ""
    return values


def _compose_env(runtime_root: Path) -> dict[str, str]:
    values = _read_env_file(runtime_root / ".env.example")
    values.update(_read_env_file(runtime_root / ".env"))
    return values


def _env_path(runtime_root: Path, env: dict[str, str], key: str, default: str) -> Path:
    raw = env.get(key, default)
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = runtime_root / path
    return path.resolve()


def _compose_candidates(start: Path) -> list[Path]:
    candidates: list[Path] = []
    explicit = os.environ.get(RUNTIME_DIR_ENV)
    if explicit:
        candidates.append(Path(explicit).expanduser())
    for anchor in (start.resolve(), *start.resolve().parents):
        candidates.append(anchor)
        candidates.append(anchor / "odoo17")
        candidates.append(anchor.parent / "odoo17")
    candidates.append(DEFAULT_COMPOSE_RUNTIME)

    seen: set[str] = set()
    unique: list[Path] = []
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            resolved = candidate
        key = str(resolved)
        if key not in seen:
            seen.add(key)
            unique.append(resolved)
    return unique


def _run_subprocess(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
    timeout: int | float | None = None,
    quiet: bool = False,
) -> subprocess.CompletedProcess[str]:
    kwargs: dict[str, Any] = {
        "text": True,
        "shell": False,
        "cwd": cwd,
        "env": env,
    }
    if quiet:
        kwargs["stdout"] = subprocess.DEVNULL
        kwargs["stderr"] = subprocess.DEVNULL
    else:
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE
    if input_text is not None:
        kwargs["stdin"] = subprocess.PIPE

    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kwargs["start_new_session"] = True

    process = subprocess.Popen(command, **kwargs)
    try:
        stdout, stderr = process.communicate(input=input_text, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        if os.name == "nt":
            process.kill()
        else:
            try:
                os.killpg(process.pid, 15)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, 9)
                except ProcessLookupError:
                    pass
        stdout, stderr = process.communicate()
        raise CliError(
            f"command timed out after {exc.timeout} seconds: {' '.join(command[:4])}"
        ) from exc
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _discover_compose_runtime(start: Path, explicit: str | None) -> Path | None:
    if explicit:
        runtime = Path(explicit).expanduser().resolve()
        if _looks_like_compose_runtime(runtime):
            return runtime
        raise CliError(
            f"runtime directory does not look like an Odoo Compose runtime: {runtime}"
        )
    for candidate in _compose_candidates(start):
        if _looks_like_compose_runtime(candidate):
            return candidate
    return None


def _resolve_compose_command() -> tuple[str, ...] | None:
    docker = shutil.which("docker")
    if docker:
        result = _run_subprocess([docker, "compose", "version"], quiet=True)
        if result.returncode == 0:
            return (docker, "compose")
    docker_compose = shutil.which("docker-compose")
    if docker_compose:
        return (docker_compose,)
    return None


def _compose_runtime(start: Path, explicit: str | None) -> RuntimeContext | None:
    runtime_root = _discover_compose_runtime(start, explicit)
    if runtime_root is None:
        return None
    env = _compose_env(runtime_root)
    config_dir = _env_path(runtime_root, env, "ODOO17_CONFIG_DIR", "./config")
    config_path = config_dir / "odoo.conf"
    if not config_path.is_file():
        raise CliError(f"Compose runtime config file not found: {config_path}")
    config = _read_config(config_path)
    source_dir = _env_path(
        runtime_root, env, "ODOO17_SOURCE_DIR", "./source/odoo-17.0+e.20260527"
    )
    custom_addons = _env_path(
        runtime_root, env, "ODOO17_CUSTOM_ADDONS_DIR", "../etech/odoo/addons"
    )
    addons_paths = [
        path
        for path in (source_dir / "odoo" / "addons", custom_addons)
        if path.is_dir()
    ]
    compose_command = _resolve_compose_command()
    if compose_command is None:
        raise CliError(
            "Docker Compose not found; install Docker/OrbStack with `docker compose` or `docker-compose`"
        )
    return RuntimeContext(
        backend="compose",
        root=runtime_root,
        config_path=config_path,
        config=config,
        addons_paths=addons_paths,
        compose_command=compose_command,
        env=env,
    )


def _host_runtime(root: Path, config_path: Path) -> RuntimeContext:
    config = _read_config(config_path)
    return RuntimeContext(
        backend="windows-host",
        root=root,
        config_path=config_path,
        config=config,
        addons_paths=_resolve_addons_paths(root, config),
    )


def _resolve_addons_paths(root: Path, config: dict[str, str]) -> list[Path]:
    raw = config.get("addons_path", "")
    paths: list[Path] = []
    seen: set[str] = set()
    for item in _split_csv(raw):
        path = _windows_to_local_path(item)
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        paths.append(path)
    if not paths and (root / "addons").is_dir():
        paths.append(root / "addons")
    return paths


def _resolve_effective_db_name(
    args: argparse.Namespace, runtime: RuntimeContext
) -> str | None:
    explicit = _normalize_config_value(getattr(args, "db", None))
    if explicit:
        return explicit
    configured = _normalize_config_value(runtime.config.get("db_name"))
    if configured:
        return configured
    if runtime.backend == "compose" and runtime.root == DEFAULT_COMPOSE_RUNTIME:
        return LOCAL_DEFAULT_DB
    return None


def load_workspace(args: argparse.Namespace) -> WorkspaceContext:
    start = Path(args.root).expanduser() if args.root else Path.cwd()
    explicit_runtime = getattr(args, "runtime_dir", None)
    runtime = _compose_runtime(start, explicit_runtime)
    if runtime is None:
        root = _discover_root(start)
        config_path = (
            Path(args.config).expanduser().resolve()
            if args.config
            else root / "odoo.conf"
        )
        if not config_path.is_file():
            raise CliError(f"config file not found: {config_path}")
        runtime = _host_runtime(root, config_path)
    effective_db_name = _resolve_effective_db_name(args, runtime)
    return WorkspaceContext(
        root=runtime.root,
        config_path=runtime.config_path,
        config=runtime.config,
        addons_paths=runtime.addons_paths,
        effective_db_name=effective_db_name,
        runtime=runtime,
    )


def _find_module_dir(ctx: WorkspaceContext, module: str) -> Path:
    for addons_dir in ctx.addons_paths:
        candidate = addons_dir / module
        if (candidate / "__manifest__.py").is_file():
            return candidate
    raise CliError(f"module {module!r} not found in configured addons_path")


def _read_manifest(module_dir: Path) -> dict[str, Any]:
    manifest_path = module_dir / "__manifest__.py"
    try:
        tree = ast.parse(
            manifest_path.read_text(encoding="utf-8"), filename=str(manifest_path)
        )
    except OSError as exc:
        raise CliError(f"failed to read {manifest_path}: {exc}") from exc
    except SyntaxError as exc:
        raise CliError(f"invalid Python in {manifest_path}: {exc}") from exc
    if not tree.body or not isinstance(tree.body[0], ast.Expr):
        raise CliError(
            f"manifest {manifest_path} does not contain a top-level dict literal"
        )
    try:
        value = ast.literal_eval(tree.body[0].value)
    except Exception as exc:
        raise CliError(
            f"manifest {manifest_path} is not a pure literal dict: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise CliError(f"manifest {manifest_path} is not a dict")
    return value


def _iter_nearby_psql_candidates(start: Path) -> Iterable[Path]:
    seen: set[str] = set()
    for anchor in (start.resolve(), *start.resolve().parents):
        candidates = [anchor / "psql.exe", anchor / "bin" / "psql.exe"]
        for child in _safe_child_dirs(anchor):
            candidates.append(child / "psql.exe")
            candidates.append(child / "bin" / "psql.exe")
        for candidate in candidates:
            key = str(candidate)
            if key in seen:
                continue
            seen.add(key)
            yield candidate


def _discover_psql(
    args: argparse.Namespace, ctx: WorkspaceContext
) -> tuple[str, list[str]]:
    checked: list[str] = []
    explicit = getattr(args, "psql", None)
    if explicit:
        path = str(Path(explicit).expanduser())
        checked.append(path)
        if Path(path).exists() or shutil.which(path):
            return path, checked
        raise CliError(f"explicit psql executable not found: {path}")

    for candidate in _iter_nearby_psql_candidates(ctx.root):
        checked.append(str(candidate))
        if candidate.is_file():
            return str(candidate), checked

    pg_path = _normalize_config_value(ctx.config.get("pg_path"))
    if pg_path:
        candidate = _windows_to_local_path(pg_path) / "psql.exe"
        checked.append(str(candidate))
        if candidate.exists():
            return str(candidate), checked

    where_exe = shutil.which("where.exe")
    if where_exe:
        checked.append("PATH lookup via where.exe psql.exe")
        result = subprocess.run(
            [where_exe, "psql.exe"], capture_output=True, text=True, shell=False
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                found = line.strip()
                if found:
                    return found, checked

    posix_psql = shutil.which("psql")
    if posix_psql:
        checked.append("PATH lookup via psql")
        return posix_psql, checked

    raise CliError(
        "psql executable not found; use --psql, run from the Odoo install tree, or configure pg_path",
        checked,
    )


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _load_sql_recipe(name: str, *, params: dict[str, Any], fallback: str) -> str:
    recipe_path = SQL_DIR / name
    has_file = recipe_path.is_file()
    if has_file:
        try:
            template = recipe_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise CliError(f"failed to read SQL recipe {recipe_path}: {exc}") from exc
    else:
        template = fallback

    rendered = template
    for key, value in params.items():
        rendered = rendered.replace(f":'{key}'", str(value))
    try:
        return rendered.format(**params)
    except KeyError as exc:
        source = recipe_path if has_file else name
        raise CliError(
            f"SQL recipe {source} references unknown placeholder {exc}"
        ) from exc


def _strip_sql_comments_and_literals(sql: str) -> str:
    sql = re.sub(r"--.*?$", "", sql, flags=re.MULTILINE)
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    sql = re.sub(r"\$[^$]*\$.*?\$[^$]*\$", "''", sql, flags=re.DOTALL)
    sql = re.sub(r"'(?:''|[^'])*'", "''", sql)
    sql = re.sub(r'"(?:""|[^"])*"', '""', sql)
    return sql


def _guard_read_only_sql(sql: str) -> None:
    stripped = _strip_sql_comments_and_literals(sql)
    if stripped.lstrip().startswith("\\"):
        raise CliError("psql meta-commands are not allowed in read-only ad-hoc queries")
    match = MUTATING_SQL_RE.search(stripped)
    if match:
        raise CliError(
            f"read-only query rejected due to mutating SQL token: {match.group(1)}"
        )


def _compose_run_psql(
    args: argparse.Namespace,
    ctx: WorkspaceContext,
    *,
    sql: str,
    read_only: bool,
    row_limit: int | None = None,
) -> dict[str, Any]:
    runtime = ctx.runtime
    if runtime.compose_command is None:
        raise CliError("Compose runtime has no Docker Compose command")
    db_name = ctx.effective_db_name
    if not db_name:
        raise CliError(
            "no database resolved; pass --db or configure the Compose runtime database"
        )
    if read_only:
        _guard_read_only_sql(sql)

    postgres_user = (
        (runtime.env or {}).get("POSTGRES_USER")
        or (runtime.env or {}).get("ODOO_DB_USER")
        or "odoo"
    )
    command = [
        *runtime.compose_command,
        "exec",
        "-T",
        "-e",
        "PGCONNECT_TIMEOUT=10",
    ]
    if read_only:
        command.extend(["-e", "PGOPTIONS=-c default_transaction_read_only=on"])
    command.extend(
        [
            "db",
            "psql",
            "-X",
            "-w",
            "--csv",
            "-v",
            "ON_ERROR_STOP=1",
            "-P",
            "footer=off",
            "-U",
            postgres_user,
            "-d",
            db_name,
            "-f",
            "-",
        ]
    )

    result = _run_subprocess(
        command,
        input_text=sql,
        cwd=runtime.root,
        timeout=30,
    )
    if result.returncode != 0:
        stderr = (result.stderr or result.stdout).strip()
        raise CliError(f"psql failed: {stderr or 'unknown error'}")

    rows: list[dict[str, str]] = []
    output = result.stdout.strip()
    if output:
        reader = csv.DictReader(io.StringIO(output))
        rows = [dict(row) for row in reader]
        if row_limit is not None:
            rows = rows[:row_limit]
    return {
        "database": db_name,
        "runtime": {"backend": runtime.backend, "root": str(runtime.root)},
        "rows": rows,
        "row_count": len(rows),
        "psql": "docker-compose:db/psql",
        "checked": ["Docker Compose service db"],
        "stdout": output,
    }


def _host_run_psql(
    args: argparse.Namespace,
    ctx: WorkspaceContext,
    *,
    sql: str,
    read_only: bool,
    row_limit: int | None = None,
) -> dict[str, Any]:
    db_name = ctx.effective_db_name
    if not db_name:
        raise CliError("no database resolved; pass --db or set db_name in odoo.conf")
    psql, checked = _discover_psql(args, ctx)
    if read_only:
        _guard_read_only_sql(sql)

    command = [
        psql,
        "-X",
        "-w",
        "--csv",
        "-v",
        "ON_ERROR_STOP=1",
        "-P",
        "footer=off",
        "-d",
        db_name,
    ]
    if host := _normalize_config_value(ctx.config.get("db_host")):
        command.extend(["-h", host])
    if port := _normalize_config_value(ctx.config.get("db_port")):
        command.extend(["-p", port])
    if user := _normalize_config_value(ctx.config.get("db_user")):
        command.extend(["-U", user])
    command.extend(["-f", "-"])

    env = os.environ.copy()
    env.setdefault("PGCONNECT_TIMEOUT", "10")
    password = _normalize_config_value(ctx.config.get("db_password"))
    if password:
        env.setdefault("PGPASSWORD", password)
    if read_only:
        existing_pgoptions = env.get("PGOPTIONS", "").strip()
        read_only_option = "-c default_transaction_read_only=on"
        env["PGOPTIONS"] = f"{existing_pgoptions} {read_only_option}".strip()

    result = _run_subprocess(
        command,
        input_text=sql,
        env=env,
        timeout=30,
    )
    if result.returncode != 0:
        stderr = (result.stderr or result.stdout).strip()
        raise CliError(f"psql failed: {stderr or 'unknown error'}")

    rows: list[dict[str, str]] = []
    output = result.stdout.strip()
    if output:
        reader = csv.DictReader(io.StringIO(output))
        rows = [dict(row) for row in reader]
        if row_limit is not None:
            rows = rows[:row_limit]
    return {
        "database": db_name,
        "runtime": {"backend": ctx.runtime.backend, "root": str(ctx.runtime.root)},
        "rows": rows,
        "row_count": len(rows),
        "psql": psql,
        "checked": checked,
        "stdout": output,
    }


def _run_psql(
    args: argparse.Namespace,
    ctx: WorkspaceContext,
    *,
    sql: str,
    read_only: bool,
    row_limit: int | None = None,
) -> dict[str, Any]:
    if ctx.runtime.backend == "compose":
        return _compose_run_psql(
            args, ctx, sql=sql, read_only=read_only, row_limit=row_limit
        )
    return _host_run_psql(args, ctx, sql=sql, read_only=read_only, row_limit=row_limit)


def _module_filter_clause(module: str) -> str:
    literal = _sql_literal(module)
    return textwrap.dedent(
        f"""
        EXISTS (
            SELECT 1
            FROM regexp_split_to_table(replace(COALESCE(modules, ''), ' ', ''), ',') AS module_name
            WHERE module_name = {literal}
        )
        """
    ).strip()


def _query_recipe(
    args: argparse.Namespace,
    ctx: WorkspaceContext,
    name: str,
    *,
    fallback: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    sql = _load_sql_recipe(name, params=params, fallback=fallback)
    return _run_psql(args, ctx, sql=sql, read_only=True)


def _route_expr_value(node: ast.AST) -> Any:
    try:
        return ast.literal_eval(node)
    except Exception:
        if isinstance(node, ast.Name):
            return node.id
        return None


@dataclass(frozen=True)
class RouteRecord:
    module: str
    controller: str | None
    function: str
    paths: list[str]
    methods: list[str]
    auth: str | None
    route_type: str | None
    source: str
    line: int
    write_signals: list[str]


class _WriteSignalVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.signals: set[str] = set()

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in WRITE_HINTS:
            self.signals.add(func.attr)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr in {"commit", "rollback"}:
            self.signals.add(node.attr)
        self.generic_visit(node)


class _RouteCollector(ast.NodeVisitor):
    def __init__(self, path: Path, module: str) -> None:
        self.path = path
        self.module = module
        self.routes: list[RouteRecord] = []
        self.class_stack: list[tuple[str, bool]] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        is_controller = any(
            (isinstance(base, ast.Attribute) and base.attr == "Controller")
            or (isinstance(base, ast.Name) and base.id == "Controller")
            for base in node.bases
        )
        self.class_stack.append((node.name, is_controller))
        self.generic_visit(node)
        self.class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._maybe_collect(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._maybe_collect(node)
        self.generic_visit(node)

    def _maybe_collect(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        controller_name = self.class_stack[-1][0] if self.class_stack else None
        inside_controller = self.class_stack[-1][1] if self.class_stack else False
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            func = decorator.func
            is_route = (isinstance(func, ast.Name) and func.id == "route") or (
                isinstance(func, ast.Attribute) and func.attr == "route"
            )
            if not is_route:
                continue
            if not inside_controller and controller_name is not None:
                continue
            paths: list[str] = []
            methods: list[str] = []
            auth: str | None = None
            route_type: str | None = None
            if decorator.args:
                first = _route_expr_value(decorator.args[0])
                if isinstance(first, str):
                    paths = [first]
                elif isinstance(first, (list, tuple)):
                    paths = [item for item in first if isinstance(item, str)]
            for keyword in decorator.keywords:
                if keyword.arg == "route":
                    value = _route_expr_value(keyword.value)
                    if isinstance(value, str):
                        paths = [value]
                    elif isinstance(value, (list, tuple)):
                        paths = [item for item in value if isinstance(item, str)]
                elif keyword.arg == "methods":
                    value = _route_expr_value(keyword.value)
                    if isinstance(value, str):
                        methods = [value.upper()]
                    elif isinstance(value, (list, tuple, set)):
                        methods = sorted({str(item).upper() for item in value})
                elif keyword.arg == "auth":
                    value = _route_expr_value(keyword.value)
                    auth = str(value) if value is not None else None
                elif keyword.arg == "type":
                    value = _route_expr_value(keyword.value)
                    route_type = str(value) if value is not None else None
            visitor = _WriteSignalVisitor()
            visitor.visit(node)
            signals = set(visitor.signals)
            lowered_name = node.name.lower()
            for hint in WRITE_HINTS:
                if hint in lowered_name:
                    signals.add(f"name:{hint}")
            if any(method in {"POST", "PUT", "PATCH", "DELETE"} for method in methods):
                signals.add("http-method")
            self.routes.append(
                RouteRecord(
                    module=self.module,
                    controller=controller_name,
                    function=node.name,
                    paths=paths,
                    methods=methods,
                    auth=auth,
                    route_type=route_type,
                    source=str(self.path),
                    line=node.lineno,
                    write_signals=sorted(signals),
                )
            )


def _scan_routes(
    ctx: WorkspaceContext,
) -> tuple[list[RouteRecord], list[dict[str, str]]]:
    records: list[RouteRecord] = []
    errors: list[dict[str, str]] = []
    for addons_dir in ctx.addons_paths:
        if not addons_dir.is_dir():
            continue
        for manifest in sorted(addons_dir.glob("*/__manifest__.py")):
            module_dir = manifest.parent
            module = module_dir.name
            for py_path in sorted(module_dir.rglob("*.py")):
                if any(part.startswith(".") for part in py_path.parts):
                    continue
                try:
                    # Tolerate BOM-prefixed source files, which are common in older
                    # Windows Odoo custom addons and should still be routable.
                    source = py_path.read_text(encoding="utf-8-sig")
                    tree = ast.parse(source, filename=str(py_path))
                except (OSError, SyntaxError) as exc:
                    errors.append({"file": str(py_path), "error": str(exc)})
                    continue
                collector = _RouteCollector(py_path, module)
                collector.visit(tree)
                records.extend(collector.routes)
    records.sort(key=lambda item: (item.module, item.source, item.line, item.function))
    return records, errors


def cmd_env_inspect(args: argparse.Namespace) -> int:
    ctx = load_workspace(args)
    psql_payload: dict[str, Any]
    if ctx.runtime.backend == "compose":
        psql_payload = {
            "path": "docker-compose:db/psql",
            "checked": ["Docker Compose service db"],
        }
    else:
        try:
            psql_path, checked = _discover_psql(args, ctx)
            psql_payload = {
                "path": psql_path,
                "checked": checked,
            }
        except CliError as exc:
            checked = (
                exc.args[1]
                if len(exc.args) > 1 and isinstance(exc.args[1], list)
                else []
            )
            psql_payload = {
                "error": str(exc.args[0]),
                "checked": checked,
            }
    runtime_payload = {
        "backend": ctx.runtime.backend,
        "root": str(ctx.runtime.root),
        "config_path": str(ctx.runtime.config_path),
    }
    if ctx.runtime.backend == "compose":
        runtime_payload["compose_command"] = " ".join(ctx.runtime.compose_command or ())
        runtime_payload["env"] = _redact_mapping(ctx.runtime.env or {})

    payload: dict[str, Any] = {
        "runtime": runtime_payload,
        "root": str(ctx.root),
        "config_path": str(ctx.config_path),
        "config": _redact_mapping(
            {
                "addons_path": ctx.config.get("addons_path"),
                "db_host": _normalize_config_value(ctx.config.get("db_host")),
                "db_port": _normalize_config_value(ctx.config.get("db_port")),
                "db_user": _normalize_config_value(ctx.config.get("db_user")),
                "db_name": _normalize_config_value(ctx.config.get("db_name")),
                "pg_path": _normalize_config_value(ctx.config.get("pg_path")),
            }
        ),
        "addons_paths": [str(path) for path in ctx.addons_paths],
        "effective_db_name": ctx.effective_db_name,
        "psql": psql_payload,
    }
    return emit_result(args, payload)


def cmd_addons_list(args: argparse.Namespace) -> int:
    ctx = load_workspace(args)
    modules: list[dict[str, Any]] = []
    for addons_dir in ctx.addons_paths:
        if not addons_dir.is_dir():
            continue
        for manifest in sorted(addons_dir.glob("*/__manifest__.py")):
            module_dir = manifest.parent
            modules.append(
                {
                    "module": module_dir.name,
                    "path": str(module_dir),
                    "addons_dir": str(addons_dir),
                }
            )
    modules.sort(key=lambda item: item["module"])
    return emit_result(args, {"count": len(modules), "modules": modules})


def cmd_addons_manifest(args: argparse.Namespace) -> int:
    ctx = load_workspace(args)
    module_dir = _find_module_dir(ctx, args.module)
    manifest = _read_manifest(module_dir)
    payload = {
        "module": args.module,
        "path": str(module_dir),
        "manifest": manifest,
    }
    return emit_result(args, payload)


def cmd_module_status(args: argparse.Namespace) -> int:
    ctx = load_workspace(args)
    module_dir = _find_module_dir(ctx, args.module)
    manifest = _read_manifest(module_dir)
    sql = _load_sql_recipe(
        "module_status.sql",
        params={"module": _sql_literal(args.module)},
        fallback="""
        SELECT name, state, latest_version, demo
        FROM ir_module_module
        WHERE name = {module}
        """,
    )
    db = _run_psql(args, ctx, sql=sql, read_only=True)
    payload = {
        "module": args.module,
        "path": str(module_dir),
        "manifest_version": manifest.get("version"),
        "depends": manifest.get("depends", []),
        "database": db["database"],
        "runtime": db.get("runtime"),
        "rows": db["rows"],
        "row_count": db["row_count"],
        "psql": db.get("psql"),
        "checked": db.get("checked"),
    }
    return emit_result(args, payload)


def cmd_module_models(args: argparse.Namespace) -> int:
    ctx = load_workspace(args)
    clause = _module_filter_clause(args.module)
    db = _query_recipe(
        args,
        ctx,
        "module_models.sql",
        params={"module": _sql_literal(args.module), "module_clause": clause},
        fallback="""
        SELECT model, name, transient, modules
        FROM ir_model
        WHERE {module_clause}
        ORDER BY model
        """,
    )
    return emit_result(args, db)


def cmd_module_tables(args: argparse.Namespace) -> int:
    ctx = load_workspace(args)
    clause = _module_filter_clause(args.module)
    db = _query_recipe(
        args,
        ctx,
        "module_tables.sql",
        params={"module": _sql_literal(args.module), "module_clause": clause},
        fallback="""
        SELECT model, replace(model, '.', '_') AS table_name
        FROM ir_model
        WHERE {module_clause}
        ORDER BY table_name
        """,
    )
    return emit_result(args, db)


def cmd_module_m2m(args: argparse.Namespace) -> int:
    ctx = load_workspace(args)
    db = _query_recipe(
        args,
        ctx,
        "module_m2m.sql",
        params={"module": _sql_literal(args.module)},
        fallback="""
        SELECT name AS relation_table, model, module
        FROM ir_model_relation
        WHERE module = {module}
        ORDER BY name
        """,
    )
    return emit_result(args, db)


def cmd_module_fks(args: argparse.Namespace) -> int:
    ctx = load_workspace(args)
    clause = _module_filter_clause(args.module)
    db = _query_recipe(
        args,
        ctx,
        "module_fks.sql",
        params={"module": _sql_literal(args.module), "module_clause": clause},
        fallback="""
        WITH module_tables AS (
            SELECT DISTINCT replace(model, '.', '_') AS table_name
            FROM ir_model
            WHERE {module_clause}
        )
        SELECT
            c.conname AS constraint_name,
            src.relname AS table_name,
            a.attname AS column_name,
            dst.relname AS references_table
        FROM pg_constraint c
        JOIN pg_class src ON src.oid = c.conrelid
        JOIN pg_class dst ON dst.oid = c.confrelid
        JOIN pg_attribute a ON a.attrelid = src.oid AND a.attnum = ANY(c.conkey)
        WHERE c.contype = 'f'
          AND (src.relname IN (SELECT table_name FROM module_tables)
               OR dst.relname IN (SELECT table_name FROM module_tables))
        ORDER BY src.relname, c.conname, a.attname
        """,
    )
    return emit_result(args, db)


def cmd_db_summary(args: argparse.Namespace) -> int:
    ctx = load_workspace(args)
    db = _query_recipe(
        args,
        ctx,
        "db_summary.sql",
        params={},
        fallback="""
        SELECT
            current_database() AS database_name,
            current_user AS db_user,
            current_schema AS schema_name,
            pg_database_size(current_database()) AS database_size_bytes,
            pg_size_pretty(pg_database_size(current_database())) AS database_size_pretty,
            (SELECT count(*) FROM pg_tables WHERE schemaname = 'public') AS table_count,
            (SELECT count(*) FROM ir_model) AS model_count,
            (SELECT count(*) FROM ir_module_module WHERE state = 'installed') AS installed_module_count
        """,
    )
    return emit_result(args, db)


def cmd_db_top_tables(args: argparse.Namespace) -> int:
    ctx = load_workspace(args)
    limit = max(1, args.limit)
    db = _query_recipe(
        args,
        ctx,
        "top_tables.sql",
        params={"limit": limit},
        fallback="""
        SELECT
            schemaname,
            relname AS table_name,
            pg_total_relation_size(format('%I.%I', schemaname, relname)) AS total_bytes,
            pg_size_pretty(pg_total_relation_size(format('%I.%I', schemaname, relname))) AS total_pretty
        FROM pg_stat_user_tables
        ORDER BY total_bytes DESC, table_name ASC
        LIMIT {limit}
        """,
    )
    return emit_result(args, db)


def cmd_db_top_rows(args: argparse.Namespace) -> int:
    ctx = load_workspace(args)
    limit = max(1, args.limit)
    db = _query_recipe(
        args,
        ctx,
        "top_rows.sql",
        params={"limit": limit},
        fallback="""
        SELECT
            schemaname,
            relname AS table_name,
            n_live_tup::bigint AS estimated_rows
        FROM pg_stat_user_tables
        ORDER BY estimated_rows DESC, table_name ASC
        LIMIT {limit}
        """,
    )
    return emit_result(args, db)


def cmd_db_orphan_tables(args: argparse.Namespace) -> int:
    ctx = load_workspace(args)
    limit = max(1, args.limit)
    db = _query_recipe(
        args,
        ctx,
        "orphan_tables.sql",
        params={"limit": limit},
        fallback="""
        WITH model_tables AS (
            SELECT DISTINCT replace(model, '.', '_') AS table_name
            FROM ir_model
        )
        SELECT tablename AS table_name
        FROM pg_tables
        WHERE schemaname = 'public'
          AND tablename NOT LIKE 'pg_%'
          AND tablename NOT LIKE 'sql_%'
          AND tablename NOT IN (SELECT table_name FROM model_tables)
        ORDER BY table_name ASC
        LIMIT {limit}
        """,
    )
    return emit_result(args, db)


def cmd_db_query(args: argparse.Namespace) -> int:
    ctx = load_workspace(args)
    if not args.read_only:
        raise CliError(
            "db query requires --read-only; write mode is intentionally not implemented"
        )
    if bool(args.sql_file) == bool(args.sql_stdin):
        raise CliError("provide exactly one of --sql-file or --sql-stdin")
    if args.sql_file:
        sql_path = Path(args.sql_file).expanduser()
        try:
            sql = sql_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise CliError(f"failed to read SQL file {sql_path}: {exc}") from exc
    else:
        sql = sys.stdin.read()
        if not sql.strip():
            raise CliError("no SQL received on stdin")
    db = _run_psql(args, ctx, sql=sql, read_only=True)
    payload = {
        "database": db["database"],
        "row_count": db["row_count"],
        "rows": db["rows"],
    }
    return emit_result(args, payload)


def cmd_route_list(args: argparse.Namespace) -> int:
    ctx = load_workspace(args)
    routes, errors = _scan_routes(ctx)
    payload = {
        "count": len(routes),
        "routes": routes,
        "parse_errors": errors,
    }
    return emit_result(args, payload)


def cmd_route_scan_writes(args: argparse.Namespace) -> int:
    ctx = load_workspace(args)
    routes, errors = _scan_routes(ctx)
    risky = [route for route in routes if route.write_signals]
    payload = {
        "count": len(risky),
        "routes": risky,
        "parse_errors": errors,
    }
    return emit_result(args, payload)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="odooctl")
    parser.add_argument(
        "--root",
        help="Odoo workspace root; defaults to discovery from cwd plus nearby child workspaces",
    )
    parser.add_argument("--config", help="Optional odoo.conf override")
    parser.add_argument("--db", help="Optional database override")
    parser.add_argument("--psql", help="Optional psql executable override")
    parser.add_argument(
        "--runtime-dir", help="Optional Docker Compose runtime directory override"
    )

    top = parser.add_subparsers(dest="topic", required=True)
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
    addons_manifest = addons_sub.add_parser("manifest")
    addons_manifest.add_argument("module")
    addons_manifest.add_argument("--json", action="store_true")
    addons_manifest.set_defaults(func=cmd_addons_manifest)

    module_parser = top.add_parser("module")
    module_sub = module_parser.add_subparsers(dest="action", required=True)
    for name, func in {
        "status": cmd_module_status,
        "models": cmd_module_models,
        "tables": cmd_module_tables,
        "m2m": cmd_module_m2m,
        "fks": cmd_module_fks,
    }.items():
        sub = module_sub.add_parser(name)
        sub.add_argument("module")
        sub.add_argument("--json", action="store_true")
        sub.set_defaults(func=func)

    db_parser = top.add_parser("db")
    db_sub = db_parser.add_subparsers(dest="action", required=True)
    db_summary = db_sub.add_parser("summary")
    db_summary.add_argument("--json", action="store_true")
    db_summary.set_defaults(func=cmd_db_summary)
    for name, func in {
        "top-tables": cmd_db_top_tables,
        "top-rows": cmd_db_top_rows,
        "orphan-tables": cmd_db_orphan_tables,
    }.items():
        sub = db_sub.add_parser(name)
        sub.add_argument("--limit", type=int, default=20)
        sub.add_argument("--json", action="store_true")
        sub.set_defaults(func=func)
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
    route_scan = route_sub.add_parser("scan-writes")
    route_scan.add_argument("--json", action="store_true")
    route_scan.set_defaults(func=cmd_route_scan_writes)
    return parser


def _normalize_global_args(argv: list[str]) -> list[str]:
    """Allow global options before or after subcommands."""
    global_options = {"--root", "--config", "--db", "--psql", "--runtime-dir"}
    prefix: list[str] = []
    rest: list[str] = []
    idx = 0
    while idx < len(argv):
        token = argv[idx]
        if token in global_options and idx + 1 < len(argv):
            prefix.extend([token, argv[idx + 1]])
            idx += 2
            continue
        if any(token.startswith(f"{option}=") for option in global_options):
            prefix.append(token)
            idx += 1
            continue
        rest.append(token)
        idx += 1
    return [*prefix, *rest]


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(_normalize_global_args(argv or sys.argv[1:]))
    try:
        return args.func(args)
    except CliError as exc:
        checked = None
        if len(exc.args) > 1 and isinstance(exc.args[1], list):
            checked = exc.args[1]
        return _fail(args, str(exc.args[0]), checked=checked)
    except KeyboardInterrupt:
        return _fail(args, "interrupted")


if __name__ == "__main__":
    raise SystemExit(main())
