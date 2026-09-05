# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "httpx>=0.27",
# ]
# ///
"""n8nctl - Minimal REST CLI for n8n workflow authoring.

Usage:
  n8nctl.py list [--limit N] [--active true|false]
  n8nctl.py get <workflow-id>
  n8nctl.py create <workflow.json>
  n8nctl.py update <workflow-id> <workflow.json>
  n8nctl.py export <workflow-id> <out.json>
  n8nctl.py activate <workflow-id>
  n8nctl.py deactivate <workflow-id>
  n8nctl.py mcp-enable <workflow-id>
  n8nctl.py validate <workflow.json>

Environment:
  N8N_BASE_URL   Base URL like http://localhost:5678
  N8N_API_KEY    API key for X-N8N-API-KEY header
  N8N_ENV_FILE   Optional env file override
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

# typing.Union is deprecated in favor of X | Y, but a recursive alias needs
# quoted forward references while X | "Y" is a runtime TypeError (TC010);
# the type statement needs Python 3.12+ and this skill supports 3.10.
from typing import (
    TYPE_CHECKING,
    NoReturn,
    TypeAlias,
    Union,  # pyright: ignore[reportDeprecated] - see note above
    cast,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

import httpx

JsonValue: TypeAlias = Union[  # pyright: ignore[reportDeprecated] - see note above
    bool, int, float, str, "list[JsonValue]", "dict[str, JsonValue]", None
]
JsonObject: TypeAlias = dict[str, JsonValue]


@dataclass(frozen=True)
class Config:
    """Connection settings for the n8n REST API."""

    base_url: str
    api_key: str


class N8nError(Exception):
    """Base error for n8nctl."""


def _fail(message: str) -> NoReturn:
    """Print a CLI error and exit with status 2."""
    print(f"n8nctl: {message}", file=sys.stderr)
    raise SystemExit(2)


def _require_env(name: str, value: str | None) -> str:
    """Return a required environment value or exit."""
    if value is None or value.strip() == "":
        _fail(f"missing required env var: {name}")
    return value


def _env_candidates() -> Iterable[Path]:
    env_file = os.getenv("N8N_ENV_FILE")
    if env_file:
        yield Path(env_file).expanduser()

    skills_dir = os.getenv("SKILLS_DIR")
    if skills_dir:
        yield Path(skills_dir).expanduser() / "n8n" / ".env"

    for parent in (Path.cwd(), *Path.cwd().parents):
        yield parent / "skills" / "n8n" / ".env"


def _load_env_file() -> None:
    if os.getenv("N8N_BASE_URL") and os.getenv("N8N_API_KEY"):
        return

    for path in _env_candidates():
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for raw_line in lines:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            key, sep, value = line.partition("=")
            if sep == "":
                continue
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            _ = os.environ.setdefault(key, value)
        return


def load_config(args: argparse.Namespace) -> Config:
    """Build connection settings from flags with environment fallback."""
    _load_env_file()
    base_url = _optional_str(args, "base_url") or os.getenv("N8N_BASE_URL")
    api_key = _optional_str(args, "api_key") or os.getenv("N8N_API_KEY")
    return Config(
        base_url=_require_env("N8N_BASE_URL", base_url).rstrip("/"),
        api_key=_require_env("N8N_API_KEY", api_key),
    )


def _headers(cfg: Config) -> dict[str, str]:
    return {"X-N8N-API-KEY": cfg.api_key}


def _optional_str(args: argparse.Namespace, field: str) -> str | None:
    """Narrow an optional string flag to a typed value."""
    value = cast("object", getattr(args, field))
    return value if isinstance(value, str) else None


def _optional_int(args: argparse.Namespace, field: str) -> int | None:
    """Narrow an optional integer flag to a typed value."""
    value = cast("object", getattr(args, field))
    return value if isinstance(value, int) else None


def _required_str(args: argparse.Namespace, field: str) -> str:
    """Narrow a required string argument to a typed value."""
    value = cast("object", getattr(args, field))
    if not isinstance(value, str):
        _fail(f"missing required argument: {field}")
    return value


def _required_path(args: argparse.Namespace, field: str) -> Path:
    """Narrow a required path argument to a typed value."""
    value = cast("object", getattr(args, field))
    if not isinstance(value, Path):
        _fail(f"missing required argument: {field}")
    return value


def _request(
    cfg: Config,
    method: str,
    path: str,
    *,
    params: dict[str, str] | None = None,
    body: JsonObject | None = None,
) -> JsonObject:
    url = f"{cfg.base_url}{path}"
    headers = _headers(cfg)
    if body is not None:
        headers["Content-Type"] = "application/json"
    with httpx.Client(timeout=30.0) as client:
        try:
            resp = client.request(
                method,
                url,
                params=params,
                json=body,
                headers=headers,
            )
        except httpx.HTTPError as exc:
            _fail(f"request failed: {exc}")
    if resp.is_error:
        _fail(f"HTTP {resp.status_code} {resp.reason_phrase}: {resp.text}")
    return cast("JsonObject", resp.json())


def _load_json(path: Path) -> JsonObject:
    """Load a JSON object file or exit with a CLI error."""
    try:
        data = cast("object", json.loads(path.read_text(encoding="utf-8")))
    except OSError as exc:
        _fail(f"failed to read {path}: {exc}")
    except json.JSONDecodeError as exc:
        _fail(f"invalid JSON in {path}: {exc}")
    if not isinstance(data, dict):
        _fail(f"expected JSON object in {path}")
    return cast("JsonObject", data)


def _require_workflow_fields(data: JsonObject, path: Path) -> JsonObject:
    """Exit unless the workflow object carries every required key."""
    missing = [
        key for key in ("name", "nodes", "connections", "settings") if key not in data
    ]
    if missing:
        _fail(f"workflow JSON missing keys {missing} in {path}")
    return data


def _workflow_payload(data: JsonObject) -> JsonObject:
    return {
        "name": data.get("name"),
        "nodes": data.get("nodes"),
        "connections": data.get("connections"),
        "settings": data.get("settings"),
    }


def _validate_workflow_data(data: JsonObject, path: Path) -> JsonObject:
    """Validate a workflow object and report errors and warnings."""
    errors: list[JsonValue] = [
        f"missing key: {key}"
        for key in ("name", "nodes", "connections", "settings")
        if key not in data
    ]
    warnings: list[JsonValue] = []
    if errors:
        return {"valid": False, "errors": errors, "warnings": warnings}

    nodes = data.get("nodes")
    connections = data.get("connections")
    settings = data.get("settings")
    if not isinstance(nodes, list):
        errors.append("nodes must be a list")
        return {"valid": False, "errors": errors, "warnings": warnings}
    if not isinstance(connections, dict):
        errors.append("connections must be an object")
    if not isinstance(settings, dict):
        errors.append("settings must be an object")

    names = _validate_nodes(nodes, errors)
    _validate_connections(connections, set(names), errors, warnings)
    if (
        isinstance(settings, dict)
        and "availableInMCP" in settings
        and not isinstance(settings["availableInMCP"], bool)
    ):
        warnings.append("settings.availableInMCP should be boolean")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "path": str(path),
    }


def _validate_nodes(nodes: list[JsonValue], errors: list[JsonValue]) -> list[str]:
    """Validate workflow nodes and return their names in order."""
    names: list[str] = []
    for idx, node in enumerate(nodes):
        if not isinstance(node, dict):
            errors.append(f"nodes[{idx}] must be an object")
            continue
        name = node.get("name")
        node_type = node.get("type")
        if not isinstance(name, str) or name.strip() == "":
            errors.append(f"nodes[{idx}].name must be a non-empty string")
        else:
            if name in names:
                errors.append(f"duplicate node name: {name}")
            names.append(name)
        if not isinstance(node_type, str) or node_type.strip() == "":
            errors.append(f"nodes[{idx}].type must be a non-empty string")
    return names


def _validate_connections(
    connections: JsonValue,
    name_set: set[str],
    errors: list[JsonValue],
    warnings: list[JsonValue],
) -> None:
    """Validate workflow connections against known node names."""
    if not isinstance(connections, dict):
        return
    for src_name, src_conn in connections.items():
        if src_name not in name_set:
            warnings.append(f"connection source not in nodes: {src_name}")
        if not isinstance(src_conn, dict):
            warnings.append(f"connection for {src_name} is not an object")
            continue
        main = src_conn.get("main")
        if not isinstance(main, list):
            warnings.append(f"connection {src_name}.main is not a list")
            continue
        for branch in main:
            if not isinstance(branch, list):
                warnings.append(f"connection {src_name}.main branch is not a list")
                continue
            for edge in branch:
                _validate_edge(src_name, edge, name_set, errors, warnings)


def _validate_edge(
    src_name: str,
    edge: JsonValue,
    name_set: set[str],
    errors: list[JsonValue],
    warnings: list[JsonValue],
) -> None:
    """Validate one connection edge against known node names."""
    if not isinstance(edge, dict):
        warnings.append(f"connection {src_name} edge is not an object")
        return
    target = edge.get("node")
    if isinstance(target, str) and target not in name_set:
        errors.append(
            f"connection from {src_name} to missing node: {target}",
        )


def cmd_list(cfg: Config, args: argparse.Namespace) -> JsonObject:
    """List workflows with optional limit and active filters."""
    params: dict[str, str] = {}
    limit = _optional_int(args, "limit")
    if limit is not None:
        params["limit"] = str(limit)
    active = _optional_str(args, "active")
    if active is not None:
        params["active"] = active
    return _request(cfg, "GET", "/api/v1/workflows", params=params)


def cmd_get(cfg: Config, args: argparse.Namespace) -> JsonObject:
    """Fetch one workflow by id."""
    workflow_id = _required_str(args, "workflow_id")
    return _request(cfg, "GET", f"/api/v1/workflows/{workflow_id}")


def cmd_create(cfg: Config, args: argparse.Namespace) -> JsonObject:
    """Create a workflow from a JSON file."""
    path = _required_path(args, "path")
    payload = _workflow_payload(_require_workflow_fields(_load_json(path), path))
    return _request(cfg, "POST", "/api/v1/workflows", body=payload)


def cmd_update(cfg: Config, args: argparse.Namespace) -> JsonObject:
    """Update a workflow from a JSON file."""
    path = _required_path(args, "path")
    workflow_id = _required_str(args, "workflow_id")
    payload = _workflow_payload(_require_workflow_fields(_load_json(path), path))
    return _request(cfg, "PUT", f"/api/v1/workflows/{workflow_id}", body=payload)


def cmd_export(cfg: Config, args: argparse.Namespace) -> JsonObject:
    """Export one workflow to a JSON file."""
    workflow_id = _required_str(args, "workflow_id")
    out = _required_path(args, "out")
    data = _request(cfg, "GET", f"/api/v1/workflows/{workflow_id}")
    _ = out.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return {"saved": str(out)}


def cmd_activate(cfg: Config, args: argparse.Namespace) -> JsonObject:
    """Activate one workflow by id."""
    workflow_id = _required_str(args, "workflow_id")
    return _request(cfg, "POST", f"/api/v1/workflows/{workflow_id}/activate")


def cmd_deactivate(cfg: Config, args: argparse.Namespace) -> JsonObject:
    """Deactivate one workflow by id."""
    workflow_id = _required_str(args, "workflow_id")
    return _request(cfg, "POST", f"/api/v1/workflows/{workflow_id}/deactivate")


def cmd_mcp_enable(cfg: Config, args: argparse.Namespace) -> JsonObject:
    """Enable MCP access for one workflow by id."""
    workflow_id = _required_str(args, "workflow_id")
    wf = _request(cfg, "GET", f"/api/v1/workflows/{workflow_id}")
    settings: JsonObject = {}
    raw_settings = wf.get("settings")
    if isinstance(raw_settings, dict):
        for key, value in cast("dict[object, object]", raw_settings).items():
            if isinstance(key, str):
                settings[key] = cast("JsonValue", value)
    settings["availableInMCP"] = True
    payload = _workflow_payload(
        {
            "name": wf.get("name"),
            "nodes": wf.get("nodes"),
            "connections": wf.get("connections"),
            "settings": settings,
        },
    )
    return _request(cfg, "PUT", f"/api/v1/workflows/{workflow_id}", body=payload)


def cmd_validate(_: Config | None, args: argparse.Namespace) -> JsonObject:
    """Validate a workflow JSON file without contacting the API."""
    path = _required_path(args, "path")
    return _validate_workflow_data(_load_json(path), path)


def build_parser() -> argparse.ArgumentParser:
    """Build the n8nctl command-line parser."""
    parser = argparse.ArgumentParser(description="n8nctl - minimal REST CLI")
    _ = parser.add_argument("--base-url", help="override N8N_BASE_URL")
    _ = parser.add_argument("--api-key", help="override N8N_API_KEY")

    sub = parser.add_subparsers(dest="command", required=True)

    list_p = sub.add_parser("list", help="list workflows")
    _ = list_p.add_argument("--limit", type=int)
    _ = list_p.add_argument("--active", choices=["true", "false"])

    get_p = sub.add_parser("get", help="get workflow by id")
    _ = get_p.add_argument("workflow_id")

    create_p = sub.add_parser("create", help="create workflow from JSON")
    _ = create_p.add_argument("path", type=Path)

    update_p = sub.add_parser("update", help="update workflow from JSON")
    _ = update_p.add_argument("workflow_id")
    _ = update_p.add_argument("path", type=Path)

    export_p = sub.add_parser("export", help="export workflow JSON")
    _ = export_p.add_argument("workflow_id")
    _ = export_p.add_argument("out", type=Path)

    activate_p = sub.add_parser("activate", help="activate workflow")
    _ = activate_p.add_argument("workflow_id")

    deactivate_p = sub.add_parser("deactivate", help="deactivate workflow")
    _ = deactivate_p.add_argument("workflow_id")

    mcp_p = sub.add_parser("mcp-enable", help="enable MCP access for workflow")
    _ = mcp_p.add_argument("workflow_id")

    validate_p = sub.add_parser("validate", help="validate workflow JSON")
    _ = validate_p.add_argument("path", type=Path)

    return parser


def main() -> None:
    """Dispatch the n8nctl subcommand."""
    parser = build_parser()
    args = parser.parse_args()
    command = _required_str(args, "command")

    if command == "validate":
        result = cmd_validate(None, args)
    else:
        handlers: dict[str, Callable[[Config, argparse.Namespace], JsonObject]] = {
            "list": cmd_list,
            "get": cmd_get,
            "create": cmd_create,
            "update": cmd_update,
            "export": cmd_export,
            "activate": cmd_activate,
            "deactivate": cmd_deactivate,
            "mcp-enable": cmd_mcp_enable,
        }
        result = handlers[command](load_config(args), args)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
