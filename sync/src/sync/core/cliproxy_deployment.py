# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""CLIProxyAPI deployment schema, validation, template preservation, and publication."""

from __future__ import annotations

import contextlib
import ipaddress
import json
import re
import shutil
import socket
import stat
import urllib.parse
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Final, Literal, TypeGuard

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from sync.runtime.errors import is_errno, panic_message
from sync.runtime.fs import sync_text_file
from sync.runtime.jsonc import strip_jsonc

INVALID_LISTEN_HOST_PATTERN: Final[re.Pattern[str]] = re.compile(r"[\s/?#@]")
INVALID_SERVER_HOSTNAME_PATTERN: Final[re.Pattern[str]] = re.compile(r"[\s/?#@:]")
INVALID_CLIENT_URL_DELIMITER_PATTERN: Final[re.Pattern[str]] = re.compile(r"[?#]")
IPV4_ZERO_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^(?:0+(?:\.0+){0,3}|0x0+)$",
    re.IGNORECASE,
)
IPV4_PART_PATTERN: Final[re.Pattern[str]] = re.compile(r"^\d{1,3}$")
ZERO_IPV6_GROUP_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^0{1,4}$",
    re.IGNORECASE,
)
TRAILING_SLASH_PATTERN: Final[re.Pattern[str]] = re.compile(r"/+$")
CLIENT_BASE_URL_PLACEHOLDER_NAME: Final[str] = "CLIPROXY_CLIENT_BASE_URL"
CLI_PROXY_SOURCE_DIR: Final[str] = "tools/cliproxyapi"
CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER: Final[str] = (
    f"${{{CLIENT_BASE_URL_PLACEHOLDER_NAME}}}"
)

ENDPOINT_READY_TIMEOUT_MS: Final[int] = 500
MIN_PORT: Final[int] = 1
MAX_PORT: Final[int] = 65535
DEFAULT_FILE_MODE: Final[int] = 0o644
IPV6_GROUPS_COUNT: Final[int] = 8
IPV4_PARTS_COUNT: Final[int] = 4
MAX_IPV4_OCTET: Final[int] = 255
BARE_KEY_DELIMITERS: Final[frozenset[str]] = frozenset(
    (".", "]", "[", " ", "\t", "#", "\r", "\n", "=")
)


def is_unspecified_ipv4(host: str) -> bool:
    """Check if host matches unspecified IPv4 zero patterns."""
    return bool(IPV4_ZERO_PATTERN.match(host))


def _is_zero_ipv6_group(group: str) -> bool:
    return bool(ZERO_IPV6_GROUP_PATTERN.match(group))


def _ipv4_tail_groups(address: str) -> list[str] | None:
    separator = address.rfind(":")
    if separator < 0:
        return None
    ipv4_str = address[separator + 1 :]
    parts = ipv4_str.split(".")
    if len(parts) != IPV4_PARTS_COUNT or any(
        not IPV4_PART_PATTERN.match(part) for part in parts
    ):
        return None
    try:
        bytes_val = [int(p) for p in parts]
    except ValueError:
        return None
    if any(b > MAX_IPV4_OCTET for b in bytes_val):
        return None
    first, second, third, fourth = bytes_val
    tail1 = f"{(first << 8) | second:x}"
    tail2 = f"{(third << 8) | fourth:x}"
    head = address[:separator].split(":")
    return [*head, tail1, tail2]


def is_unspecified_ipv6(host: str) -> bool:
    """Check if host represents an unspecified IPv6 address (:: or all zero groups)."""
    address = host.split("%", maxsplit=1)[0]
    try:
        ip = ipaddress.IPv6Address(address)
    except ValueError:
        return False

    if ip.is_unspecified:
        return True

    groups = _ipv4_tail_groups(address) if "." in address else address.split(":")
    if groups is None:
        return False
    compression = address.find("::")
    if compression >= 0:
        if address.find("::", compression + 2) >= 0:
            return False
        explicit = [g for g in groups if g]
        return (
            all(_is_zero_ipv6_group(g) for g in explicit)
            and len(explicit) < IPV6_GROUPS_COUNT
        )
    return len(groups) == IPV6_GROUPS_COUNT and all(
        _is_zero_ipv6_group(g) for g in groups
    )


class ServerConfig(BaseModel):
    """Server hostname configuration."""

    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid", frozen=True, strict=True
    )
    hostname: str

    @field_validator("hostname")
    @classmethod
    def _validate_hostname(cls, h: str) -> str:
        if not h or h != h.strip() or INVALID_SERVER_HOSTNAME_PATTERN.search(h):
            msg = "expected a local OS hostname"
            raise ValueError(msg)
        return h


class ListenConfig(BaseModel):
    """Network listen address and port configuration."""

    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid", frozen=True, strict=True
    )
    host: str
    port: int = Field(ge=MIN_PORT, le=MAX_PORT)

    @field_validator("host")
    @classmethod
    def _validate_host(cls, host: str) -> str:
        if (
            not host
            or host != host.strip()
            or INVALID_LISTEN_HOST_PATTERN.search(host)
            or "://" in host
            or "[" in host
            or "]" in host
            or is_unspecified_ipv4(host)
            or is_unspecified_ipv6(host)
        ):
            msg = "expected a specific host or interface address"
            raise ValueError(msg)
        return host


class ClientConfig(BaseModel):
    """Client endpoint base URL configuration."""

    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        populate_by_name=True,
    )
    base_url: str = Field(alias="baseUrl")

    @field_validator("base_url")
    @classmethod
    def _validate_base_url(cls, raw: str) -> str:
        if (
            not raw
            or raw != raw.strip()
            or INVALID_CLIENT_URL_DELIMITER_PATTERN.search(raw)
        ):
            msg = (
                "expected an HTTP(S) /v1 endpoint without credentials, "
                "query, or fragment"
            )
            raise ValueError(msg)
        try:
            parsed = urllib.parse.urlsplit(raw)
        except ValueError as err:
            msg = "expected URL"
            raise ValueError(msg) from err
        if (
            parsed.scheme not in ("http", "https")
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or not parsed.hostname
            or parsed.path.rstrip("/") != "/v1"
        ):
            msg = (
                "expected an HTTP(S) /v1 endpoint without credentials, "
                "query, or fragment"
            )
            raise ValueError(msg)
        return raw.rstrip("/")


class CliProxyDeployment(BaseModel):
    """Full CLIProxyAPI deployment specification."""

    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        populate_by_name=True,
    )
    server: ServerConfig
    listen: ListenConfig
    client: ClientConfig


def _is_obj_dict(val: object) -> TypeGuard[dict[str, object]]:
    return isinstance(val, dict)


def _is_obj_list(val: object) -> TypeGuard[list[object]]:
    return isinstance(val, list)


def _reject_unknown_fields(
    record: dict[str, object],
    allowed_fields: tuple[str, ...],
    label: str,
) -> None:
    allowed = set(allowed_fields)
    for field in record:
        if field not in allowed:
            msg = f"invalid {label}: unknown field {field}"
            raise ValueError(msg)


def parse_cliproxy_deployment(value: object) -> CliProxyDeployment:
    """Parse and validate CLIProxyAPI deployment dictionary."""
    if not _is_obj_dict(value):
        msg = "invalid CLIProxyAPI deployment: expected object"
        raise TypeError(msg)
    _reject_unknown_fields(
        value,
        ("server", "listen", "client"),
        "CLIProxyAPI deployment",
    )

    server_raw = value.get("server")
    if not _is_obj_dict(server_raw):
        msg = "invalid CLIProxyAPI deployment.server: expected object"
        raise TypeError(msg)
    _reject_unknown_fields(
        server_raw,
        ("hostname",),
        "CLIProxyAPI deployment.server",
    )

    listen_raw = value.get("listen")
    if not _is_obj_dict(listen_raw):
        msg = "invalid CLIProxyAPI deployment.listen: expected object"
        raise TypeError(msg)
    _reject_unknown_fields(
        listen_raw,
        ("host", "port"),
        "CLIProxyAPI deployment.listen",
    )

    client_raw = value.get("client")
    if not _is_obj_dict(client_raw):
        msg = "invalid CLIProxyAPI deployment.client: expected object"
        raise TypeError(msg)
    _reject_unknown_fields(
        client_raw,
        ("baseUrl", "base_url"),
        "CLIProxyAPI deployment.client",
    )

    try:
        return CliProxyDeployment.model_validate(value)
    except ValidationError as error:
        msg = f"invalid CLIProxyAPI deployment ({panic_message(error)})"
        raise ValueError(msg) from error


def read_cliproxy_deployment(path: str | Path) -> CliProxyDeployment:
    """Read and validate CLIProxyAPI deployment from a JSONC file."""
    path_obj = Path(path)
    try:
        text = path_obj.read_text(encoding="utf-8")
    except OSError as error:
        msg = f"read CLIProxyAPI deployment {path_obj} ({panic_message(error)})"
        raise RuntimeError(msg) from error
    try:
        parsed: object = json.loads(strip_jsonc(text))  # pyright: ignore[reportAny]
    except (ValueError, TypeError) as error:
        msg = f"parse CLIProxyAPI deployment {path_obj} ({panic_message(error)})"
        raise RuntimeError(msg) from error
    return parse_cliproxy_deployment(parsed)


def is_cliproxy_gateway_host(
    deployment: CliProxyDeployment,
    hostname: str | None = None,
) -> bool:
    """Return True if hostname matches deployment server hostname."""
    current = socket.gethostname() if hostname is None else hostname
    return current.strip().lower() == deployment.server.hostname.lower()


def cliproxy_models_url(deployment: CliProxyDeployment) -> str:
    """Return the /models endpoint URL for this deployment."""
    base = deployment.client.base_url.rstrip("/")
    return f"{base}/models"


FetchCallable = Callable[..., httpx.Response]


@dataclass(frozen=True)
class CliProxyEndpointSyncOptions:
    """Options for endpoint template synchronization and readiness polling."""

    fetch: FetchCallable | None = None
    timeout_ms: int = ENDPOINT_READY_TIMEOUT_MS
    skip_readiness: bool = False


def is_cliproxy_target_ready(
    deployment: CliProxyDeployment,
    options: CliProxyEndpointSyncOptions | None = None,
) -> bool:
    """Check if CLIProxyAPI /models endpoint is responding with non-empty data array."""
    opts = options or CliProxyEndpointSyncOptions()
    timeout_sec = opts.timeout_ms / 1000.0
    url = cliproxy_models_url(deployment)
    headers = {
        "Accept": "application/json",
        "Cache-Control": "no-cache",
    }
    try:
        if opts.fetch is not None:
            resp = opts.fetch(url, headers=headers, timeout=timeout_sec)
        else:
            resp = httpx.get(url, headers=headers, timeout=timeout_sec)
        if not resp.is_success:
            return False
        payload: object = resp.json()  # pyright: ignore[reportAny]
        if not _is_obj_dict(payload):
            return False
        data = payload.get("data")
        return _is_obj_list(data) and len(data) > 0
    except (httpx.HTTPError, OSError, ValueError, TypeError, KeyError):
        return False


def render_cliproxy_endpoint_template(
    template: str,
    deployment: CliProxyDeployment,
) -> str:
    """Render endpoint template by substituting ${CLIPROXY_CLIENT_BASE_URL}."""
    if CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER not in template:
        msg = (
            "missing CLIProxyAPI endpoint placeholder: "
            f"{CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER}"
        )
        raise ValueError(msg)
    return template.replace(
        CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER,
        deployment.client.base_url,
    )


def _skip_spaces(raw: str, i: int) -> int:
    length = len(raw)
    while i < length and raw[i] in (" ", "\t"):
        i += 1
    return i


def _parse_double_quoted(raw: str, i: int) -> tuple[str, int] | None:
    length = len(raw)
    value = ""
    escape_map = {"n": "\n", "t": "\t", "r": "\r"}
    while i < length:
        c = raw[i]
        if c == "\\":
            i += 1
            if i >= length:
                return None
            esc = raw[i]
            value += escape_map.get(esc, esc)
            i += 1
        elif c == '"':
            return value, i + 1
        else:
            value += c
            i += 1
    return None


def _parse_single_quoted(raw: str, i: int) -> tuple[str, int] | None:
    length = len(raw)
    value = ""
    while i < length:
        c = raw[i]
        if c == "'":
            return value, i + 1
        value += c
        i += 1
    return None


def _parse_bare_key(raw: str, i: int) -> tuple[str, int] | None:
    length = len(raw)
    key = ""
    while i < length and raw[i] not in BARE_KEY_DELIMITERS:
        key += raw[i]
        i += 1
    if not key:
        return None
    return key, i


def parse_toml_key_path(raw: str) -> list[str] | None:
    """Parse a dotted/quoted TOML key path into a list of key segments."""
    segments: list[str] = []
    i = 0
    length = len(raw)

    while i < length:
        i = _skip_spaces(raw, i)
        if i >= length:
            break

        char = raw[i]
        if char == '"':
            res = _parse_double_quoted(raw, i + 1)
        elif char == "'":
            res = _parse_single_quoted(raw, i + 1)
        else:
            res = _parse_bare_key(raw, i)

        if res is None:
            return None
        segment, i = res
        segments.append(segment)

        i = _skip_spaces(raw, i)
        if i < length and raw[i] == ".":
            i = _skip_spaces(raw, i + 1)
            if i >= length:
                return None
        else:
            break

    i = _skip_spaces(raw, i)
    if i < length:
        return None
    return segments or None


def _find_closing_bracket(trimmed: str, *, is_array: bool) -> int:
    i = 2 if is_array else 1
    length = len(trimmed)
    in_double = False
    in_single = False

    while i < length:
        c = trimmed[i]
        if in_double:
            if c == "\\":
                i += 2
                continue
            in_double = c != '"'
            i += 1
            continue
        if in_single:
            in_single = c != "'"
            i += 1
            continue
        if c == '"':
            in_double = True
        elif c == "'":
            in_single = True
        elif (is_array and trimmed[i : i + 2] == "]]") or (not is_array and c == "]"):
            return i
        i += 1
    return -1


def parse_toml_table_header(line: str) -> list[str] | None:
    """Parse a TOML table header [a.b] or array header [[a.b]] into segments."""
    trimmed = line[:-1].rstrip("\r").strip() if line.endswith("\n") else line.strip()
    if not trimmed.startswith("["):
        return None

    is_array = trimmed.startswith("[[")
    open_bracket_count = 2 if is_array else 1
    close_bracket_index = _find_closing_bracket(trimmed, is_array=is_array)
    if close_bracket_index == -1:
        return None

    rest = trimmed[close_bracket_index + open_bracket_count :].strip()
    if len(rest) > 0 and not rest.startswith("#"):
        return None

    inner = trimmed[open_bracket_count:close_bracket_index]
    return parse_toml_key_path(inner)


@dataclass
class _TomlSection:
    header_segments: list[str] | None
    lines: list[str]


def _split_toml_sections(lines: list[str]) -> list[_TomlSection]:
    sections: list[_TomlSection] = []
    current_section = _TomlSection(header_segments=None, lines=[])
    for line in lines:
        header = parse_toml_table_header(line)
        if header is not None:
            if (
                current_section.header_segments is not None
                or len(current_section.lines) > 0
            ):
                sections.append(current_section)
            current_section = _TomlSection(header_segments=header, lines=[line])
        else:
            current_section.lines.append(line)
    if current_section.header_segments is not None or len(current_section.lines) > 0:
        sections.append(current_section)
    return sections


def _header_matches_prefix(hdr: list[str], target: list[str]) -> bool:
    return len(hdr) >= len(target) and hdr[: len(target)] == target


def extract_preserved_top_levels(
    existing: str,
    top_levels: Sequence[str],
) -> str:
    """Extract preserved top-level TOML sections from existing content."""
    if not top_levels:
        return ""
    parsed_top_levels = [
        parsed
        for tl in top_levels
        if (parsed := parse_toml_key_path(tl)) is not None and len(parsed) > 0
    ]
    if not parsed_top_levels:
        return ""

    sections = _split_toml_sections(existing.splitlines(keepends=True))
    preserved = [
        s
        for s in sections
        if s.header_segments is not None
        and any(_header_matches_prefix(s.header_segments, t) for t in parsed_top_levels)
    ]
    if not preserved:
        return ""

    joined = "\n\n".join("".join(s.lines).rstrip() for s in preserved)
    return f"{joined}\n"


def read_preserved_top_levels(
    path: str | Path,
    top_levels: Sequence[str],
) -> str:
    """Read existing file and extract matching preserved top-level TOML tables."""
    if not top_levels:
        return ""
    path_obj = Path(path)
    try:
        existing = path_obj.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    except OSError as error:
        if is_errno(error, "ENOENT"):
            return ""
        raise
    return extract_preserved_top_levels(existing, top_levels)


def append_preserved_sections(rendered: str, preserved: str) -> str:
    """Append preserved TOML sections to rendered content with blank line separation."""
    if not preserved:
        return rendered
    if not rendered:
        return preserved
    if rendered.endswith("\n\n"):
        return f"{rendered}{preserved}"
    if rendered.endswith("\n"):
        return f"{rendered}\n{preserved}"
    return f"{rendered}\n\n{preserved}"


def _existing_file_mode(path: Path) -> int | None:
    try:
        st = path.lstat()
    except OSError:
        return None
    else:
        if stat.S_ISREG(st.st_mode) and not stat.S_ISLNK(st.st_mode):
            return st.st_mode & 0o777
        return None


def sync_cliproxy_endpoint_template(
    src: str | Path,
    dst: str | Path,
    deployment: CliProxyDeployment,
    preserve_top_levels: Sequence[str] = (),
) -> None:
    """Render endpoint template and synchronize to destination preserving sections."""
    src_p = Path(src)
    dst_p = Path(dst)
    try:
        template = src_p.read_text(encoding="utf-8")
        existing_mode = _existing_file_mode(dst_p)
        mode = (
            existing_mode
            if existing_mode is not None
            else (src_p.stat().st_mode & 0o777)
        )
    except OSError as error:
        msg = f"read CLIProxyAPI endpoint template {src_p} ({panic_message(error)})"
        raise RuntimeError(msg) from error

    try:
        rendered = render_cliproxy_endpoint_template(template, deployment)
        preserved = read_preserved_top_levels(dst_p, preserve_top_levels)
        sync_text_file(
            dst_p,
            append_preserved_sections(rendered, preserved),
            mode,
        )
    except (OSError, ValueError, RuntimeError) as error:
        msg = (
            f"render CLIProxyAPI endpoint template {src_p} -> {dst_p} "
            f"({panic_message(error)})"
        )
        raise RuntimeError(msg) from error


@dataclass(frozen=True)
class CliProxyEndpointTarget:
    """Target file for endpoint template synchronization."""

    src: str
    dst: str
    preserve_top_levels: Sequence[str] = ()


CliProxyEndpointPublication = Literal["published", "skipped"]


@dataclass(frozen=True, slots=True)
class MissingEndpointTarget:
    """Endpoint destination did not exist before sync."""

    path: Path


@dataclass(frozen=True, slots=True)
class FileEndpointTarget:
    """Endpoint destination held a regular file before sync."""

    path: Path
    content: str
    mode: int


@dataclass(frozen=True, slots=True)
class SymlinkEndpointTarget:
    """Endpoint destination held a symlink before sync."""

    path: Path
    link: str


@dataclass(frozen=True, slots=True)
class OtherEndpointTarget:
    """Endpoint destination held a non-file, non-symlink entry before sync."""

    path: Path


EndpointTargetSnapshot = (
    MissingEndpointTarget
    | FileEndpointTarget
    | SymlinkEndpointTarget
    | OtherEndpointTarget
)


def _snapshot_endpoint_target(path: Path) -> EndpointTargetSnapshot:
    try:
        st = path.lstat()
        if stat.S_ISLNK(st.st_mode):
            return SymlinkEndpointTarget(path=path, link=str(path.readlink()))
        if not stat.S_ISREG(st.st_mode):
            return OtherEndpointTarget(path=path)
        return FileEndpointTarget(
            path=path,
            content=path.read_text(encoding="utf-8"),
            mode=st.st_mode & 0o777,
        )
    except FileNotFoundError:
        return MissingEndpointTarget(path=path)
    except OSError as error:
        if is_errno(error, "ENOENT"):
            return MissingEndpointTarget(path=path)
        raise


def _restore_single_snapshot(snapshot: EndpointTargetSnapshot) -> None:
    match snapshot:
        case MissingEndpointTarget(path=path):
            with contextlib.suppress(OSError):
                if path.is_symlink() or path.is_file():
                    path.unlink(missing_ok=True)
                elif path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
        case FileEndpointTarget(path=path, content=content, mode=mode):
            sync_text_file(path, content, mode)
        case SymlinkEndpointTarget(path=path, link=link):
            with contextlib.suppress(OSError):
                path.unlink(missing_ok=True)
            path.symlink_to(link)
        case OtherEndpointTarget():
            pass


def _restore_endpoint_targets(
    snapshots: Sequence[EndpointTargetSnapshot],
) -> None:
    for snapshot in snapshots:
        _restore_single_snapshot(snapshot)


def publish_cliproxy_endpoint_templates(
    targets: Sequence[CliProxyEndpointTarget],
    deployment: CliProxyDeployment,
    options: CliProxyEndpointSyncOptions | None = None,
) -> CliProxyEndpointPublication:
    """Publish rendered endpoint templates or roll back on write failure."""
    if not targets:
        return "published"

    opts = options or CliProxyEndpointSyncOptions()
    if not opts.skip_readiness and not is_cliproxy_target_ready(deployment, opts):
        return "skipped"

    snapshots = [_snapshot_endpoint_target(Path(target.dst)) for target in targets]
    try:
        for target in targets:
            sync_cliproxy_endpoint_template(
                target.src,
                target.dst,
                deployment,
                target.preserve_top_levels,
            )
    except Exception:
        _restore_endpoint_targets(snapshots)
        raise
    return "published"
