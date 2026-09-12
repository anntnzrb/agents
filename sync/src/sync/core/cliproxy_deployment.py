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
import tomllib
import urllib.parse
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Final, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from sync.runtime.errors import is_errno, panic_message
from sync.runtime.fs import sync_text_file
from sync.runtime.jsonc import is_obj_dict, is_obj_list, strip_jsonc

INVALID_LISTEN_HOST_PATTERN: Final[re.Pattern[str]] = re.compile(r"[\s/?#@]")
INVALID_SERVER_HOSTNAME_PATTERN: Final[re.Pattern[str]] = re.compile(r"[\s/?#@:]")
INVALID_CLIENT_URL_DELIMITER_PATTERN: Final[re.Pattern[str]] = re.compile(r"[?#]")
IPV4_ZERO_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^(?:0+(?:\.0+){0,3}|0x0+)$",
    re.IGNORECASE,
)
CLIENT_BASE_URL_PLACEHOLDER_NAME: Final[str] = "CLIPROXY_CLIENT_BASE_URL"
CLI_PROXY_SOURCE_DIR: Final[str] = "tools/cliproxyapi"
CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER: Final[str] = (
    f"${{{CLIENT_BASE_URL_PLACEHOLDER_NAME}}}"
)

ENDPOINT_READY_TIMEOUT_MS: Final[int] = 500
MIN_PORT: Final[int] = 1
MAX_PORT: Final[int] = 65535
DEFAULT_FILE_MODE: Final[int] = 0o644


def _is_unspecified_host(host: str) -> bool:
    if IPV4_ZERO_PATTERN.match(host):
        return True
    address = host.split("%", maxsplit=1)[0]
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    else:
        return ip.is_unspecified


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
            or _is_unspecified_host(host)
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


def parse_cliproxy_deployment(value: object) -> CliProxyDeployment:
    """Parse and validate CLIProxyAPI deployment dictionary."""
    if not is_obj_dict(value):
        msg = "invalid CLIProxyAPI deployment: expected object"
        raise ValueError(msg)
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
        resp = (
            opts.fetch(url, headers=headers, timeout=timeout_sec)
            if opts.fetch is not None
            else httpx.get(url, headers=headers, timeout=timeout_sec)
        )
        if not resp.is_success:
            return False
        payload: object = resp.json()  # pyright: ignore[reportAny]
        if not is_obj_dict(payload):
            return False
        data = payload.get("data")
        return is_obj_list(data) and len(data) > 0
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


def parse_toml_key_path(raw: str) -> list[str] | None:
    """Parse a dotted/quoted TOML key path into a list of key segments."""
    if not raw or not raw.strip():
        return None
    try:
        data: object = tomllib.loads(f"[{raw}]\n")
    except tomllib.TOMLDecodeError:
        return None
    return _toml_single_path(data)


def _toml_single_path(data: object) -> list[str] | None:
    """Walk nested single-key TOML tables/arrays into a key segment list."""
    keys: list[str] = []
    curr: object = data
    while True:
        if is_obj_dict(curr) and curr:
            k = next(iter(curr.keys()))
            keys.append(k)
            curr = curr.get(k)
        elif is_obj_list(curr) and curr:
            curr = curr[0]
        else:
            break
    return keys or None


def parse_toml_table_header(line: str) -> list[str] | None:
    """Parse a TOML table header [a.b] or array header [[a.b]] into segments."""
    trimmed = line.strip()
    if not trimmed.startswith("["):
        return None
    try:
        data: object = tomllib.loads(trimmed + "\n")
    except tomllib.TOMLDecodeError:
        return None
    return _toml_single_path(data)


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

    preserved: list[list[str]] = []
    current: list[str] | None = None
    for line in existing.splitlines(keepends=True):
        header = parse_toml_table_header(line)
        if header is not None:
            current = None
            if any(header[: len(prefix)] == prefix for prefix in parsed_top_levels):
                current = []
                preserved.append(current)
        if current is not None:
            current.append(line)
    if not preserved:
        return ""
    return "\n\n".join("".join(lines).rstrip() for lines in preserved) + "\n"


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


def _restore_endpoint_targets(
    snapshots: Sequence[EndpointTargetSnapshot],
) -> None:
    for snap in snapshots:
        match snap:
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
