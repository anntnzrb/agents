# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""CLIProxyAPI configuration rendering and synchronization."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Final, TypeGuard

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sync.core.cliproxy_deployment import CliProxyDeployment
from sync.runtime.errors import panic_message
from sync.runtime.fs import sync_private_text_file
from sync.runtime.jsonc import strip_jsonc

POOL_NAME_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9-]*$")
POOL_MARKER: Final[str] = "x-credential-pool"
MIN_CREDENTIAL_WEIGHT: Final[int] = 1
MAX_CREDENTIAL_WEIGHT: Final[int] = 1_000_000

NATIVE_CREDENTIAL_SECTIONS: Final[tuple[str, ...]] = (
    "claude-api-key",
    "codex-api-key",
    "gemini-api-key",
    "interactions-api-key",
    "vertex-api-key",
    "xai-api-key",
)

OWNED_NATIVE_FIELDS: Final[tuple[str, ...]] = ("api-key", "weight", "proxy-url")
OWNED_COMPATIBILITY_FIELDS: Final[tuple[str, ...]] = ("api-key-entries",)


class Credential(BaseModel):
    """Single upstream API credential within a pool."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        populate_by_name=True,
    )

    api_key: str = Field(alias="apiKey", min_length=1)
    weight: int | None = Field(
        default=None,
        ge=MIN_CREDENTIAL_WEIGHT,
        le=MAX_CREDENTIAL_WEIGHT,
    )
    proxy_url: str | None = Field(default=None, alias="proxyUrl", min_length=1)


class CliProxySecrets(BaseModel):
    """Collection of named credential pools for CLIProxyAPI."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        populate_by_name=True,
    )

    cliproxy_credential_pools: dict[str, list[Credential]] = Field(
        alias="CLIPROXY_CREDENTIAL_POOLS",
    )

    @field_validator("cliproxy_credential_pools")
    @classmethod
    def _validate_pools(
        cls,
        pools: dict[str, list[Credential]],
    ) -> dict[str, list[Credential]]:
        for pool_name, credentials in pools.items():
            if not pool_name or not POOL_NAME_PATTERN.match(pool_name):
                msg = f"invalid pool name: {pool_name}"
                raise ValueError(msg)
            if not credentials:
                msg = f"empty credential pool: {pool_name}"
                raise ValueError(msg)
            seen_keys: set[str] = set()
            for cred in credentials:
                if cred.api_key in seen_keys:
                    msg = (
                        f"duplicate API key in CLIProxyAPI credential pool: {pool_name}"
                    )
                    raise ValueError(msg)
                seen_keys.add(cred.api_key)
        return pools


def credential_config(credential: Credential) -> dict[str, object]:
    """Serialize a single Credential into YAML config record format."""
    result: dict[str, object] = {"api-key": credential.api_key}
    if credential.weight is not None:
        result["weight"] = credential.weight
    if credential.proxy_url is not None:
        result["proxy-url"] = credential.proxy_url
    return result


def _validate_pool_marker(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) == 0:
        msg = f"invalid {label}.{POOL_MARKER}: expected non-empty string"
        raise ValueError(msg)
    return value


def _reject_owned_fields(
    record: dict[str, object],
    label: str,
    fields: Sequence[str],
) -> None:
    for field in fields:
        if field in record:
            msg = f"invalid {label}: {field} is owned by its credential pool"
            raise ValueError(msg)


def _require_pool(
    pool_name: str,
    pools: dict[str, list[Credential]],
) -> list[Credential]:
    pool = pools.get(pool_name)
    if pool is None:
        msg = f"missing CLIProxyAPI credential pool: {pool_name}"
        raise ValueError(msg)
    return pool


def _is_obj_list(val: object) -> TypeGuard[list[object]]:
    return isinstance(val, list)


def _is_obj_dict(val: object) -> TypeGuard[dict[str, object]]:
    return isinstance(val, dict)


def _expand_native_credential_section(
    section_name: str,
    value: object,
    pools: dict[str, list[Credential]],
    referenced_pools: set[str],
) -> list[dict[str, object]]:
    if not _is_obj_list(value):
        msg = f"invalid {section_name}: expected array"
        raise TypeError(msg)
    result: list[dict[str, object]] = []
    for index, raw_item in enumerate(value):
        label = f"{section_name}[{index}]"
        if not _is_obj_dict(raw_item):
            msg = f"invalid {label}: expected object"
            raise TypeError(msg)
        profile: dict[str, object] = dict(raw_item)
        if POOL_MARKER not in profile:
            result.append(profile)
            continue
        pool_marker_val = profile[POOL_MARKER]
        pool_name = _validate_pool_marker(pool_marker_val, label)
        _reject_owned_fields(profile, label, OWNED_NATIVE_FIELDS)
        credentials = _require_pool(pool_name, pools)
        referenced_pools.add(pool_name)
        shared_profile = {k: v for k, v in profile.items() if k != POOL_MARKER}
        result.extend(credential_config(cred) | shared_profile for cred in credentials)
    return result


def _expand_compatibility_section(
    value: object,
    pools: dict[str, list[Credential]],
    referenced_pools: set[str],
) -> list[dict[str, object]]:
    if not _is_obj_list(value):
        msg = "invalid openai-compatibility: expected array"
        raise TypeError(msg)
    result: list[dict[str, object]] = []
    for index, raw_item in enumerate(value):
        label = f"openai-compatibility[{index}]"
        if not _is_obj_dict(raw_item):
            msg = f"invalid {label}: expected object"
            raise TypeError(msg)
        profile: dict[str, object] = dict(raw_item)
        if POOL_MARKER not in profile:
            result.append(profile)
            continue
        pool_marker_val = profile[POOL_MARKER]
        pool_name = _validate_pool_marker(pool_marker_val, label)
        _reject_owned_fields(profile, label, OWNED_COMPATIBILITY_FIELDS)
        credentials = _require_pool(pool_name, pools)
        referenced_pools.add(pool_name)
        shared_profile = {k: v for k, v in profile.items() if k != POOL_MARKER}
        result.append(
            shared_profile
            | {
                "api-key-entries": [credential_config(cred) for cred in credentials],
            }
        )
    return result


def render_cliproxy_config(
    template: str,
    secrets: CliProxySecrets | Mapping[str, object],
    deployment: CliProxyDeployment,
) -> str:
    """Render CLIProxyAPI configuration YAML from template, secrets, and deployment."""
    try:
        parsed: object = yaml.safe_load(template)
    except Exception as error:
        msg = f"parse CLIProxyAPI template ({panic_message(error)})"
        raise RuntimeError(msg) from error

    if not _is_obj_dict(parsed):
        msg = "invalid CLIProxyAPI template root: expected object"
        raise TypeError(msg)

    config: dict[str, object] = dict(parsed)
    if "x-model-sources" in config:
        msg = "unsupported CLIProxyAPI template field: x-model-sources"
        raise ValueError(msg)
    config["host"] = deployment.listen.host
    config["port"] = deployment.listen.port
    referenced_pools: set[str] = set()

    validated_secrets = (
        secrets
        if isinstance(secrets, CliProxySecrets)
        else CliProxySecrets.model_validate(secrets)
    )
    pools = validated_secrets.cliproxy_credential_pools

    for section_name in NATIVE_CREDENTIAL_SECTIONS:
        if section_name in config:
            config[section_name] = _expand_native_credential_section(
                section_name,
                config[section_name],
                pools,
                referenced_pools,
            )

    if "openai-compatibility" in config:
        config["openai-compatibility"] = _expand_compatibility_section(
            config["openai-compatibility"],
            pools,
            referenced_pools,
        )

    unreferenced_pools = [name for name in pools if name not in referenced_pools]
    if unreferenced_pools:
        unref_str = ", ".join(unreferenced_pools)
        msg = f"unreferenced CLIProxyAPI credential pool: {unref_str}"
        raise ValueError(msg)

    content = yaml.safe_dump(config, sort_keys=False)
    # Sanity check roundtrip
    yaml.safe_load(content)
    return content if content.endswith("\n") else f"{content}\n"


def read_cliproxy_secrets(path: str | Path) -> CliProxySecrets:
    """Read and validate CLIProxyAPI secrets from JSON/JSONC file."""
    path_obj = Path(path)
    try:
        text = path_obj.read_text(encoding="utf-8")
    except OSError as error:
        msg = f"read CLIProxyAPI secrets {path_obj} ({panic_message(error)})"
        raise RuntimeError(msg) from error

    try:
        stripped = strip_jsonc(text)
        parsed: object = json.loads(stripped)
    except Exception as error:
        msg = f"parse CLIProxyAPI secrets {path_obj} ({panic_message(error)})"
        raise RuntimeError(msg) from error

    try:
        return CliProxySecrets.model_validate(parsed)
    except Exception as error:
        msg = f"invalid CLIProxyAPI secrets {path_obj} ({panic_message(error)})"
        raise RuntimeError(msg) from error


def sync_cliproxy_config(
    src: str | Path,
    dst: str | Path,
    secrets_path: str | Path,
    deployment: CliProxyDeployment,
) -> None:
    """Render and write CLIProxyAPI configuration with 0600 permissions."""
    src_p = Path(src)
    dst_p = Path(dst)
    secrets_p = Path(secrets_path)
    try:
        template = src_p.read_text(encoding="utf-8")
    except OSError as error:
        msg = f"read CLIProxyAPI template {src_p} ({panic_message(error)})"
        raise RuntimeError(msg) from error

    secrets = read_cliproxy_secrets(secrets_p)
    content = render_cliproxy_config(template, secrets, deployment)
    try:
        sync_private_text_file(dst_p, content)
    except Exception as error:
        msg = f"render CLIProxyAPI config {src_p} -> {dst_p} ({panic_message(error)})"
        raise RuntimeError(msg) from error
