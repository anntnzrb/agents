#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Odoo JSON-RPC Client.

Queries and manages Odoo models directly via JSON-RPC.
Enforces strict allowlisting for safe read-only/introspection queries by default,
and requires explicit authorization (--write) for state-modifying operations.
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Methods that only perform SELECT operations or inspect system metadata
READONLY_ALLOWLIST: frozenset[str] = frozenset(
    {
        "search",
        "search_read",
        "search_count",
        "search_fetch",
        "read",
        "read_group",
        "fields_get",
        "get_view",
        "get_views",
        "name_search",
        "name_get",
        "export_data",
        "get_metadata",
        "get_external_id",
        "default_get",
        "check_access_rights",
        "check_field_access_rights",
        "user_has_groups",
        "onchange",
    }
)

# Methods that mutate state / write to the database (require --write)
MUTATION_ALLOWLIST: frozenset[str] = frozenset(
    {
        "create",
        "write",
        "unlink",
        "copy",
        "action_archive",
        "action_unarchive",
        "toggle_active",
    }
)


def parse_env_file(path: Path) -> bool:
    """Parse a .env file and populate os.environ with setdefault semantics."""
    if not path.is_file():
        return False
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return False

    for line in content.splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        if text.startswith("export "):
            text = text.removeprefix("export ").lstrip()
        if "=" not in text:
            continue
        key, value = text.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)
    return True


def load_env(env_file: Path | str | None = None) -> None:
    """Auto-discover and load .env configuration."""
    candidates: list[Path] = []
    if env_file:
        candidates.append(Path(env_file).expanduser())
    if os.environ.get("ODOO_ENV_FILE"):
        candidates.append(Path(os.environ["ODOO_ENV_FILE"]).expanduser())

    skill_root = Path(__file__).resolve().parents[1]
    candidates.append(skill_root / ".env")

    # Upward search for nearest ancestor skills/odoo-ops/.env
    here = Path.cwd().resolve()
    for directory in (here, *here.parents):
        candidate = directory / "skills" / "odoo-ops" / ".env"
        candidates.append(candidate)

    for candidate in candidates:
        if candidate.is_file() and parse_env_file(candidate):
            break


@dataclass(frozen=True, slots=True)
class OdooRpcConfig:
    """Validated boundary configuration for Odoo RPC."""

    url: str
    database: str
    user: str
    token: str
    verify_ssl: bool = True

    @classmethod
    def from_env(
        cls,
        *,
        url: str | None = None,
        database: str | None = None,
        user: str | None = None,
        token: str | None = None,
        token_path: Path | str | None = None,
        verify_ssl: bool | None = None,
    ) -> OdooRpcConfig:
        """Resolve and validate configuration from CLI arguments and environment."""
        resolved_url = url or os.environ.get("ODOO_RPC_URL")
        if not resolved_url:
            raise ValueError(
                "Missing Odoo RPC URL. Set ODOO_RPC_URL in your environment/.env or pass --url."
            )
        if not resolved_url.endswith("/jsonrpc"):
            resolved_url = f"{resolved_url.rstrip('/')}/jsonrpc"

        resolved_db = database or os.environ.get("ODOO_RPC_DB")
        if not resolved_db:
            raise ValueError(
                "Missing Odoo RPC database. Set ODOO_RPC_DB in your environment/.env or pass --db."
            )

        resolved_user = user or os.environ.get("ODOO_RPC_USER")
        if not resolved_user:
            raise ValueError(
                "Missing Odoo RPC user. Set ODOO_RPC_USER in your environment/.env or pass --user."
            )

        # Token resolution
        resolved_token = token or os.environ.get("ODOO_RPC_TOKEN")
        if not resolved_token:
            candidate_token_paths: list[Path] = []
            if token_path:
                candidate_token_paths.append(Path(token_path).expanduser())
            if os.environ.get("ODOO_RPC_TOKEN_PATH"):
                candidate_token_paths.append(
                    Path(os.environ["ODOO_RPC_TOKEN_PATH"]).expanduser()
                )
            default_token_path = Path("~/.erp-token").expanduser()
            candidate_token_paths.append(default_token_path)

            for path in candidate_token_paths:
                if path.is_file():
                    try:
                        resolved_token = path.read_text(encoding="utf-8").strip()
                        if resolved_token:
                            break
                    except OSError:
                        continue

        if not resolved_token:
            raise ValueError(
                "Missing Odoo RPC token. Specify ODOO_RPC_TOKEN, provide ODOO_RPC_TOKEN_PATH, "
                "or pass --token / --token-path."
            )

        # SSL resolution: default True
        if verify_ssl is not None:
            resolved_verify_ssl = verify_ssl
        else:
            env_ssl = os.environ.get("ODOO_RPC_VERIFY_SSL", "true").strip().lower()
            resolved_verify_ssl = env_ssl not in ("0", "false", "no", "off")

        return cls(
            url=resolved_url,
            database=resolved_db,
            user=resolved_user,
            token=resolved_token,
            verify_ssl=resolved_verify_ssl,
        )


def json_rpc(
    url: str,
    service: str,
    method: str,
    *args: Any,
    verify_ssl: bool = True,
    timeout: float = 30.0,
) -> Any:
    """Execute a single JSON-RPC 2.0 call against Odoo."""
    payload = {
        "jsonrpc": "2.0",
        "method": "call",
        "params": {
            "service": service,
            "method": method,
            "args": list(args),
        },
        "id": 1,
    }

    if verify_ssl:
        cafile = None
        for candidate in (
            os.environ.get("SSL_CERT_FILE"),
            os.environ.get("NIX_SSL_CERT_FILE"),
            "/etc/ssl/certs/ca-certificates.crt",
            "/etc/pki/tls/certs/ca-bundle.crt",
            "/etc/ssl/ca-bundle.pem",
        ):
            if candidate and Path(candidate).is_file():
                cafile = candidate
                break
        ctx = ssl.create_default_context(cafile=cafile)
    else:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "OdooRpcClient/1.0",
        },
    )

    try:
        with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            res = json.loads(raw)
            if "error" in res:
                raise RuntimeError(f"Odoo RPC Error: {res['error']}")
            return res.get("result")
    except urllib.error.HTTPError as e:
        error_body = ""
        try:
            error_body = e.read().decode("utf-8", errors="replace")
        except (OSError, UnicodeDecodeError):
            error_body = "<unreadable>"
        raise RuntimeError(f"HTTP {e.code}: {e.reason} ({error_body})") from e
    except urllib.error.URLError as e:
        raise ConnectionError(f"Failed to connect to {url}: {e.reason}") from e


class OdooRpcClient:
    """Client providing safe querying and guarded mutations on Odoo via JSON-RPC."""

    def __init__(
        self,
        config: OdooRpcConfig | None = None,
        *,
        allow_write: bool = False,
    ) -> None:
        self.config = config or OdooRpcConfig.from_env()
        self.allow_write = allow_write
        self._uid: int | None = None

    @property
    def uid(self) -> int:
        if self._uid is None:
            res = json_rpc(
                self.config.url,
                "common",
                "authenticate",
                self.config.database,
                self.config.user,
                self.config.token,
                {},
                verify_ssl=self.config.verify_ssl,
            )
            if not res or not isinstance(res, int):
                raise PermissionError(
                    f"Authentication failed at {self.config.url} for user {self.config.user}"
                )
            self._uid = res
        return self._uid

    def execute(
        self,
        model: str,
        method: str,
        args: list[Any] | None = None,
        kwargs: dict[str, Any] | None = None,
    ) -> Any:
        """Execute a model method after checking method permission policies."""
        if method in READONLY_ALLOWLIST:
            # Safe read-only / introspection methods are always allowed
            pass
        elif method in MUTATION_ALLOWLIST:
            if not self.allow_write:
                raise PermissionError(
                    f"MUTATION BLOCKED: Method '{method}' modifies data but --write was not specified. "
                    "Pass --write to authorize state mutations."
                )
        else:
            raise PermissionError(
                f"METHOD FORBIDDEN: Method '{method}' is neither in the safe allowlist nor the mutation allowlist: "
                f"{sorted(READONLY_ALLOWLIST | MUTATION_ALLOWLIST)}"
            )

        return json_rpc(
            self.config.url,
            "object",
            "execute_kw",
            self.config.database,
            self.uid,
            self.config.token,
            model,
            method,
            args or [],
            kwargs or {},
            verify_ssl=self.config.verify_ssl,
        )

    # --- Read & Query Operations ---

    def search_read(
        self,
        model: str,
        domain: list[Any] | None = None,
        fields: list[str] | None = None,
        limit: int | None = None,
        offset: int = 0,
        order: str | None = None,
    ) -> list[dict[str, Any]]:
        kwargs: dict[str, Any] = {"offset": offset}
        if fields:
            kwargs["fields"] = fields
        if limit is not None:
            kwargs["limit"] = limit
        if order:
            kwargs["order"] = order
        return self.execute(model, "search_read", [domain or []], kwargs)

    def search_count(self, model: str, domain: list[Any] | None = None) -> int:
        return self.execute(model, "search_count", [domain or []])

    def read(
        self,
        model: str,
        ids: list[int],
        fields: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        kwargs = {"fields": fields} if fields else {}
        return self.execute(model, "read", [ids], kwargs)

    def fields_get(
        self,
        model: str,
        allfields: list[str] | None = None,
        attributes: list[str] | None = None,
    ) -> dict[str, Any]:
        args = [allfields] if allfields is not None else []
        kwargs = {"attributes": attributes} if attributes else {}
        return self.execute(model, "fields_get", args, kwargs)

    def get_view(
        self,
        model: str,
        view_id: int | None = None,
        view_type: str = "form",
    ) -> dict[str, Any]:
        kwargs = {"view_type": view_type}
        if view_id is not None:
            kwargs["view_id"] = view_id
        return self.execute(model, "get_view", [], kwargs)

    def get_views(
        self,
        model: str,
        views: list[list[Any]],
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.execute(model, "get_views", [views], {"options": options or {}})

    # --- Safe Introspection Operations ---

    def get_metadata(
        self,
        model: str,
        ids: list[int],
    ) -> list[dict[str, Any]]:
        return self.execute(model, "get_metadata", [ids])

    def get_external_id(
        self,
        model: str,
        ids: list[int],
    ) -> dict[int, str]:
        return self.execute(model, "get_external_id", [ids])

    def default_get(
        self,
        model: str,
        fields: list[str],
    ) -> dict[str, Any]:
        return self.execute(model, "default_get", [fields])

    def check_access_rights(
        self,
        model: str,
        operation: str = "read",
        raise_exception: bool = False,
    ) -> bool:
        return self.execute(
            model,
            "check_access_rights",
            [operation],
            {"raise_exception": raise_exception},
        )

    def user_has_groups(
        self,
        groups: str,
    ) -> bool:
        return self.execute("res.users", "user_has_groups", [groups])

    def onchange(
        self,
        model: str,
        ids: list[int],
        values: dict[str, Any],
        field_name: str,
        field_onchange: dict[str, Any],
    ) -> dict[str, Any]:
        return self.execute(
            model, "onchange", [ids, values, field_name, field_onchange]
        )

    # --- State Mutation Operations (Guarded by --write) ---

    def create(
        self,
        model: str,
        vals: dict[str, Any] | list[dict[str, Any]],
    ) -> int | list[int]:
        return self.execute(model, "create", [vals])

    def write(
        self,
        model: str,
        ids: list[int],
        vals: dict[str, Any],
    ) -> bool:
        return self.execute(model, "write", [ids, vals])

    def unlink(
        self,
        model: str,
        ids: list[int],
    ) -> bool:
        return self.execute(model, "unlink", [ids])

    def copy(
        self,
        model: str,
        record_id: int,
        default: dict[str, Any] | None = None,
    ) -> int:
        kwargs = {"default": default} if default else {}
        return self.execute(model, "copy", [record_id], kwargs)

    def action_archive(
        self,
        model: str,
        ids: list[int],
    ) -> bool:
        return self.execute(model, "action_archive", [ids])

    def action_unarchive(
        self,
        model: str,
        ids: list[int],
    ) -> bool:
        return self.execute(model, "action_unarchive", [ids])

    def toggle_active(
        self,
        model: str,
        ids: list[int],
    ) -> bool:
        return self.execute(model, "toggle_active", [ids])


# Backward-compatible alias
OdooReadOnlyClient = OdooRpcClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Odoo JSON-RPC Client (Safe Querying & Guarded Mutations)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    # Global connection & execution overrides
    parser.add_argument("--url", help="Odoo JSON-RPC endpoint URL")
    parser.add_argument("--db", help="Odoo database name")
    parser.add_argument("--user", help="Odoo user login")
    parser.add_argument("--token", help="Odoo API token or password")
    parser.add_argument("--token-path", help="Path to token file")
    parser.add_argument(
        "--insecure", action="store_true", help="Disable SSL certificate verification"
    )
    parser.add_argument("--env-file", help="Path to specific .env configuration file")
    parser.add_argument(
        "--write",
        action="store_true",
        help="Authorize state mutations (create, write, unlink, archive, copy)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- Query Commands ---
    sr_parser = subparsers.add_parser("search_read", help="Execute search_read query")
    sr_parser.add_argument("model", help="Model name (e.g. crm.lead)")
    sr_parser.add_argument(
        "domain",
        nargs="?",
        default="[]",
        help='Domain as JSON array (e.g. \'[["active", "=", true]]\')',
    )
    sr_parser.add_argument(
        "--fields", nargs="*", default=None, help="Field names to retrieve"
    )
    sr_parser.add_argument(
        "--limit", type=int, default=10, help="Maximum records to return"
    )
    sr_parser.add_argument("--offset", type=int, default=0, help="Record offset")
    sr_parser.add_argument("--order", default=None, help="Sort order (e.g. 'id desc')")

    count_parser = subparsers.add_parser("count", help="Count matching records")
    count_parser.add_argument("model", help="Model name")
    count_parser.add_argument(
        "domain", nargs="?", default="[]", help="Domain as JSON array"
    )

    read_parser = subparsers.add_parser("read", help="Read records by ID")
    read_parser.add_argument("model", help="Model name")
    read_parser.add_argument("ids", help="Record IDs as JSON array (e.g. '[1, 2, 3]')")
    read_parser.add_argument(
        "--fields", nargs="*", default=None, help="Field names to retrieve"
    )

    fg_parser = subparsers.add_parser(
        "fields_get", help="Inspect model fields definition"
    )
    fg_parser.add_argument("model", help="Model name")
    fg_parser.add_argument(
        "--fields", nargs="*", default=None, help="Specific fields to inspect"
    )

    gv_parser = subparsers.add_parser(
        "get_view", help="Inspect rendered view architecture"
    )
    gv_parser.add_argument("model", help="Model name")
    gv_parser.add_argument("--view-id", type=int, default=None, help="Specific view ID")
    gv_parser.add_argument(
        "--view-type", default="form", help="View type (form, list/tree, search)"
    )

    # --- Safe Introspection Commands ---
    meta_parser = subparsers.add_parser(
        "metadata", help="Get record metadata (create_date, write_date, XML IDs)"
    )
    meta_parser.add_argument("model", help="Model name")
    meta_parser.add_argument("ids", help="Record IDs as JSON array (e.g. '[1, 2]')")

    ext_parser = subparsers.add_parser(
        "external_id", help="Retrieve XML External IDs for records"
    )
    ext_parser.add_argument("model", help="Model name")
    ext_parser.add_argument("ids", help="Record IDs as JSON array (e.g. '[1, 2]')")

    def_parser = subparsers.add_parser(
        "default_get", help="Retrieve default values for fields"
    )
    def_parser.add_argument("model", help="Model name")
    def_parser.add_argument(
        "fields", nargs="+", help="Field names to inspect default values for"
    )

    access_parser = subparsers.add_parser(
        "check_access", help="Check model access rights"
    )
    access_parser.add_argument("model", help="Model name")
    access_parser.add_argument(
        "--operation", default="read", choices=["read", "write", "create", "unlink"]
    )

    group_parser = subparsers.add_parser(
        "user_has_groups", help="Check if current user has group"
    )
    group_parser.add_argument("groups", help="Group XML ID (e.g. 'base.group_system')")

    # --- State Mutation Commands (Require --write) ---
    create_parser = subparsers.add_parser(
        "create", help="Create new record(s) (requires --write)"
    )
    create_parser.add_argument("model", help="Model name")
    create_parser.add_argument(
        "values", help="Field values as JSON object or array of objects"
    )

    update_parser = subparsers.add_parser(
        "write", aliases=["update"], help="Update existing records (requires --write)"
    )
    update_parser.add_argument("model", help="Model name")
    update_parser.add_argument("ids", help="Record IDs as JSON array (e.g. '[1, 2]')")
    update_parser.add_argument("values", help="Field values to update as JSON object")

    unlink_parser = subparsers.add_parser(
        "unlink", aliases=["delete"], help="Delete records (requires --write)"
    )
    unlink_parser.add_argument("model", help="Model name")
    unlink_parser.add_argument("ids", help="Record IDs as JSON array (e.g. '[1, 2]')")

    copy_parser = subparsers.add_parser(
        "copy", help="Duplicate a record (requires --write)"
    )
    copy_parser.add_argument("model", help="Model name")
    copy_parser.add_argument("id", type=int, help="Record ID to duplicate")
    copy_parser.add_argument(
        "--default", default=None, help="Default override values as JSON object"
    )

    archive_parser = subparsers.add_parser(
        "archive", help="Archive records by setting active=False (requires --write)"
    )
    archive_parser.add_argument("model", help="Model name")
    archive_parser.add_argument("ids", help="Record IDs as JSON array")

    unarchive_parser = subparsers.add_parser(
        "unarchive", help="Unarchive records by setting active=True (requires --write)"
    )
    unarchive_parser.add_argument("model", help="Model name")
    unarchive_parser.add_argument("ids", help="Record IDs as JSON array")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    load_env(args.env_file)

    try:
        config = OdooRpcConfig.from_env(
            url=args.url,
            database=args.db,
            user=args.user,
            token=args.token,
            token_path=args.token_path,
            verify_ssl=False if args.insecure else None,
        )
        client = OdooRpcClient(config, allow_write=args.write)

        # Query & Inspection
        if args.command == "search_read":
            domain = json.loads(args.domain)
            res = client.search_read(
                args.model,
                domain=domain,
                fields=args.fields,
                limit=args.limit,
                offset=args.offset,
                order=args.order,
            )
            print(json.dumps(res, indent=2, ensure_ascii=False))
        elif args.command == "count":
            domain = json.loads(args.domain)
            res = client.search_count(args.model, domain=domain)
            print(json.dumps({"count": res}))
        elif args.command == "read":
            ids = json.loads(args.ids)
            res = client.read(args.model, ids=ids, fields=args.fields)
            print(json.dumps(res, indent=2, ensure_ascii=False))
        elif args.command == "fields_get":
            res = client.fields_get(args.model, allfields=args.fields)
            print(json.dumps(res, indent=2, ensure_ascii=False))
        elif args.command == "get_view":
            res = client.get_view(
                args.model, view_id=args.view_id, view_type=args.view_type
            )
            print(json.dumps(res, indent=2, ensure_ascii=False))
        elif args.command == "metadata":
            ids = json.loads(args.ids)
            res = client.get_metadata(args.model, ids=ids)
            print(json.dumps(res, indent=2, ensure_ascii=False))
        elif args.command == "external_id":
            ids = json.loads(args.ids)
            res = client.get_external_id(args.model, ids=ids)
            print(json.dumps(res, indent=2, ensure_ascii=False))
        elif args.command == "default_get":
            res = client.default_get(args.model, fields=args.fields)
            print(json.dumps(res, indent=2, ensure_ascii=False))
        elif args.command == "check_access":
            res = client.check_access_rights(args.model, operation=args.operation)
            print(json.dumps({"allowed": res}))
        elif args.command == "user_has_groups":
            res = client.user_has_groups(args.groups)
            print(json.dumps({"has_group": res}))

        # Mutations (guarded by client.allow_write / --write)
        elif args.command == "create":
            vals = json.loads(args.values)
            res = client.create(args.model, vals=vals)
            print(json.dumps({"created_id": res}))
        elif args.command in ("write", "update"):
            ids = json.loads(args.ids)
            vals = json.loads(args.values)
            res = client.write(args.model, ids=ids, vals=vals)
            print(json.dumps({"updated": res}))
        elif args.command in ("unlink", "delete"):
            ids = json.loads(args.ids)
            res = client.unlink(args.model, ids=ids)
            print(json.dumps({"deleted": res}))
        elif args.command == "copy":
            default_vals = json.loads(args.default) if args.default else None
            res = client.copy(args.model, record_id=args.id, default=default_vals)
            print(json.dumps({"copied_id": res}))
        elif args.command == "archive":
            ids = json.loads(args.ids)
            res = client.action_archive(args.model, ids=ids)
            print(json.dumps({"archived": res}))
        elif args.command == "unarchive":
            ids = json.loads(args.ids)
            res = client.action_unarchive(args.model, ids=ids)
            print(json.dumps({"unarchived": res}))

        return 0
    except (
        ValueError,
        RuntimeError,
        PermissionError,
        ConnectionError,
        json.JSONDecodeError,
    ) as e:
        sys.stderr.write(f"Error: {e}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
