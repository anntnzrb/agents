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
import contextlib
import hashlib
import ipaddress
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
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
    from typing import IO

JsonValue: TypeAlias = Union[  # pyright: ignore[reportDeprecated] - see note above
    bool, int, float, str, "list[JsonValue]", "dict[str, JsonValue]", None
]
JsonObject: TypeAlias = dict[str, JsonValue]
JsonRecord: TypeAlias = dict[str, JsonValue]

SKILL_DIR: Path = Path(__file__).resolve().parent.parent
_MIN_QUOTED_LENGTH = 2
_MAX_ERROR_MESSAGE_LEN = 500
_PLAN_ID_HEX_LEN = 10
_DOMAIN_JSON_HINT = (
    'expected JSON like \'[["field","=","value"]]\' (double quotes, lists not tuples)'
)

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

# Hard deny-list for production (non-loopback) endpoints, citing Odoo 17 risks:
# - unlink: BaseModel.unlink permanently deletes rows and on ir.model.fields drops SQL columns.
# - ^_: private/internal methods (_auto_init, _drop_column, etc.) bypass public ORM guards.
# - button_immediate_*, button_(un)?install, button_upgrade, module_uninstall:
#   ir.module.module transitions mutate the live module registry, views, and schema.
# - run, method_direct_trigger: ir.actions.server.run / ir.cron.method_direct_trigger execute
#   arbitrary server actions or scheduled jobs immediately in production.
# - send, send_*, action_.*send, action_launch, message_post, message_notify:
#   mail.thread / mail.mail / mailing.mailing methods dispatch live external emails/WhatsApp/notifications.
# - merge: partner/lead merge wizards destructively reassign foreign keys and unlink source records.
# - action_post, reconcile, action_sign, action_mass_sign, action_liquidate,
#   action_payslip_done, action_paid: accounting, electronic invoicing/signing, treasury,
#   and payroll state transitions lock moves, consume sequences, and post legal documents.
# - set_param: ir.config_parameter.set_param alters global system configuration/secrets.
# - change_password, action_reset_password: res.users credential mutation and reset emails.
PROD_DENIED_METHOD_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"^unlink$", "Odoo 17 BaseModel.unlink permanently deletes records"),
    (r"^_", "Odoo 17 private/internal methods starting with '_' are forbidden"),
    (
        r"^button_immediate_",
        "Odoo 17 ir.module.module immediate module state changes are forbidden",
    ),
    (
        r"^button_(un)?install",
        "Odoo 17 module install/uninstall actions are forbidden",
    ),
    (r"^button_upgrade", "Odoo 17 module upgrade actions are forbidden"),
    (
        r"^module_uninstall$",
        "Odoo 17 ir.module.module.module_uninstall drops tables and data",
    ),
    (
        r"^run$",
        "Odoo 17 ir.actions.server.run executes arbitrary server action code",
    ),
    (
        r"^method_direct_trigger$",
        "Odoo 17 ir.cron.method_direct_trigger triggers live cron execution",
    ),
    (r"^send$", "Odoo 17 live message/email dispatch via send is forbidden"),
    (r"^send_", "Odoo 17 outbound send_* methods dispatch live messages"),
    (
        r"^action_.*send",
        "Odoo 17 workflow send actions dispatch live external messages",
    ),
    (
        r"^action_launch$",
        "Odoo 17 campaign/mailing launch dispatches live external messages",
    ),
    (
        r"^message_post$",
        "Odoo 17 mail.thread.message_post posts chatter messages and notifies followers",
    ),
    (
        r"^message_notify$",
        "Odoo 17 mail.thread.message_notify sends live partner notifications",
    ),
    (
        r"merge",
        "Odoo 17 merge operations destructively reassign references and unlink records",
    ),
    (
        r"^action_post$",
        "Odoo 17 account.move.action_post locks accounting entries and sequences",
    ),
    (
        r"^reconcile",
        "Odoo 17 account.move.line.reconcile mutates accounting reconciliation state",
    ),
    (r"^action_sign", "Odoo 17 electronic signing actions are forbidden"),
    (r"^action_mass_sign", "Odoo 17 batch electronic signing actions are forbidden"),
    (r"^action_liquidate", "Odoo 17 liquidation actions are forbidden"),
    (
        r"^action_payslip_done$",
        "Odoo 17 hr.payslip.action_payslip_done locks payslips and posts entries",
    ),
    (r"^action_paid$", "Odoo 17 payment state transitions are forbidden"),
    (
        r"^set_param$",
        "Odoo 17 ir.config_parameter.set_param mutates global system parameters",
    ),
    (r"change_password", "Odoo 17 user password changes are forbidden"),
    (
        r"^action_reset_password$",
        "Odoo 17 res.users.action_reset_password sends reset emails and invalidates tokens",
    ),
)
PROD_DENIED_METHODS: tuple[str, ...] = tuple(
    pattern for pattern, _ in PROD_DENIED_METHOD_PATTERNS
)
_COMPILED_DENIED_METHODS: tuple[tuple[re.Pattern[str], str, str], ...] = tuple(
    (re.compile(pattern), pattern, reason)
    for pattern, reason in PROD_DENIED_METHOD_PATTERNS
)

# Odoo 17 schema, module registry, system parameter, ACL, and merge wizard models where
# create/write/write-batch/copy/call are denied on production (archive/unarchive remain allowed).
PROD_DENIED_MODELS: frozenset[str] = frozenset(
    {
        "ir.model",
        "ir.model.fields",
        "ir.model.data",
        "ir.model.relation",
        "ir.model.constraint",
        "ir.module.module",
        "ir.module.module.dependency",
        "ir.config_parameter",
        "ir.rule",
        "ir.model.access",
        "res.groups",
        "base.partner.merge.automatic.wizard",
    }
)

# Odoo 17 credential fields denied in create/write/write-batch on any model in production.
PROD_DENIED_VALUE_KEYS: frozenset[str] = frozenset(
    {
        "password",
        "new_password",
    }
)


class ProductionDeniedError(PermissionError):
    """Raised when an operation is hard-denied on a production (non-loopback) endpoint."""


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


def is_loopback(url: OdooRpcConfig | str) -> bool:
    """Return True if a URL or OdooRpcConfig targets a loopback host (127.0.0.1, ::1, localhost)."""
    raw_url = url.url if isinstance(url, OdooRpcConfig) else url
    parsed = urllib.parse.urlsplit(raw_url)
    if not parsed.hostname:
        return _is_loopback_host(raw_url)
    return _is_loopback_host(parsed.hostname)


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


def default_env_file() -> Path:
    """Return default .env path within the skill directory."""
    return SKILL_DIR / ".env"


def load_env(env_file: Path | str | None = None) -> None:
    """Load explicit or default .env configuration file with fail-closed semantics."""
    explicit_target = env_file or os.environ.get("ODOO_ENV_FILE")
    if explicit_target:
        path = Path(explicit_target).expanduser()
        if not path.is_file():
            message = f"Explicit .env file not found or unreadable: {path}"
            raise FileNotFoundError(message)
        if not parse_env_file(path):
            message = f"Failed to parse explicit .env file: {path}"
            raise ValueError(message)
        return

    default_path = default_env_file()
    if default_path and Path(default_path).is_file():
        _ = parse_env_file(Path(default_path))


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
    allow_custom_method: bool = False,
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
        elif allow_custom_method and allow_write and not inner_method.startswith("_"):
            pass
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
                data_obj = err_dict.get("data")
                data_dict = data_obj if isinstance(data_obj, dict) else {}
                data_name = (
                    data_dict.get("name")
                    if isinstance(data_dict.get("name"), str)
                    else ""
                )

                raw_msg = ""
                data_msg = data_dict.get("message")
                if isinstance(data_msg, str) and data_msg.strip():
                    raw_msg = data_msg
                else:
                    err_msg = err_dict.get("message")
                    if isinstance(err_msg, str) and err_msg.strip():
                        raw_msg = err_msg

                first_line = raw_msg.splitlines()[0].strip() if raw_msg else ""

                if data_name and first_line:
                    detail = f"{data_name}: {first_line}"
                elif data_name:
                    detail = data_name
                elif first_line:
                    detail = first_line
                else:
                    detail = ""

                if detail:
                    failure = f"Odoo RPC server error (code {err_code}): {detail}"
                else:
                    failure = f"Odoo RPC server error (code {err_code})"

                if len(failure) > _MAX_ERROR_MESSAGE_LEN:
                    failure = failure[:_MAX_ERROR_MESSAGE_LEN]
                raise RuntimeError(failure)
            return cast("JsonValue", res.get("result"))
    except urllib.error.HTTPError as e:
        http_failure = f"HTTP {e.code} error from server"
        raise RuntimeError(http_failure) from None
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", None)
        is_ssl_cert_error = False
        if (
            isinstance(reason, ssl.SSLCertVerificationError)
            or (
                isinstance(reason, ssl.SSLError)
                and "CERTIFICATE_VERIFY_FAILED" in str(reason)
            )
            or (
                isinstance(reason, Exception)
                and (
                    "certificate verify failed" in str(reason).lower()
                    or "certificate_verify_failed" in str(reason).lower()
                )
            )
            or (
                isinstance(reason, str)
                and (
                    "certificate verify failed" in reason.lower()
                    or "certificate_verify_failed" in reason.lower()
                )
            )
        ):
            is_ssl_cert_error = True

        if is_ssl_cert_error:
            raise ConnectionError(
                "SSL certificate verification failed; set SSL_CERT_FILE to a CA bundle"
            ) from None
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
        *,
        allow_custom: bool = False,
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
        elif method in MUTATION_ALLOWLIST or (
            allow_custom and not method.startswith("_")
        ):
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
            allow_custom_method=allow_custom,
            verify_ssl=self.config.verify_ssl,
        )

    def read_group(  # noqa: PLR0913, PLR0917
        self,
        model: str,
        groupby: list[str],
        domain: list[JsonValue] | None = None,
        fields: list[str] | None = None,
        orderby: str | None = None,
        lazy: bool = False,
        offset: int = 0,
        limit: int | None = None,
    ) -> list[JsonRecord]:
        """Execute read_group query on model."""
        args: list[JsonValue] = [
            cast("JsonValue", domain or []),
            cast("JsonValue", fields or []),
            cast("JsonValue", groupby),
        ]
        kwargs: JsonObject = {"lazy": lazy, "offset": offset}
        if orderby:
            kwargs["orderby"] = orderby
        if limit is not None:
            kwargs["limit"] = limit
        return cast("list[JsonRecord]", self.execute(model, "read_group", args, kwargs))

    def call(
        self,
        model: str,
        method: str,
        args: list[JsonValue] | None = None,
        kwargs: JsonObject | None = None,
    ) -> JsonValue:
        """Call arbitrary model method (guarded by allow_write for non-readonly methods)."""
        if method.startswith("_"):
            message = f"Private methods starting with '_' are forbidden: {method}"
            raise ValueError(message)
        return self.execute(model, method, args, kwargs, allow_custom=True)

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


def _build_parent_parser() -> argparse.ArgumentParser:
    """Build a shared parent parser with default=argparse.SUPPRESS for flag-merging."""
    parent = argparse.ArgumentParser(add_help=False)
    _ = parent.add_argument(
        "--allow-rpc",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Acknowledge and authorize live network JSON-RPC calls",
    )
    _ = parent.add_argument(
        "--write",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Authorize state mutations",
    )
    _ = parent.add_argument(
        "--url", default=argparse.SUPPRESS, help="Odoo JSON-RPC endpoint URL"
    )
    _ = parent.add_argument(
        "--db", default=argparse.SUPPRESS, help="Odoo database name"
    )
    _ = parent.add_argument("--user", default=argparse.SUPPRESS, help="Odoo user login")
    _ = parent.add_argument(
        "--token", default=argparse.SUPPRESS, help="Odoo API token or password"
    )
    _ = parent.add_argument(
        "--token-path", default=argparse.SUPPRESS, help="Path to token file"
    )
    _ = parent.add_argument(
        "--insecure",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Disable SSL certificate verification (loopback only)",
    )
    _ = parent.add_argument(
        "--env-file",
        default=argparse.SUPPRESS,
        help="Path to specific .env configuration file",
    )
    _ = parent.add_argument(
        "--json",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Emit JSON formatted output",
    )
    return parent


def build_parser() -> argparse.ArgumentParser:
    """Build the Odoo RPC command-line parser."""
    parser = argparse.ArgumentParser(
        description="Odoo JSON-RPC Client (Safe Querying & Guarded Mutations)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    # Global consent & connection overrides (with real defaults)
    _ = parser.add_argument(
        "--allow-rpc",
        action="store_true",
        default=False,
        help="Acknowledge and authorize live network JSON-RPC calls (required)",
    )
    _ = parser.add_argument("--url", default=None, help="Odoo JSON-RPC endpoint URL")
    _ = parser.add_argument("--db", default=None, help="Odoo database name")
    _ = parser.add_argument("--user", default=None, help="Odoo user login")
    _ = parser.add_argument("--token", default=None, help="Odoo API token or password")
    _ = parser.add_argument("--token-path", default=None, help="Path to token file")
    _ = parser.add_argument(
        "--insecure",
        action="store_true",
        default=False,
        help="Disable SSL certificate verification (loopback only)",
    )
    _ = parser.add_argument(
        "--env-file", default=None, help="Path to specific .env configuration file"
    )
    _ = parser.add_argument(
        "--write",
        action="store_true",
        default=False,
        help="Authorize state mutations (create, write, unlink, archive, copy)",
    )
    _ = parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Emit output in JSON format",
    )

    parent_parser = _build_parent_parser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_subparser(
        name: str,
        *,
        help: str | None = None,  # noqa: A002
        aliases: Sequence[str] = (),
    ) -> argparse.ArgumentParser:
        return subparsers.add_parser(
            name, parents=[parent_parser], help=help, aliases=aliases
        )

    _add_query_parsers(add_subparser)
    _add_introspection_parsers(add_subparser)
    _add_mutation_parsers(add_subparser)
    _add_plan_parsers(add_subparser)
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

    rg_parser = add_parser("read_group", help="Execute read_group query")
    _ = rg_parser.add_argument("model", help="Model name")
    _ = rg_parser.add_argument(
        "domain",
        nargs="?",
        default="[]",
        help="Domain as JSON array",
    )
    _ = rg_parser.add_argument(
        "--groupby",
        nargs="+",
        required=True,
        help="Fields to group by",
    )
    _ = rg_parser.add_argument(
        "--fields",
        nargs="*",
        default=None,
        help="Fields or aggregate specs to retrieve",
    )
    _ = rg_parser.add_argument(
        "--orderby",
        default=None,
        help="Sort order for groups",
    )
    _ = rg_parser.add_argument(
        "--lazy",
        action="store_true",
        default=False,
        help="Whether to group only by the first groupby field",
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
    call_parser = add_parser("call", help="Call arbitrary model method")
    _ = call_parser.add_argument("model", help="Model name")
    _ = call_parser.add_argument("method", help="Method name")
    _ = call_parser.add_argument(
        "--ids", default=None, help="Record IDs as JSON integer or array"
    )
    _ = call_parser.add_argument(
        "--args", default=None, help="Method arguments as JSON array"
    )
    _ = call_parser.add_argument(
        "--kwargs", default=None, help="Method keyword arguments as JSON object"
    )

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

    wb_parser = add_parser(
        "write-batch",
        help="Update records in batch from JSON mapping id -> values (requires --write)",
    )
    _ = wb_parser.add_argument("model", help="Model name")
    _ = wb_parser.add_argument(
        "file", help="Path to JSON file with id->values mapping, or '-' for stdin"
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
    _ = archive_parser.add_argument("ids", help="Record IDs as JSON array")

    unarchive_parser = add_parser(
        "unarchive", help="Unarchive records by setting active=True (requires --write)"
    )
    _ = unarchive_parser.add_argument("model", help="Model name")
    _ = unarchive_parser.add_argument("ids", help="Record IDs as JSON array")


def _add_plan_parsers(
    add_parser: Callable[..., argparse.ArgumentParser],
) -> None:
    """Register plan execution and revert subcommands."""
    apply_parser = add_parser(
        "apply", help="Apply a planned mutation (requires --write)"
    )
    _ = apply_parser.add_argument("plan_id", help="10-hex plan ID")

    revert_parser = add_parser(
        "revert", help="Revert an applied plan by generating a compensating plan"
    )
    _ = revert_parser.add_argument("plan_id", help="10-hex plan ID")


def normalize_fields(fields: Sequence[str] | str | None) -> list[str] | None:
    """Normalize fields from 'a b', 'a,b', or JSON array string to a list of field names."""
    if fields is None:
        return None
    raw_items: Sequence[str] = [fields] if isinstance(fields, str) else fields
    result: list[str] = []
    for item in raw_items:
        text = item.strip()
        if not text:
            continue
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = cast("object", json.loads(text))
                if isinstance(parsed, list):
                    for sub in parsed:
                        if isinstance(sub, str) and sub.strip():
                            result.append(sub.strip())
                    continue
            except json.JSONDecodeError:
                pass
        for part in text.replace(",", " ").split():
            if part:
                result.append(part)
    return result


def _json_domain(text: str) -> list[JsonValue]:
    """Parse a CLI domain argument expecting a JSON array with hint on error."""
    try:
        value = cast("object", json.loads(text))
    except json.JSONDecodeError as exc:
        message = f"Invalid domain JSON: {exc} ({_DOMAIN_JSON_HINT})."
        raise ValueError(message) from exc
    if not isinstance(value, list):
        message = f"Invalid domain JSON: expected an array ({_DOMAIN_JSON_HINT})."
        raise TypeError(message)
    return cast("list[JsonValue]", value)


def _json_list(text: str, label: str) -> list[JsonValue]:
    """Parse a CLI JSON-array argument."""
    try:
        value = cast("object", json.loads(text))
    except json.JSONDecodeError as exc:
        hint = f" ({_DOMAIN_JSON_HINT})" if label == "domain" else ""
        message = f"Invalid {label} JSON: {exc}.{hint}"
        raise ValueError(message) from exc
    if not isinstance(value, list):
        hint = f" ({_DOMAIN_JSON_HINT})" if label == "domain" else ""
        message = f"Invalid {label} JSON: expected an array.{hint}"
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


def _parse_call_ids(text: str | None) -> list[int] | None:
    """Parse call --ids flag accepting a positive integer or JSON array of integers."""
    if not text:
        return None
    try:
        val = cast("object", json.loads(text))
    except json.JSONDecodeError as exc:
        message = f"Invalid --ids JSON: {exc}."
        raise ValueError(message) from exc
    if isinstance(val, int) and not isinstance(val, bool):
        return [_check_positive_id(val, "id")]
    if isinstance(val, list):
        return [_check_positive_id(x, "id item") for x in val]
    message = (
        "Invalid --ids JSON: expected a positive integer or list of positive integers."
    )
    raise TypeError(message)


def _parse_batch_file(path_or_stdin: str) -> dict[int, JsonObject]:
    """Parse write-batch JSON mapping id -> values from file or stdin."""
    if path_or_stdin == "-":
        content = sys.stdin.read()
    else:
        path = Path(path_or_stdin).expanduser()
        if not path.is_file():
            message = f"Batch file not found: {path}"
            raise FileNotFoundError(message)
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            message = f"Cannot read batch file {path}: {exc}"
            raise OSError(message) from exc

    try:
        data = cast("object", json.loads(content))
    except json.JSONDecodeError as exc:
        message = f"Invalid write-batch JSON: {exc}."
        raise ValueError(message) from exc

    if not isinstance(data, dict) or not data:
        message = "Invalid write-batch JSON: expected a non-empty object mapping id -> values."
        raise TypeError(message)

    result: dict[int, JsonObject] = {}
    for key, val in data.items():
        try:
            raw_id = int(key)
        except (ValueError, TypeError) as exc:
            message = f"Invalid write-batch key: {key!r} must be an integer ID."
            raise ValueError(message) from exc
        valid_id = _check_positive_id(raw_id, "batch ID")
        if not isinstance(val, dict) or not val:
            message = f"Invalid write-batch values for ID {valid_id}: must be a non-empty object."
            raise TypeError(message)
        if not all(isinstance(k, str) for k in val):
            message = f"Invalid write-batch values for ID {valid_id}: field names must be strings."
            raise TypeError(message)
        result[valid_id] = cast("JsonObject", val)
    return result


def _optional_str(args: argparse.Namespace, field: str) -> str | None:
    """Narrow an optional string flag to a typed value."""
    value = cast("object", getattr(args, field, None))
    return value if isinstance(value, str) else None


def _optional_str_list(args: argparse.Namespace, field: str) -> list[str] | None:
    """Narrow an optional string-list flag to a typed value."""
    value = cast("object", getattr(args, field, None))
    if value is None:
        return None
    items = cast("list[object]", value)
    return [item for item in items if isinstance(item, str)]


def _required_str_list(args: argparse.Namespace, field: str) -> list[str]:
    """Narrow a required string-list argument to a typed value."""
    value = cast("object", getattr(args, field, None))
    if not isinstance(value, list):
        message = f"Missing required argument: {field}."
        raise TypeError(message)
    items = cast("list[object]", value)
    return [item for item in items if isinstance(item, str)]


def _optional_int(args: argparse.Namespace, field: str, default: int) -> int:
    """Narrow an optional integer flag to a typed value."""
    value = cast("object", getattr(args, field, None))
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _optional_int_or_none(args: argparse.Namespace, field: str) -> int | None:
    """Narrow an optional integer-or-null flag to a typed value."""
    value = cast("object", getattr(args, field, None))
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _optional_flag(args: argparse.Namespace, field: str) -> bool:
    """Narrow an optional boolean flag to a typed value."""
    value = cast("object", getattr(args, field, None))
    return value is True


def _required_str(args: argparse.Namespace, field: str) -> str:
    """Narrow a required string argument to a typed value."""
    value = cast("object", getattr(args, field, None))
    if not isinstance(value, str):
        message = f"Missing required argument: {field}."
        raise TypeError(message)
    return value


def _required_int(args: argparse.Namespace, field: str) -> int:
    """Narrow a required integer argument to a typed value."""
    value = cast("object", getattr(args, field, None))
    if not isinstance(value, int) or isinstance(value, bool):
        message = f"Invalid integer argument: {field}."
        raise TypeError(message)
    return value


def _emit(payload: object) -> None:
    """Print a JSON payload with the command's documented shape."""
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def _emit_compact(payload: object) -> None:
    """Print a single-line JSON payload."""
    print(json.dumps(payload))


def get_state_dir() -> Path:
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


def _append_writes_log(entry: Mapping[str, object]) -> None:
    """Append a step entry to writes.log in JSONL format."""
    state_dir = get_state_dir()
    _ensure_dir_0700(state_dir)
    log_file = state_dir / "writes.log"
    line = json.dumps(entry, sort_keys=True, ensure_ascii=False) + "\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    fd = os.open(log_file, flags, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as f:
        _ = f.write(line)
    with contextlib.suppress(OSError):
        log_file.chmod(0o600)


def check_production_denylist(
    config: OdooRpcConfig,
    command: str,
    model: str,
    *,
    method: str | None = None,
    values: JsonObject | list[JsonRecord] | None = None,
    values_by_id: dict[int, JsonObject] | None = None,
) -> None:
    """Check production deny-list invariants for non-loopback endpoints."""
    if is_loopback(config):
        return

    # 1. Method patterns
    check_method: str | None = None
    if command in ("unlink", "delete"):
        check_method = "unlink"
    elif command == "call" and method:
        check_method = method

    if check_method:
        for pattern, pattern_str, reason in _COMPILED_DENIED_METHODS:
            if pattern.search(check_method):
                message = f"{reason} (pattern '{pattern_str}')"
                raise ProductionDeniedError(message)

    # 2. Models (archive/unarchive remain allowed)
    if (
        command in ("create", "write", "update", "write-batch", "copy", "call")
        and model in PROD_DENIED_MODELS
    ):
        message = f"mutations on model '{model}' are forbidden"
        raise ProductionDeniedError(message)

    # 3. Value keys
    if command in ("create", "write", "update", "write-batch"):
        dicts_to_check: list[JsonObject] = []
        if isinstance(values, dict):
            dicts_to_check.append(values)
        elif isinstance(values, list):
            dicts_to_check.extend(d for d in values if isinstance(d, dict))
        if values_by_id:
            dicts_to_check.extend(values_by_id.values())

        for d in dicts_to_check:
            for k in d:
                if k in PROD_DENIED_VALUE_KEYS:
                    message = f"modifying field '{k}' is forbidden"
                    raise ProductionDeniedError(message)


def _generate_plan_id(canonical_payload: JsonObject) -> str:
    """Generate 10-hex plan ID from canonical payload + timestamp."""
    raw = json.dumps(canonical_payload, sort_keys=True) + str(time.time())
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:_PLAN_ID_HEX_LEN]


def _print_plan_diff(plan: JsonObject) -> None:
    """Print per-record diff of old -> new values."""
    model = cast("str", plan.get("model", ""))
    command = cast("str", plan.get("command", ""))
    preimage = cast("list[JsonRecord]", plan.get("preimage", []))
    pre_by_id: dict[int, JsonRecord] = {
        int(r["id"]): r
        for r in preimage
        if "id" in r and isinstance(r["id"], int) and not isinstance(r["id"], bool)
    }

    if command in ("write", "update"):
        vals = cast("JsonObject", plan.get("values", {}))
        ids = cast("list[int]", plan.get("ids", []))
        for rid in ids:
            rec = pre_by_id.get(rid, {})
            dname = rec.get("display_name", f"id={rid}")
            print(f"# {model} id={rid} ({dname}):")
            for field, new_val in vals.items():
                old_val = rec.get(field)
                print(f"  {field}: {old_val} -> {new_val}")
    elif command == "write-batch":
        v_by_id = cast("dict[str, JsonObject]", plan.get("values_by_id", {}))
        for id_str, vals in v_by_id.items():
            rid = int(id_str)
            rec = pre_by_id.get(rid, {})
            dname = rec.get("display_name", f"id={rid}")
            print(f"# {model} id={rid} ({dname}):")
            for field, new_val in vals.items():
                old_val = rec.get(field)
                print(f"  {field}: {old_val} -> {new_val}")
    elif command == "archive":
        ids = cast("list[int]", plan.get("ids", []))
        for rid in ids:
            rec = pre_by_id.get(rid, {})
            dname = rec.get("display_name", f"id={rid}")
            print(f"# {model} id={rid} ({dname}):")
            print("  active: True -> False")
    elif command == "unarchive":
        ids = cast("list[int]", plan.get("ids", []))
        for rid in ids:
            rec = pre_by_id.get(rid, {})
            dname = rec.get("display_name", f"id={rid}")
            print(f"# {model} id={rid} ({dname}):")
            print("  active: False -> True")
    elif command == "create":
        vals = plan.get("values")
        records = (
            [vals]
            if isinstance(vals, dict)
            else (vals if isinstance(vals, list) else [])
        )
        for idx, rec_vals in enumerate(records):
            if isinstance(rec_vals, dict):
                print(f"# {model} create record #{idx + 1}:")
                for field, val in rec_vals.items():
                    print(f"  {field}: None -> {val}")
    elif command == "copy":
        ids = cast("list[int]", plan.get("ids", []))
        rid = ids[0] if ids else 0
        rec = pre_by_id.get(rid, {})
        dname = rec.get("display_name", f"id={rid}")
        print(f"# {model} copy id={rid} ({dname}):")
        defaults = cast("JsonObject", plan.get("default", {})) or {}
        for field, val in defaults.items():
            print(f"  override {field} -> {val}")
    elif command in ("unlink", "delete"):
        ids = cast("list[int]", plan.get("ids", []))
        for rid in ids:
            rec = pre_by_id.get(rid, {})
            dname = rec.get("display_name", f"id={rid}")
            print(f"# {model} unlink id={rid} ({dname})")
    elif command == "call":
        method = plan.get("method")
        ids = plan.get("ids")
        args_val = plan.get("args")
        kwargs_val = plan.get("kwargs")
        print(
            f"# {model} call method={method!r} ids={ids} args={args_val} kwargs={kwargs_val}"
        )


def _create_and_save_plan(
    client: OdooRpcClient,
    command: str,
    model: str,
    ids: list[int] | None,
    preimage: list[JsonRecord],
    *,
    values: JsonObject | list[JsonRecord] | None = None,
    values_by_id: dict[int, JsonObject] | None = None,
    default_vals: JsonObject | None = None,
    method: str | None = None,
    call_args: list[JsonValue] | None = None,
    call_kwargs: JsonObject | None = None,
    as_json: bool = False,
) -> int:
    """Create, persist, and display an execution plan."""
    canonical: JsonObject = {
        "command": command,
        "model": model,
        "url": client.config.url,
        "db": client.config.database,
    }
    if ids is not None:
        canonical["ids"] = cast("JsonValue", ids)
    plan_id = _generate_plan_id(canonical)

    plan: JsonObject = {
        "id": plan_id,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "url": client.config.url,
        "db": client.config.database,
        "user": client.config.user,
        "command": command,
        "model": model,
        "ids": cast("JsonValue", ids),
        "preimage": cast("JsonValue", preimage),
    }
    if values is not None:
        plan["values"] = cast("JsonValue", values)
    if values_by_id is not None:
        plan["values_by_id"] = cast(
            "JsonValue", {str(k): v for k, v in values_by_id.items()}
        )
    if default_vals is not None:
        plan["default"] = cast("JsonValue", default_vals)
    if method is not None:
        plan["method"] = method
        plan["args"] = cast("JsonValue", call_args or [])
        plan["kwargs"] = cast("JsonValue", call_kwargs or {})

    plan_path = get_state_dir() / "plans" / f"{plan_id}.json"
    _write_file_0600(
        plan_path, json.dumps(plan, indent=2, sort_keys=True, ensure_ascii=False)
    )

    if as_json:
        plan_out = dict(plan)
        plan_out["message"] = (
            f"plan {plan_id} saved. After user approval run: cli.py rpc --allow-rpc --write apply {plan_id}"
        )
        _emit(plan_out)
    else:
        _print_plan_diff(plan)
        print(
            f"plan {plan_id} saved. After user approval run: cli.py rpc --allow-rpc --write apply {plan_id}"
        )
    return 0


def _run_read_commands(
    client: OdooRpcClient, args: argparse.Namespace, command: str
) -> None:
    """Run search/count/read/read_group subcommands."""
    model = _required_str(args, "model")
    if command == "search_read":
        domain_val = _json_domain(_required_str(args, "domain"))
        fields_val = normalize_fields(_optional_str_list(args, "fields"))
        limit_val = _optional_int(args, "limit", 10)
        offset_val = _optional_int(args, "offset", 0)
        order_val = _optional_str(args, "order")
        res = client.search_read(
            model,
            domain=domain_val,
            fields=fields_val,
            limit=limit_val,
            offset=offset_val,
            order=order_val,
        )
        if limit_val is not None and len(res) == limit_val:
            total = client.search_count(model, domain=domain_val)
            if total > limit_val:
                _ = sys.stderr.write(
                    f"warning: truncated: showing {limit_val} of {total} records (use --limit/--offset)\n"
                )
        _emit(res)
    elif command == "count":
        res = client.search_count(
            model, domain=_json_domain(_required_str(args, "domain"))
        )
        _emit_compact({"count": res})
    elif command == "read":
        res = client.read(
            model,
            ids=_id_list(_required_str(args, "ids"), "ids"),
            fields=normalize_fields(_optional_str_list(args, "fields")),
        )
        _emit(res)
    elif command == "read_group":
        domain_val = _json_domain(_required_str(args, "domain"))
        groupby_val = _required_str_list(args, "groupby")
        norm_groupby: list[str] = []
        for g in groupby_val:
            for part in g.replace(",", " ").split():
                if part:
                    norm_groupby.append(part)
        fields_val = normalize_fields(_optional_str_list(args, "fields"))
        orderby_val = _optional_str(args, "orderby")
        lazy_val = _optional_flag(args, "lazy")
        res = client.read_group(
            model,
            groupby=norm_groupby,
            domain=domain_val,
            fields=fields_val,
            orderby=orderby_val,
            lazy=lazy_val,
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
        _emit(
            client.fields_get(
                model,
                allfields=normalize_fields(_optional_str_list(args, "fields")),
            )
        )
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
    client: OdooRpcClient,
    args: argparse.Namespace,
    command: str,
    *,
    allow_write: bool,
    as_json: bool,
) -> int:
    """Handle state-mutation subcommands via direct execution or plans."""
    model = _required_str(args, "model")

    method: str | None = None
    call_args: list[JsonValue] | None = None
    call_kwargs: JsonObject | None = None
    vals: JsonObject | list[JsonRecord] | None = None
    values_by_id: dict[int, JsonObject] | None = None
    default_vals: JsonObject | None = None
    ids: list[int] | None = None

    if command == "call":
        method = _required_str(args, "method")
        if method.startswith("_"):
            message = f"Private methods starting with '_' are forbidden: {method}"
            raise ValueError(message)
        call_ids = _parse_call_ids(_optional_str(args, "ids"))
        call_args = (
            _json_list(_required_str(args, "args"), "args")
            if _optional_str(args, "args")
            else []
        )
        call_kwargs = (
            _json_object_arg(_required_str(args, "kwargs"), "kwargs")
            if _optional_str(args, "kwargs")
            else {}
        )
        if method in READONLY_ALLOWLIST:
            full_args = (
                [cast("JsonValue", call_ids), *call_args] if call_ids else call_args
            )
            res = client.execute(model, method, full_args, call_kwargs)
            _emit(res)
            return 0
        ids = call_ids
    elif command == "create":
        vals = _json_vals(_required_str(args, "values"), "values")
    elif command in ("write", "update"):
        ids = _id_list(_required_str(args, "ids"), "ids")
        vals = _json_object_arg(_required_str(args, "values"), "values")
    elif command == "write-batch":
        values_by_id = _parse_batch_file(_required_str(args, "file"))
        ids = sorted(values_by_id.keys())
    elif command in ("unlink", "delete"):
        ids = _id_list(_required_str(args, "ids"), "ids")
    elif command == "copy":
        rec_id = _required_int(args, "id")
        ids = [rec_id]
        default_text = _optional_str(args, "default")
        default_vals = (
            _json_object_arg(default_text, "default") if default_text else None
        )
    elif command in ("archive", "unarchive"):
        ids = _id_list(_required_str(args, "ids"), "ids")
    else:
        message = f"Unknown mutation command: {command}."
        raise ValueError(message)

    # Check production deny-list
    check_production_denylist(
        client.config,
        command,
        model,
        method=method,
        values=vals,
        values_by_id=values_by_id,
    )

    is_target_loopback = is_loopback(client.config)

    # Production with --write is blocked on direct mutations
    if not is_target_loopback and allow_write:
        _ = sys.stderr.write(
            "MUTATION BLOCKED: production writes must go through a plan. "
            + "Run the same command without --write, show the plan to the user, "
            + "then 'apply <id>' after approval.\n"
        )
        return 2

    # Loopback with --write executes directly
    if is_target_loopback and allow_write:
        if command == "create":
            created = client.create(
                model, vals=cast("JsonObject | list[JsonRecord]", vals)
            )
            _emit_compact({"created_id": created})
        elif command in ("write", "update"):
            updated = client.write(
                model,
                ids=cast("list[int]", ids),
                vals=cast("JsonObject", vals),
            )
            _emit_compact({"updated": updated})
        elif command == "write-batch":
            grouped: dict[str, tuple[list[int], JsonObject]] = {}
            if values_by_id:
                for rid, rvals in values_by_id.items():
                    key = json.dumps(rvals, sort_keys=True)
                    if key not in grouped:
                        grouped[key] = ([], rvals)
                    grouped[key][0].append(rid)
            for grp_ids, grp_vals in grouped.values():
                _ = client.write(model, ids=grp_ids, vals=grp_vals)
            _emit_compact({"updated": True})
        elif command in ("unlink", "delete"):
            deleted = client.unlink(model, ids=cast("list[int]", ids))
            _emit_compact({"deleted": deleted})
        elif command == "copy":
            copied = client.copy(
                model,
                record_id=cast("list[int]", ids)[0],
                default=default_vals,
            )
            _emit_compact({"copied_id": copied})
        elif command == "archive":
            archived = client.action_archive(model, ids=cast("list[int]", ids))
            _emit_compact({"archived": archived})
        elif command == "unarchive":
            unarchived = client.action_unarchive(model, ids=cast("list[int]", ids))
            _emit_compact({"unarchived": unarchived})
        elif command == "call":
            call_m = cast("str", method)
            c_args = call_args or []
            c_kwargs = call_kwargs or {}
            full_c_args = [cast("JsonValue", ids), *c_args] if ids else c_args
            result = client.call(model, call_m, full_c_args, c_kwargs)
            _emit(result)
        return 0

    # Without --write: create and save plan
    preimage: list[JsonRecord] = []
    if command in ("write", "update"):
        target_ids = cast("list[int]", ids)
        write_vals = cast("JsonObject", vals)
        fetch_fields = sorted({*write_vals.keys(), "write_date", "display_name"})
        preimage = client.read(model, target_ids, fields=fetch_fields)
    elif command == "write-batch":
        target_ids = cast("list[int]", ids)
        batch_vals = cast("dict[int, JsonObject]", values_by_id)
        fetch_fields = sorted(
            {
                *(f for d in batch_vals.values() for f in d),
                "write_date",
                "display_name",
            }
        )
        preimage = client.read(model, target_ids, fields=fetch_fields)
    elif command in ("archive", "unarchive"):
        target_ids = cast("list[int]", ids)
        preimage = client.read(
            model, target_ids, fields=["active", "write_date", "display_name"]
        )
    elif command == "copy":
        target_ids = cast("list[int]", ids)
        preimage = client.read(model, target_ids, fields=["display_name", "write_date"])
    elif command == "call":
        if ids:
            preimage = client.read(model, ids, fields=["display_name", "write_date"])
    elif command in ("unlink", "delete"):
        target_ids = cast("list[int]", ids)
        preimage = client.read(model, target_ids, fields=["display_name", "write_date"])
    elif command == "create":
        preimage = []

    return _create_and_save_plan(
        client,
        command,
        model,
        ids,
        preimage,
        values=vals,
        values_by_id=values_by_id,
        default_vals=default_vals,
        method=method,
        call_args=call_args,
        call_kwargs=call_kwargs,
        as_json=as_json,
    )


def _run_apply(
    client: OdooRpcClient,
    plan_id: str,
    *,
    allow_write: bool,
) -> int:
    """Apply a saved plan after verifying configuration and write_date drift."""
    if not allow_write:
        _ = sys.stderr.write(
            "MUTATION BLOCKED: 'apply' modifies data but --write was not specified. "
            + "Pass --write to authorize state mutations.\n"
        )
        return 1

    plan_path = get_state_dir() / "plans" / f"{plan_id}.json"
    if not plan_path.is_file():
        _ = sys.stderr.write(f"Error: Plan not found: {plan_id}\n")
        return 1

    try:
        plan_raw = json.loads(plan_path.read_text(encoding="utf-8"))
        if not isinstance(plan_raw, dict):
            _ = sys.stderr.write(f"Error: Plan file {plan_id} is corrupt.\n")
            return 1
        plan = cast("JsonObject", plan_raw)
    except (OSError, json.JSONDecodeError) as exc:
        _ = sys.stderr.write(f"Error: Cannot read plan {plan_id}: {exc}\n")
        return 1

    if plan.get("applied_at"):
        _ = sys.stderr.write(
            f"Error: Plan {plan_id} has already been applied at {plan['applied_at']}.\n"
        )
        return 1

    plan_url = plan.get("url")
    plan_db = plan.get("db")
    if plan_url != client.config.url or plan_db != client.config.database:
        _ = sys.stderr.write(
            f"Error: Plan target ({plan_url}, {plan_db}) does not match current config "
            + f"({client.config.url}, {client.config.database}).\n"
        )
        return 1

    command = cast("str", plan["command"])
    model = cast("str", plan["model"])
    method = cast("str | None", plan.get("method"))
    values_obj = cast("JsonObject | list[JsonRecord] | None", plan.get("values"))
    raw_v_by_id = plan.get("values_by_id")
    v_by_id: dict[int, JsonObject] | None = None
    if isinstance(raw_v_by_id, dict):
        v_by_id = {int(k): cast("JsonObject", v) for k, v in raw_v_by_id.items()}

    # Re-check production deny-list
    check_production_denylist(
        client.config,
        command,
        model,
        method=method,
        values=values_obj,
        values_by_id=v_by_id,
    )

    planned_ids_raw = plan.get("ids")
    planned_ids: list[int] = (
        [x for x in planned_ids_raw if isinstance(x, int) and not isinstance(x, bool)]
        if isinstance(planned_ids_raw, list)
        else []
    )

    # Drift check on write_date
    if planned_ids:
        current_records = client.read(model, planned_ids, fields=["write_date"])
        current_by_id = {
            int(r["id"]): r
            for r in current_records
            if "id" in r and isinstance(r["id"], int) and not isinstance(r["id"], bool)
        }
        preimage = cast("list[JsonRecord]", plan.get("preimage", []))
        pre_by_id = {
            int(r["id"]): r
            for r in preimage
            if "id" in r and isinstance(r["id"], int) and not isinstance(r["id"], bool)
        }

        drifted_ids: list[int] = []
        for pid in planned_ids:
            if pid not in current_by_id:
                drifted_ids.append(pid)
                continue
            curr_date = current_by_id[pid].get("write_date")
            pre_date = pre_by_id.get(pid, {}).get("write_date")
            if curr_date != pre_date:
                drifted_ids.append(pid)

        if drifted_ids:
            drifted_sorted = sorted(set(drifted_ids))
            _ = sys.stderr.write(f"drift detected on {model} ids {drifted_sorted}\n")
            return 1

    # Write backup BEFORE mutating
    backup_path = get_state_dir() / "backups" / f"{plan_id}.json"
    backup: JsonObject = {
        "plan_id": plan_id,
        "created_at": plan.get("created_at"),
        "applied_at": None,
        "command": command,
        "model": model,
        "ids": cast("JsonValue", planned_ids),
        "preimage": plan.get("preimage", []),
        "created_ids": [],
        "steps_completed": [],
    }
    _write_file_0600(
        backup_path, json.dumps(backup, indent=2, sort_keys=True, ensure_ascii=False)
    )

    done_ids: list[int] = []
    remaining_ids: list[int] = list(planned_ids)
    try:
        if command in ("write", "update"):
            vals = cast("JsonObject", plan["values"])
            _ = client.write(model, planned_ids, vals)
            done_ids.extend(planned_ids)
            remaining_ids.clear()
            _append_writes_log(
                {
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "plan_id": plan_id,
                    "command": "write",
                    "model": model,
                    "ids": planned_ids,
                    "values": vals,
                }
            )
        elif command == "write-batch":
            grouped: dict[str, tuple[list[int], JsonObject]] = {}
            if v_by_id:
                for rid, vals in v_by_id.items():
                    key = json.dumps(vals, sort_keys=True)
                    if key not in grouped:
                        grouped[key] = ([], vals)
                    grouped[key][0].append(rid)

            for group_ids, group_vals in grouped.values():
                _ = client.write(model, group_ids, group_vals)
                done_ids.extend(group_ids)
                remaining_ids = [i for i in remaining_ids if i not in done_ids]
                _append_writes_log(
                    {
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "plan_id": plan_id,
                        "command": "write-batch",
                        "model": model,
                        "ids": group_ids,
                        "values": group_vals,
                    }
                )
        elif command == "create":
            create_vals = cast("JsonObject | list[JsonRecord]", plan["values"])
            created = client.create(model, create_vals)
            created_ids = (
                [created]
                if isinstance(created, int) and not isinstance(created, bool)
                else (cast("list[int]", created) if isinstance(created, list) else [])
            )
            backup["created_ids"] = cast("JsonValue", created_ids)
            _write_file_0600(
                backup_path,
                json.dumps(backup, indent=2, sort_keys=True, ensure_ascii=False),
            )
            _append_writes_log(
                {
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "plan_id": plan_id,
                    "command": "create",
                    "model": model,
                    "created_ids": created_ids,
                }
            )
        elif command == "copy":
            rec_id = planned_ids[0]
            default_override = cast("JsonObject | None", plan.get("default"))
            copied_id = client.copy(model, rec_id, default=default_override)
            backup["created_ids"] = [copied_id]
            _write_file_0600(
                backup_path,
                json.dumps(backup, indent=2, sort_keys=True, ensure_ascii=False),
            )
            _append_writes_log(
                {
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "plan_id": plan_id,
                    "command": "copy",
                    "model": model,
                    "copied_id": copied_id,
                }
            )
        elif command == "archive":
            _ = client.action_archive(model, planned_ids)
            done_ids.extend(planned_ids)
            remaining_ids.clear()
            _append_writes_log(
                {
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "plan_id": plan_id,
                    "command": "archive",
                    "model": model,
                    "ids": planned_ids,
                }
            )
        elif command == "unarchive":
            _ = client.action_unarchive(model, planned_ids)
            done_ids.extend(planned_ids)
            remaining_ids.clear()
            _append_writes_log(
                {
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "plan_id": plan_id,
                    "command": "unarchive",
                    "model": model,
                    "ids": planned_ids,
                }
            )
        elif command in ("unlink", "delete"):
            _ = client.unlink(model, planned_ids)
            done_ids.extend(planned_ids)
            remaining_ids.clear()
            _append_writes_log(
                {
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "plan_id": plan_id,
                    "command": "unlink",
                    "model": model,
                    "ids": planned_ids,
                }
            )
        elif command == "call":
            call_method = cast("str", plan["method"])
            call_args = cast("list[JsonValue]", plan.get("args", []))
            call_kwargs = cast("JsonObject", plan.get("kwargs", {}))
            full_args = (
                [cast("JsonValue", planned_ids), *call_args]
                if planned_ids
                else call_args
            )
            _ = client.call(model, call_method, full_args, call_kwargs)
            done_ids.extend(planned_ids)
            remaining_ids.clear()
            _append_writes_log(
                {
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "plan_id": plan_id,
                    "command": "call",
                    "model": model,
                    "method": call_method,
                    "ids": planned_ids,
                }
            )
    except Exception as exc:
        _ = sys.stderr.write(
            f"Error during apply: {exc}. Done IDs: {done_ids}, remaining IDs: {remaining_ids}\n"
        )
        return 1

    applied_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    plan["applied_at"] = applied_time
    _write_file_0600(
        plan_path, json.dumps(plan, indent=2, sort_keys=True, ensure_ascii=False)
    )
    backup["applied_at"] = applied_time
    _write_file_0600(
        backup_path, json.dumps(backup, indent=2, sort_keys=True, ensure_ascii=False)
    )

    print(
        f"applied plan {plan_id}; revert with: cli.py rpc --allow-rpc revert {plan_id}"
    )
    return 0


def _run_revert(
    client: OdooRpcClient,
    plan_id: str,
    *,
    as_json: bool,
) -> int:
    """Generate a compensating plan from an applied plan's backup."""
    backup_path = get_state_dir() / "backups" / f"{plan_id}.json"
    if not backup_path.is_file():
        _ = sys.stderr.write(f"Error: Backup not found for plan {plan_id}.\n")
        return 1

    try:
        backup_raw = json.loads(backup_path.read_text(encoding="utf-8"))
        if not isinstance(backup_raw, dict):
            _ = sys.stderr.write(f"Error: Backup file {plan_id} is corrupt.\n")
            return 1
        backup = cast("JsonObject", backup_raw)
    except (OSError, json.JSONDecodeError) as exc:
        _ = sys.stderr.write(f"Error: Cannot read backup {plan_id}: {exc}\n")
        return 1

    command = cast("str", backup.get("command", ""))
    model = cast("str", backup.get("model", ""))
    preimage = cast("list[JsonRecord]", backup.get("preimage", []))

    if command == "call":
        _ = sys.stderr.write(
            f"no automatic revert for method calls; pre-image saved in {backup_path}\n"
        )
        return 1

    if command in ("write", "update", "write-batch"):
        values_by_id: dict[int, JsonObject] = {}
        for rec in preimage:
            if (
                "id" not in rec
                or not isinstance(rec["id"], int)
                or isinstance(rec["id"], bool)
            ):
                continue
            rid = rec["id"]
            restore_vals = {
                k: v
                for k, v in rec.items()
                if k not in ("id", "write_date", "display_name")
            }
            if restore_vals:
                values_by_id[rid] = restore_vals

        if not values_by_id:
            _ = sys.stderr.write(
                f"Error: No pre-image values found to revert in plan {plan_id}.\n"
            )
            return 1

        target_ids = sorted(values_by_id.keys())
        all_fields = sorted(
            {
                *(f for d in values_by_id.values() for f in d),
                "write_date",
                "display_name",
            }
        )
        new_preimage = client.read(model, target_ids, fields=all_fields)
        return _create_and_save_plan(
            client,
            "write-batch",
            model,
            target_ids,
            new_preimage,
            values_by_id=values_by_id,
            as_json=as_json,
        )

    if command == "archive":
        ids_raw = backup.get("ids", [])
        target_ids = (
            [x for x in ids_raw if isinstance(x, int) and not isinstance(x, bool)]
            if isinstance(ids_raw, list)
            else []
        )
        new_preimage = client.read(
            model, target_ids, fields=["active", "write_date", "display_name"]
        )
        return _create_and_save_plan(
            client,
            "unarchive",
            model,
            target_ids,
            new_preimage,
            as_json=as_json,
        )

    if command == "unarchive":
        ids_raw = backup.get("ids", [])
        target_ids = (
            [x for x in ids_raw if isinstance(x, int) and not isinstance(x, bool)]
            if isinstance(ids_raw, list)
            else []
        )
        new_preimage = client.read(
            model, target_ids, fields=["active", "write_date", "display_name"]
        )
        return _create_and_save_plan(
            client,
            "archive",
            model,
            target_ids,
            new_preimage,
            as_json=as_json,
        )

    if command in ("create", "copy"):
        created_ids_raw = backup.get("created_ids", [])
        created_ids = (
            [
                x
                for x in created_ids_raw
                if isinstance(x, int) and not isinstance(x, bool)
            ]
            if isinstance(created_ids_raw, list)
            else []
        )
        if not created_ids:
            _ = sys.stderr.write(
                f"Error: No created IDs recorded in backup for plan {plan_id}.\n"
            )
            return 1
        new_preimage = client.read(
            model, created_ids, fields=["active", "write_date", "display_name"]
        )
        return _create_and_save_plan(
            client,
            "archive",
            model,
            created_ids,
            new_preimage,
            as_json=as_json,
        )

    _ = sys.stderr.write(f"Error: Unsupported command for revert: {command}\n")
    return 1


_READ_COMMANDS = frozenset({"search_read", "count", "read", "read_group"})
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
        "write-batch",
        "unlink",
        "delete",
        "copy",
        "archive",
        "unarchive",
        "call",
    }
)
_PLAN_COMMANDS = frozenset({"apply", "revert"})
_ALL_COMMANDS = (
    _READ_COMMANDS | _INSPECTION_COMMANDS | _MUTATION_COMMANDS | _PLAN_COMMANDS
)


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
            return 0
        if command in _INSPECTION_COMMANDS:
            _run_inspection_commands(client, args, command)
            return 0
        if command == "apply":
            return _run_apply(
                client,
                _required_str(args, "plan_id"),
                allow_write=_optional_flag(args, "write"),
            )
        if command == "revert":
            return _run_revert(
                client,
                _required_str(args, "plan_id"),
                as_json=_optional_flag(args, "json"),
            )
        return _run_mutation_commands(
            client,
            args,
            command,
            allow_write=_optional_flag(args, "write"),
            as_json=_optional_flag(args, "json"),
        )
    except ProductionDeniedError as exc:
        _ = sys.stderr.write(f"DENIED on production: {exc}. Do it in the Odoo UI.\n")
        return 2
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


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
