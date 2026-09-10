#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Odoo JSON-RPC Client.

Queries and manages Odoo models directly via JSON-RPC.
Requires explicit per-invocation authorization (--allow-rpc / allow_rpc=True)
before initiating any network connection, authentication, or config loading.
Enforces strict allowlisting for safe read-only/introspection queries by default,
and requires independent explicit authorization (--write / allow_write=True)
for state-modifying operations.

Note: Client-side method allowlists do not guarantee server-side read-only transactions,
as custom server-side method implementations or hooks could perform mutations.
Consent flags record explicit user authorization.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

# typing.Union is deprecated in favor of X | Y, but a recursive alias needs
# quoted forward references while X | "Y" is a runtime TypeError (TC010);
# the type statement needs Python 3.12+ and this skill supports 3.10.
from typing import (
    TYPE_CHECKING,
    TypeAlias,
    Union,  # pyright: ignore[reportDeprecated] - see note above
    cast,
)

if TYPE_CHECKING:
    import http.client
    from collections.abc import Callable
    from typing import IO

JsonValue: TypeAlias = Union[  # pyright: ignore[reportDeprecated] - see note above
    bool, int, float, str, "list[JsonValue]", "dict[str, JsonValue]", None
]
JsonObject: TypeAlias = dict[str, JsonValue]
JsonRecord: TypeAlias = dict[str, JsonValue]

_MIN_QUOTED_LENGTH = 2
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
        "get_metadata",
        "get_external_id",
        "default_get",
        "check_access_rights",
        "check_field_access_rights",
        "user_has_groups",
    }
)

# Methods that mutate state (require --write / allow_write=True)
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


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Prevent automatic HTTP redirection to safeguard credentials from leaking."""

    def redirect_request(  # noqa: PLR0913, PLR0917 - stdlib override signature
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: http.client.HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        """Reject automated redirects across all 3xx status codes."""
        del req, fp, code, msg, headers, newurl
        return None


def _is_loopback_host(hostname: str) -> bool:
    """Check if a hostname or IP address is loopback."""
    norm = hostname.strip().lower()
    if norm in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        ip = ipaddress.ip_address(norm)
    except ValueError:
        return False
    else:
        return ip.is_loopback


def _validate_url(raw_url: str, *, verify_ssl: bool = True) -> str:
    """Validate URL structure, schemes, credentials, query/fragments, and transport safety."""
    if not isinstance(raw_url, str) or not raw_url.strip():
        message = "Odoo RPC URL must be a non-empty string."
        raise ValueError(message)

    parsed = urllib.parse.urlsplit(raw_url)
    if parsed.scheme not in ("http", "https"):
        message = "Invalid Odoo RPC URL. Scheme must be http or https."
        raise ValueError(message)
    if not parsed.netloc or not parsed.hostname:
        message = "Invalid Odoo RPC URL. URL must contain a valid host."
        raise ValueError(message)
    if parsed.username or parsed.password:
        message = "Odoo RPC URL must not contain embedded user credentials/userinfo."
        raise ValueError(message)
    if parsed.query:
        message = "Odoo RPC URL must not contain query parameters."
        raise ValueError(message)
    if parsed.fragment:
        message = "Odoo RPC URL must not contain URL fragments."
        raise ValueError(message)

    is_loopback = _is_loopback_host(parsed.hostname)
    if parsed.scheme == "http" and not is_loopback:
        message = (
            "Plaintext HTTP is only permitted for loopback endpoints (127.0.0.1, localhost, ::1); "
            + "remote connections must use HTTPS."
        )
        raise ValueError(message)
    if not verify_ssl and not is_loopback:
        message = (
            "Disabling SSL verification (--insecure / verify_ssl=False) is only permitted for loopback endpoints "
            + "(127.0.0.1, localhost, ::1); remote connections must verify TLS certificates."
        )
        raise ValueError(message)

    norm_url = raw_url.rstrip("/")
    if not norm_url.endswith("/jsonrpc"):
        norm_url = f"{norm_url}/jsonrpc"
    return norm_url


def _check_positive_id(val: object, label: str) -> int:
    """Validate that a value is a strictly positive non-boolean integer."""
    if isinstance(val, bool) or not isinstance(val, int) or val <= 0:
        message = f"Invalid {label}: ID must be a positive non-boolean integer (> 0), got {val!r}."
        raise ValueError(message)
    return val


def _validate_id_list(ids: list[int], label: str = "IDs") -> list[int]:
    """Ensure list of IDs is non-empty and contains only positive non-bool ints."""
    if not isinstance(ids, list) or not ids:
        message = (
            f"Invalid {label}: ID list must be a non-empty list of positive integers."
        )
        raise ValueError(message)
    return [_check_positive_id(item, f"{label} item") for item in ids]


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
        if not key or not key.isidentifier():
            continue
        if (
            len(value) >= _MIN_QUOTED_LENGTH
            and value[0] == value[-1]
            and value[0] in {"'", '"'}
        ):
            value = value[1:-1]
        _ = os.environ.setdefault(key, value)
    return True


def load_env(env_file: Path | str | None = None) -> None:
    """Load explicit .env configuration file with strict fail-closed semantics."""
    target_path_str = env_file or os.environ.get("ODOO_ENV_FILE")
    if not target_path_str:
        return

    path = Path(target_path_str).expanduser()
    if not path.is_file():
        message = f"Explicit .env file not found or unreadable: {path}"
        raise FileNotFoundError(message)
    if not parse_env_file(path):
        message = f"Failed to parse explicit .env file: {path}"
        raise ValueError(message)


@dataclass(frozen=True, slots=True)
class OdooRpcConfig:
    """Validated boundary configuration for Odoo RPC."""

    url: str
    database: str
    user: str
    token: str
    verify_ssl: bool = True

    @classmethod
    def from_env(  # noqa: PLR0913 - parameters mirror the documented CLI/config surface one-to-one
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
        raw_url = _require_field("Odoo RPC URL", url, "ODOO_RPC_URL", "--url")
        resolved_ssl = _resolve_verify_ssl(verify_ssl)
        validated_url = _validate_url(raw_url, verify_ssl=resolved_ssl)
        return cls(
            url=validated_url,
            database=_require_field(
                "Odoo RPC database", database, "ODOO_RPC_DB", "--db"
            ),
            user=_require_field("Odoo RPC user", user, "ODOO_RPC_USER", "--user"),
            token=_resolve_token(token, token_path),
            verify_ssl=resolved_ssl,
        )


def _require_field(label: str, flag: str | None, env_name: str, cli: str) -> str:
    """Resolve one required string from a CLI flag with environment fallback."""
    value = flag or os.environ.get(env_name)
    if not value:
        message = (
            f"Missing {label}. Set {env_name} in your environment/.env "
            + f"or pass {cli}."
        )
        raise ValueError(message)
    return value


def _resolve_token(token: str | None, token_path: Path | str | None) -> str:
    """Resolve the API token from a flag, environment, or explicit token file."""
    if token:
        return token
    if os.environ.get("ODOO_RPC_TOKEN"):
        return os.environ["ODOO_RPC_TOKEN"]

    target_token_path = token_path or os.environ.get("ODOO_RPC_TOKEN_PATH")
    if target_token_path:
        path = Path(target_token_path).expanduser()
        if not path.is_file():
            message = f"Explicit token file not found or unreadable: {path}"
            raise FileNotFoundError(message)
        try:
            resolved = path.read_text(encoding="utf-8").strip()
        except OSError as e:
            message = f"Cannot read token file: {path}"
            raise OSError(message) from e
        else:
            if not resolved:
                message = f"Token file is empty: {path}"
                raise ValueError(message)
            return resolved
    message = (
        "Missing Odoo RPC token. Specify ODOO_RPC_TOKEN, "
        + "provide ODOO_RPC_TOKEN_PATH, or pass --token / --token-path."
    )
    raise ValueError(message)


def _resolve_verify_ssl(verify_ssl: bool | None) -> bool:
    """Resolve SSL verification with a default-true environment fallback."""
    if verify_ssl is not None:
        return verify_ssl
    env_ssl = os.environ.get("ODOO_RPC_VERIFY_SSL", "true").strip().lower()
    return env_ssl not in ("0", "false", "no", "off")


def json_rpc(
    url: str,
    service: str,
    method: str,
    *args: JsonValue,
    allow_rpc: bool = False,
    allow_write: bool = False,
    verify_ssl: bool = True,
    timeout: float = 30.0,
) -> JsonValue:
    """Execute a single JSON-RPC 2.0 call against Odoo.

    Requires explicit per-invocation consent via allow_rpc=True.
    Enforces service allowlists and method permissions at the transport boundary.
    """
    if not allow_rpc:
        message = (
            "RPC BLOCKED: Network JSON-RPC calls require explicit authorization. "
            + "Pass allow_rpc=True (or --allow-rpc on the CLI) to proceed."
        )
        raise PermissionError(message)

    validated_url = _validate_url(url, verify_ssl=verify_ssl)

    if service == "common":
        if method != "authenticate":
            message = (
                f"METHOD FORBIDDEN: common method '{method}' is forbidden; "
                + "only common.authenticate is permitted."
            )
            raise PermissionError(message)
    elif service == "object":
        if method != "execute_kw":
            message = (
                f"METHOD FORBIDDEN: object method '{method}' is forbidden; "
                + "only object.execute_kw is permitted."
            )
            raise PermissionError(message)
        # Check inner method: args are (db, uid, password, model, inner_method, inner_args, inner_kwargs)
        if len(args) < 5 or not isinstance(args[4], str):
            message = (
                "Malformed execute_kw payload: inner method name missing or invalid."
            )
            raise PermissionError(message)
        inner_method = args[4]
        if inner_method in READONLY_ALLOWLIST:
            pass
        elif inner_method in MUTATION_ALLOWLIST:
            if not allow_write:
                message = (
                    f"MUTATION BLOCKED: Method '{inner_method}' modifies data "
                    + "but allow_write=False was specified."
                )
                raise PermissionError(message)
        else:
            message = (
                f"METHOD FORBIDDEN: Method '{inner_method}' is neither in the safe "
                + "allowlist nor the mutation allowlist: "
                + f"{sorted(READONLY_ALLOWLIST | MUTATION_ALLOWLIST)}"
            )
            raise PermissionError(message)
    else:
        message = f"SERVICE FORBIDDEN: JSON-RPC service '{service}' is forbidden."
        raise PermissionError(message)

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

    req = urllib.request.Request(  # noqa: S310 - validated_url is strictly checked by _validate_url
        validated_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "OdooRpcClient/1.0",
        },
    )

    opener = urllib.request.build_opener(
        _NoRedirectHandler(),
        urllib.request.HTTPSHandler(context=ctx),
        urllib.request.HTTPHandler(),
    )

    try:
        with opener.open(  # noqa: S310 - validated_url is strictly checked by _validate_url
            req, timeout=timeout
        ) as raw_resp:  # pyright: ignore[reportAny] - typeshed types open() as Any; narrowed to HTTPResponse on the next line
            resp = cast("http.client.HTTPResponse", raw_resp)
            raw = resp.read().decode("utf-8")
            decoded = cast("object", json.loads(raw))
            if not isinstance(decoded, dict):
                message = "Unexpected JSON-RPC response format from server."
                raise TypeError(message)
            res = cast("dict[object, object]", decoded)
            if "error" in res:
                err_dict = res["error"] if isinstance(res["error"], dict) else {}
                raw_code = err_dict.get("code")
                err_code = (
                    raw_code
                    if isinstance(raw_code, int) and not isinstance(raw_code, bool)
                    else "unknown"
                )
                failure = f"Odoo RPC server error (code {err_code})"
                raise RuntimeError(failure)
            return cast("JsonValue", res.get("result"))
    except urllib.error.HTTPError as e:
        http_failure = f"HTTP {e.code} error from server"
        raise RuntimeError(http_failure) from None
    except urllib.error.URLError:
        connection_failure = "Failed to connect to RPC endpoint"
        raise ConnectionError(connection_failure) from None


class OdooRpcClient:
    """Client providing safe querying and guarded mutations on Odoo via JSON-RPC.

    Note: Client-side method allowlists do not guarantee server-side read-only transactions,
    as custom server-side method implementations or hooks could perform mutations.
    Explicit authorization (--allow-rpc and --write) attests user permission.
    """

    def __init__(
        self,
        config: OdooRpcConfig | None = None,
        *,
        allow_rpc: bool = False,
        allow_write: bool = False,
    ) -> None:
        """Build a client with explicit RPC consent and optional mutation permissions."""
        if not allow_rpc:
            message = (
                "RPC BLOCKED: OdooRpcClient requires explicit authorization. "
                + "Pass allow_rpc=True (or --allow-rpc on the CLI) to proceed."
            )
            raise PermissionError(message)
        self.allow_rpc: bool = allow_rpc
        self.allow_write: bool = allow_write
        self.config: OdooRpcConfig = config or OdooRpcConfig.from_env()
        self._uid: int | None = None

    @property
    def uid(self) -> int:
        """Return the cached authenticated user id."""
        if self._uid is None:
            res = json_rpc(
                self.config.url,
                "common",
                "authenticate",
                self.config.database,
                self.config.user,
                self.config.token,
                {},
                allow_rpc=self.allow_rpc,
                allow_write=self.allow_write,
                verify_ssl=self.config.verify_ssl,
            )
            if not res or not isinstance(res, int) or isinstance(res, bool):
                auth_failure = (
                    f"Authentication failed at {self.config.url} "
                    + f"for user {self.config.user}"
                )
                raise PermissionError(auth_failure)
            self._uid = res
        return self._uid

    def execute(
        self,
        model: str,
        method: str,
        args: list[JsonValue] | None = None,
        kwargs: JsonObject | None = None,
    ) -> JsonValue:
        """Execute a model method after checking method permission policies."""
        if not isinstance(model, str) or not model.strip():
            message = "Model name must be a non-empty string."
            raise ValueError(message)
        if not all(c.isalnum() or c in "._" for c in model):
            message = f"Invalid model name: {model!r}"
            raise ValueError(message)

        if method in READONLY_ALLOWLIST:
            # Safe read-only / introspection methods are allowed without --write
            pass
        elif method in MUTATION_ALLOWLIST:
            if not self.allow_write:
                blocked = (
                    f"MUTATION BLOCKED: Method '{method}' modifies data "
                    + "but --write was not specified. "
                    + "Pass --write to authorize state mutations."
                )
                raise PermissionError(blocked)
        else:
            forbidden = (
                f"METHOD FORBIDDEN: Method '{method}' is neither in the safe "
                + "allowlist nor the mutation allowlist: "
                + f"{sorted(READONLY_ALLOWLIST | MUTATION_ALLOWLIST)}"
            )
            raise PermissionError(forbidden)

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
            allow_rpc=self.allow_rpc,
            allow_write=self.allow_write,
            verify_ssl=self.config.verify_ssl,
        )

    # --- Read & Query Operations ---

    def search_read(  # noqa: PLR0913, PLR0917 - mirrors Odoo's search_read signature position-for-position
        self,
        model: str,
        domain: list[JsonValue] | None = None,
        fields: list[str] | None = None,
        limit: int | None = None,
        offset: int = 0,
        order: str | None = None,
    ) -> list[JsonRecord]:
        """Search records and read their fields in one call."""
        kwargs: JsonObject = {"offset": offset}
        if fields:
            kwargs["fields"] = cast("JsonValue", fields)
        if limit is not None:
            kwargs["limit"] = limit
        if order:
            kwargs["order"] = order
        return cast(
            "list[JsonRecord]",
            self.execute(model, "search_read", [domain or []], kwargs),
        )

    def search_count(self, model: str, domain: list[JsonValue] | None = None) -> int:
        """Count records matching a domain."""
        return cast("int", self.execute(model, "search_count", [domain or []]))

    def read(
        self,
        model: str,
        ids: list[int],
        fields: list[str] | None = None,
    ) -> list[JsonRecord]:
        """Read field values for record ids."""
        valid_ids = _validate_id_list(ids, "ids")
        kwargs: JsonObject = {"fields": cast("JsonValue", fields)} if fields else {}
        return cast(
            "list[JsonRecord]",
            self.execute(model, "read", [cast("JsonValue", valid_ids)], kwargs),
        )

    def fields_get(
        self,
        model: str,
        allfields: list[str] | None = None,
        attributes: list[str] | None = None,
    ) -> JsonObject:
        """Inspect model field definitions."""
        args = [cast("JsonValue", allfields)] if allfields is not None else []
        kwargs: JsonObject = (
            {"attributes": cast("JsonValue", attributes)} if attributes else {}
        )
        return cast("JsonObject", self.execute(model, "fields_get", args, kwargs))

    def get_view(
        self,
        model: str,
        view_id: int | None = None,
        view_type: str = "form",
    ) -> JsonObject:
        """Inspect a rendered view architecture."""
        kwargs: JsonObject = {"view_type": view_type}
        if view_id is not None:
            kwargs["view_id"] = _check_positive_id(view_id, "view_id")
        return cast("JsonObject", self.execute(model, "get_view", [], kwargs))

    def get_views(
        self,
        model: str,
        views: list[list[JsonValue]],
        options: JsonObject | None = None,
    ) -> JsonObject:
        """Inspect rendered view architectures."""
        return cast(
            "JsonObject",
            self.execute(
                model,
                "get_views",
                [cast("JsonValue", views)],
                {"options": options or {}},
            ),
        )

    # --- Safe Introspection Operations ---

    def get_metadata(
        self,
        model: str,
        ids: list[int],
    ) -> list[JsonRecord]:
        """Fetch record metadata for ids."""
        valid_ids = _validate_id_list(ids, "ids")
        return cast(
            "list[JsonRecord]",
            self.execute(model, "get_metadata", [cast("JsonValue", valid_ids)]),
        )

    def get_external_id(
        self,
        model: str,
        ids: list[int],
    ) -> dict[int, str]:
        """Fetch XML external ids for record ids."""
        valid_ids = _validate_id_list(ids, "ids")
        return cast(
            "dict[int, str]",
            self.execute(model, "get_external_id", [cast("JsonValue", valid_ids)]),
        )

    def default_get(
        self,
        model: str,
        fields: list[str],
    ) -> JsonObject:
        """Fetch default values for fields."""
        return cast(
            "JsonObject",
            self.execute(model, "default_get", [cast("JsonValue", fields)]),
        )

    def check_access_rights(
        self,
        model: str,
        operation: str = "read",
        raise_exception: bool = False,
    ) -> bool:
        """Check model access rights for an operation."""
        return cast(
            "bool",
            self.execute(
                model,
                "check_access_rights",
                [operation],
                {"raise_exception": raise_exception},
            ),
        )

    def user_has_groups(
        self,
        groups: str,
    ) -> bool:
        """Check whether the current user has a group."""
        return cast("bool", self.execute("res.users", "user_has_groups", [groups]))

    # --- State Mutation Operations (Guarded by --write / allow_write=True) ---

    def create(
        self,
        model: str,
        vals: JsonObject | list[JsonRecord],
    ) -> int | list[int]:
        """Create records from field values."""
        return cast(
            "int | list[int]", self.execute(model, "create", [cast("JsonValue", vals)])
        )

    def write(
        self,
        model: str,
        ids: list[int],
        vals: JsonObject,
    ) -> bool:
        """Update records with field values."""
        valid_ids = _validate_id_list(ids, "ids")
        if not isinstance(vals, dict) or not vals:
            message = "vals must be a non-empty dictionary of field updates."
            raise ValueError(message)
        return cast(
            "bool",
            self.execute(model, "write", [cast("JsonValue", valid_ids), vals]),
        )

    def unlink(
        self,
        model: str,
        ids: list[int],
    ) -> bool:
        """Delete records by id."""
        valid_ids = _validate_id_list(ids, "ids")
        return cast(
            "bool", self.execute(model, "unlink", [cast("JsonValue", valid_ids)])
        )

    def copy(
        self,
        model: str,
        record_id: int,
        default: JsonObject | None = None,
    ) -> int:
        """Duplicate a record with optional default overrides."""
        valid_id = _check_positive_id(record_id, "record_id")
        kwargs: JsonObject = {"default": default} if default else {}
        return cast("int", self.execute(model, "copy", [valid_id], kwargs))

    def action_archive(
        self,
        model: str,
        ids: list[int],
    ) -> bool:
        """Archive records by id."""
        valid_ids = _validate_id_list(ids, "ids")
        return cast(
            "bool",
            self.execute(model, "action_archive", [cast("JsonValue", valid_ids)]),
        )

    def action_unarchive(
        self,
        model: str,
        ids: list[int],
    ) -> bool:
        """Unarchive records by id."""
        valid_ids = _validate_id_list(ids, "ids")
        return cast(
            "bool",
            self.execute(model, "action_unarchive", [cast("JsonValue", valid_ids)]),
        )

    def toggle_active(
        self,
        model: str,
        ids: list[int],
    ) -> bool:
        """Toggle the active flag on records."""
        valid_ids = _validate_id_list(ids, "ids")
        return cast(
            "bool",
            self.execute(model, "toggle_active", [cast("JsonValue", valid_ids)]),
        )


def build_parser() -> argparse.ArgumentParser:
    """Build the Odoo RPC command-line parser."""
    parser = argparse.ArgumentParser(
        description="Odoo JSON-RPC Client (Safe Querying & Guarded Mutations)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    # Global consent & connection overrides
    _ = parser.add_argument(
        "--allow-rpc",
        action="store_true",
        help="Acknowledge and authorize live network JSON-RPC calls (required)",
    )
    _ = parser.add_argument("--url", help="Odoo JSON-RPC endpoint URL")
    _ = parser.add_argument("--db", help="Odoo database name")
    _ = parser.add_argument("--user", help="Odoo user login")
    _ = parser.add_argument("--token", help="Odoo API token or password")
    _ = parser.add_argument("--token-path", help="Path to token file")
    _ = parser.add_argument(
        "--insecure",
        action="store_true",
        help="Disable SSL certificate verification (loopback only)",
    )
    _ = parser.add_argument(
        "--env-file", help="Path to specific .env configuration file"
    )
    _ = parser.add_argument(
        "--write",
        action="store_true",
        help="Authorize state mutations (create, write, unlink, archive, copy)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)
    _add_query_parsers(subparsers.add_parser)
    _add_introspection_parsers(subparsers.add_parser)
    _add_mutation_parsers(subparsers.add_parser)
    return parser


def _add_query_parsers(
    add_parser: Callable[..., argparse.ArgumentParser],
) -> None:
    """Register read-query subcommands."""
    # --- Query Commands ---
    sr_parser = add_parser("search_read", help="Execute search_read query")
    _ = sr_parser.add_argument("model", help="Model name (e.g. crm.lead)")
    _ = sr_parser.add_argument(
        "domain",
        nargs="?",
        default="[]",
        help='Domain as JSON array (e.g. \'[["active", "=", true]]\')',
    )
    _ = sr_parser.add_argument(
        "--fields", nargs="*", default=None, help="Field names to retrieve"
    )
    _ = sr_parser.add_argument(
        "--limit", type=int, default=10, help="Maximum records to return"
    )
    _ = sr_parser.add_argument("--offset", type=int, default=0, help="Record offset")
    _ = sr_parser.add_argument(
        "--order", default=None, help="Sort order (e.g. 'id desc')"
    )

    count_parser = add_parser("count", help="Count matching records")
    _ = count_parser.add_argument("model", help="Model name")
    _ = count_parser.add_argument(
        "domain",
        nargs="?",
        default="[]",
        help="Domain as JSON array",
    )

    read_parser = add_parser("read", help="Read records by ID")
    _ = read_parser.add_argument("model", help="Model name")
    _ = read_parser.add_argument(
        "ids", help='Record IDs as JSON array (e.g. "[1, 2, 3]")'
    )
    _ = read_parser.add_argument(
        "--fields", nargs="*", default=None, help="Field names to retrieve"
    )


def _add_introspection_parsers(
    add_parser: Callable[..., argparse.ArgumentParser],
) -> None:
    """Register safe-introspection subcommands."""
    fg_parser = add_parser("fields_get", help="Inspect Model fields definition")
    _ = fg_parser.add_argument("model", help="Model name")
    _ = fg_parser.add_argument(
        "--fields", nargs="*", default=None, help="Specific fields to inspect"
    )

    gv_parser = add_parser("get_view", help="Inspect rendered view architecture")
    _ = gv_parser.add_argument("model", help="Model name")
    _ = gv_parser.add_argument(
        "--view-id", type=int, default=None, help="Specific view ID"
    )
    _ = gv_parser.add_argument(
        "--view-type",
        default="form",
        help="View type (form, list/tree, search)",
    )

    meta_parser = add_parser(
        "metadata", help="Get record metadata (create_date, write_date, XML IDs)"
    )
    _ = meta_parser.add_argument("model", help="Model name")
    _ = meta_parser.add_argument(
        "ids", help='Record IDs as JSON array (e.g. "[1, 2, 3]")'
    )

    ext_parser = add_parser("external_id", help="Retrieve XML External IDs for records")
    _ = ext_parser.add_argument("model", help="Model name")
    _ = ext_parser.add_argument(
        "ids", help='Record IDs as JSON array (e.g. "[1, 2, 3]")'
    )

    def_parser = add_parser("default_get", help="Retrieve default values for fields")
    _ = def_parser.add_argument("model", help="Model name")
    _ = def_parser.add_argument(
        "fields", nargs="+", help="Field names to inspect default values for"
    )

    access_parser = add_parser("check_access", help="Check Model access rights")
    _ = access_parser.add_argument("model", help="Model name")
    _ = access_parser.add_argument(
        "operation",
        default="read",
        choices=["read", "write", "create", "unlink"],
    )

    group_parser = add_parser("user_has_groups", help="Check if current user has group")
    _ = group_parser.add_argument(
        "groups", help="Group XML ID (e.g. 'base.group_system')"
    )


def _add_mutation_parsers(
    add_parser: Callable[..., argparse.ArgumentParser],
) -> None:
    """Register guarded state-mutation subcommands."""
    create_parser = add_parser("create", help="Create new record(s) (requires --write)")
    _ = create_parser.add_argument("model", help="Model name")
    _ = create_parser.add_argument(
        "values", help="Field values as JSON object or array of objects"
    )

    update_parser = add_parser(
        "write", aliases=["update"], help="Update existing records (requires --write)"
    )
    _ = update_parser.add_argument("model", help="Model name")
    _ = update_parser.add_argument(
        "ids", help='Record IDs as JSON array (e.g. "[1, 2, 3]")'
    )
    _ = update_parser.add_argument(
        "values", help="Field values to update as JSON object"
    )

    unlink_parser = add_parser(
        "unlink", aliases=["delete"], help="Delete records (requires --write)"
    )
    _ = unlink_parser.add_argument("model", help="Model name")
    _ = unlink_parser.add_argument(
        "ids", help='Record IDs as JSON array (e.g. "[1, 2, 3]")'
    )

    copy_parser = add_parser("copy", help="Duplicate a record (requires --write)")
    _ = copy_parser.add_argument("model", help="Model name")
    _ = copy_parser.add_argument("id", type=int, help="Record ID to duplicate")
    _ = copy_parser.add_argument(
        "--default", default=None, help="Default override values as JSON object"
    )

    archive_parser = add_parser(
        "archive", help="Archive records by setting active=False (requires --write)"
    )
    _ = archive_parser.add_argument("model", help="Model name")
    _ = archive_parser.add_argument("ids", help="Record IDs as JSON array)")

    unarchive_parser = add_parser(
        "unarchive", help="Unarchive records by setting active=True (requires --write)"
    )
    _ = unarchive_parser.add_argument("model", help="Model name")
    _ = unarchive_parser.add_argument("ids", help="Record IDs as JSON array)")


def _optional_str(args: argparse.Namespace, field: str) -> str | None:
    """Narrow an optional string flag to a typed value."""
    value = cast("object", getattr(args, field, None))
    return value if isinstance(value, str) else None


def _optional_str_list(args: argparse.Namespace, field: str) -> list[str] | None:
    """Narrow an optional string-list flag to a typed value."""
    value = cast("object", getattr(args, field))
    if value is None:
        return None
    items = cast("list[object]", value)
    return [item for item in items if isinstance(item, str)]


def _optional_int(args: argparse.Namespace, field: str, default: int) -> int:
    """Narrow an optional integer flag to a typed value."""
    value = cast("object", getattr(args, field))
    return value if isinstance(value, int) else default


def _optional_flag(args: argparse.Namespace, field: str) -> bool:
    """Narrow an optional boolean flag to a typed value."""
    value = cast("object", getattr(args, field))
    return value if isinstance(value, bool) else False


def _required_str(args: argparse.Namespace, field: str) -> str:
    """Narrow a required string argument to a typed value."""
    value = cast("object", getattr(args, field))
    if not isinstance(value, str):
        message = f"Missing required argument: {field}."
        raise TypeError(message)
    return value


def _required_int(args: argparse.Namespace, field: str) -> int:
    """Narrow a required integer argument to a typed value."""
    value = cast("object", getattr(args, field))
    if not isinstance(value, int) or isinstance(value, bool):
        message = f"Invalid integer argument: {field}."
        raise TypeError(message)
    return value


def _json_list(text: str, label: str) -> list[JsonValue]:
    """Parse a CLI JSON-array argument."""
    try:
        value = cast("object", json.loads(text))
    except json.JSONDecodeError as exc:
        message = f"Invalid {label} JSON: {exc}."
        raise ValueError(message) from exc
    if not isinstance(value, list):
        message = f"Invalid {label} JSON: expected an array."
        raise TypeError(message)
    return cast("list[JsonValue]", value)


def _json_object_arg(text: str, label: str) -> JsonObject:
    """Parse a CLI JSON-object argument."""
    try:
        value = cast("object", json.loads(text))
    except json.JSONDecodeError as exc:
        message = f"Invalid {label} JSON: {exc}."
        raise ValueError(message) from exc
    if not isinstance(value, dict):
        message = f"Invalid {label} JSON: expected an object."
        raise TypeError(message)
    return cast("JsonObject", value)


def _json_vals(text: str, label: str) -> JsonObject | list[JsonRecord]:
    """Parse a CLI JSON argument that may be an object or a non-empty array of objects."""
    try:
        value = cast("object", json.loads(text))
    except json.JSONDecodeError as exc:
        message = f"Invalid {label} JSON: {exc}."
        raise ValueError(message) from exc
    if isinstance(value, dict):
        if not all(isinstance(k, str) for k in value):
            message = f"Invalid {label} JSON: keys must be strings."
            raise TypeError(message)
        return cast("JsonObject", value)
    if isinstance(value, list) and value:
        for idx, item in enumerate(value):
            if not isinstance(item, dict) or not all(isinstance(k, str) for k in item):
                message = (
                    f"Invalid {label} JSON item at index {idx}: "
                    + "expected an object with string keys."
                )
                raise TypeError(message)
        return cast("list[JsonRecord]", value)
    message = (
        f"Invalid {label} JSON: expected an object or a non-empty array of objects."
    )
    raise TypeError(message)


def _id_list(text: str, label: str) -> list[int]:
    """Parse a CLI JSON-array-of-ids argument with strict positive integer checks."""
    raw_list = _json_list(text, label)
    if not raw_list:
        message = f"Invalid {label}: ID list must not be empty."
        raise ValueError(message)
    return [_check_positive_id(item, f"{label} item") for item in raw_list]


def main(argv: list[str] | None = None) -> int:
    """Run the Odoo RPC command-line interface."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if not _optional_flag(args, "allow_rpc"):
        _ = sys.stderr.write(
            "RPC BLOCKED: Network RPC access requires explicit authorization. "
            + "Pass --allow-rpc to proceed.\n"
        )
        return 1

    command = _required_str(args, "command")
    if command not in _ALL_COMMANDS:
        _ = sys.stderr.write(f"Error: Unknown command: {command}.\n")
        return 1

    if command in _MUTATION_COMMANDS and not _optional_flag(args, "write"):
        _ = sys.stderr.write(
            f"MUTATION BLOCKED: Command '{command}' modifies data "
            + "but --write was not specified. Pass --write to authorize state mutations.\n"
        )
        return 1

    try:
        load_env(_optional_str(args, "env_file"))
        config = OdooRpcConfig.from_env(
            url=_optional_str(args, "url"),
            database=_optional_str(args, "db"),
            user=_optional_str(args, "user"),
            token=_optional_str(args, "token"),
            token_path=_optional_str(args, "token_path"),
            verify_ssl=False if _optional_flag(args, "insecure") else None,
        )
        client = OdooRpcClient(
            config,
            allow_rpc=True,
            allow_write=_optional_flag(args, "write"),
        )
        if command in _READ_COMMANDS:
            _run_read_commands(client, args, command)
        elif command in _INSPECTION_COMMANDS:
            _run_inspection_commands(client, args, command)
        else:
            _run_mutation_commands(client, args, command)
    except (
        ValueError,
        TypeError,
        RuntimeError,
        PermissionError,
        ConnectionError,
        FileNotFoundError,
        OSError,
        json.JSONDecodeError,
    ) as exc:
        _ = sys.stderr.write(f"Error: {exc}\n")
        return 1
    else:
        return 0


_READ_COMMANDS = frozenset({"search_read", "count", "read"})
_INSPECTION_COMMANDS = frozenset(
    {
        "fields_get",
        "get_view",
        "metadata",
        "external_id",
        "default_get",
        "check_access",
        "user_has_groups",
    }
)
_MUTATION_COMMANDS = frozenset(
    {
        "create",
        "write",
        "update",
        "unlink",
        "delete",
        "copy",
        "archive",
        "unarchive",
    }
)
_ALL_COMMANDS = _READ_COMMANDS | _INSPECTION_COMMANDS | _MUTATION_COMMANDS


def _emit(payload: object) -> None:
    """Print a JSON payload with the command's documented shape."""
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def _emit_compact(payload: object) -> None:
    """Print a single-line JSON payload."""
    print(json.dumps(payload))


def _required_str_list(args: argparse.Namespace, field: str) -> list[str]:
    """Narrow a required string-list argument to a typed value."""
    value = cast("object", getattr(args, field))
    if not isinstance(value, list):
        message = f"Missing required argument: {field}."
        raise TypeError(message)
    items = cast("list[object]", value)
    return [item for item in items if isinstance(item, str)]


def _optional_int_or_none(args: argparse.Namespace, field: str) -> int | None:
    """Narrow an optional integer-or-null flag to a typed value."""
    value = cast("object", getattr(args, field))
    return value if isinstance(value, int) else None


def _run_read_commands(
    client: OdooRpcClient, args: argparse.Namespace, command: str
) -> None:
    """Run search/count/read subcommands."""
    model = _required_str(args, "model")
    if command == "search_read":
        res = client.search_read(
            model,
            domain=_json_list(_required_str(args, "domain"), "domain"),
            fields=_optional_str_list(args, "fields"),
            limit=_optional_int(args, "limit", 10),
            offset=_optional_int(args, "offset", 0),
            order=_optional_str(args, "order"),
        )
        _emit(res)
    elif command == "count":
        res = client.search_count(
            model, domain=_json_list(_required_str(args, "domain"), "domain")
        )
        _emit_compact({"count": res})
    elif command == "read":
        res = client.read(
            model,
            ids=_id_list(_required_str(args, "ids"), "ids"),
            fields=_optional_str_list(args, "fields"),
        )
        _emit(res)
    else:
        message = f"Unknown read command: {command}."
        raise ValueError(message)


def _run_inspection_commands(
    client: OdooRpcClient, args: argparse.Namespace, command: str
) -> None:
    """Run safe-introspection subcommands."""
    model = _required_str(args, "model")
    if command == "fields_get":
        _emit(client.fields_get(model, allfields=_optional_str_list(args, "fields")))
    elif command == "get_view":
        _emit(
            client.get_view(
                model,
                view_id=_optional_int_or_none(args, "view_id"),
                view_type=_required_str(args, "view_type"),
            )
        )
    elif command == "metadata":
        _emit(
            client.get_metadata(model, ids=_id_list(_required_str(args, "ids"), "ids"))
        )
    elif command == "external_id":
        _emit(
            client.get_external_id(
                model, ids=_id_list(_required_str(args, "ids"), "ids")
            )
        )
    elif command == "default_get":
        _emit(client.default_get(model, fields=_required_str_list(args, "fields")))
    elif command == "check_access":
        _emit_compact(
            {
                "allowed": client.check_access_rights(
                    model, operation=_required_str(args, "operation")
                )
            }
        )
    elif command == "user_has_groups":
        _emit_compact(
            {"has_group": client.user_has_groups(_required_str(args, "groups"))}
        )
    else:
        message = f"Unknown inspection command: {command}."
        raise ValueError(message)


def _run_mutation_commands(
    client: OdooRpcClient, args: argparse.Namespace, command: str
) -> None:
    """Run guarded state-mutation subcommands."""
    model = _required_str(args, "model")
    if command == "create":
        vals = _json_vals(_required_str(args, "values"), "values")
        _emit_compact({"created_id": client.create(model, vals=vals)})
    elif command in ("write", "update"):
        ids = _id_list(_required_str(args, "ids"), "ids")
        vals = _json_object_arg(_required_str(args, "values"), "values")
        _emit_compact({"updated": client.write(model, ids=ids, vals=vals)})
    elif command in ("unlink", "delete"):
        ids = _id_list(_required_str(args, "ids"), "ids")
        _emit_compact({"deleted": client.unlink(model, ids=ids)})
    elif command == "copy":
        default_text = _optional_str(args, "default")
        default_vals = (
            _json_object_arg(default_text, "default") if default_text else None
        )
        _emit_compact(
            {
                "copied_id": client.copy(
                    model,
                    record_id=_required_int(args, "id"),
                    default=default_vals,
                )
            }
        )
    elif command == "archive":
        ids = _id_list(_required_str(args, "ids"), "ids")
        _emit_compact({"archived": client.action_archive(model, ids=ids)})
    elif command == "unarchive":
        ids = _id_list(_required_str(args, "ids"), "ids")
        _emit_compact({"unarchived": client.action_unarchive(model, ids=ids)})
    else:
        message = f"Unknown mutation command: {command}."
        raise ValueError(message)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
