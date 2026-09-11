# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""CLIProxyAPI configuration rendering and synchronization."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Final, TypeGuard

import httpx
import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

if TYPE_CHECKING:
    from sync.core.cliproxy_deployment import CliProxyDeployment
from sync.runtime.errors import panic_message, warn
from sync.runtime.fs import sync_private_text_file
from sync.runtime.jsonc import strip_jsonc

POOL_NAME_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9-]*$")
POOL_MARKER: Final[str] = "x-credential-pool"
DISCOVERY_MARKER: Final[str] = "x-model-discovery"
DISCOVERY_TIMEOUT_SECONDS: Final[float] = 5.0
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


type ModelListFetcher = Callable[[str, str], list[str] | None]


class Credential(BaseModel):
    """Single upstream API credential within a pool."""

    model_config: ClassVar[ConfigDict] = ConfigDict(
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

    model_config: ClassVar[ConfigDict] = ConfigDict(
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


def fetch_upstream_model_ids(base_url: str, api_key: str) -> list[str] | None:
    """Return upstream model ids, or None when the endpoint is unavailable."""
    url = f"{base_url.rstrip('/')}/models"
    headers = {"Accept": "application/json", "Authorization": f"Bearer {api_key}"}
    try:
        response = httpx.get(url, headers=headers, timeout=DISCOVERY_TIMEOUT_SECONDS)
        if not response.is_success:
            return None
        payload: object = response.json()  # pyright: ignore[reportAny]
    except (httpx.HTTPError, OSError, ValueError, TypeError):
        return None
    if not _is_obj_dict(payload):
        return None
    data = payload.get("data")
    if not _is_obj_list(data):
        return None
    ids: list[str] = []
    for item in data:
        if _is_obj_dict(item):
            identifier = item.get("id")
            if isinstance(identifier, str) and identifier:
                ids.append(identifier)
    return ids


def _validate_discovery(value: object, label: str) -> None:
    if value is not True:
        msg = f"invalid {label}.{DISCOVERY_MARKER}: expected true"
        raise ValueError(msg)


def _read_previous_models(path: Path) -> dict[str, list[object]]:
    """Collect the previous rendered model lists keyed by compatibility profile name."""
    try:
        parsed: object = yaml.safe_load(path.read_text(encoding="utf-8"))  # pyright: ignore[reportAny]
    except (OSError, yaml.YAMLError):
        return {}
    if not _is_obj_dict(parsed):
        return {}
    profiles = parsed.get("openai-compatibility")
    if not _is_obj_list(profiles):
        return {}
    previous: dict[str, list[object]] = {}
    for profile in profiles:
        if not _is_obj_dict(profile):
            continue
        name = profile.get("name")
        models = profile.get("models")
        if isinstance(name, str) and _is_obj_list(models):
            previous[name] = list(models)
    return previous


def _discover_profile_models(
    label: str,
    profile: dict[str, object],
    credential: Credential,
    discover: ModelListFetcher | None,
    previous_models: Mapping[str, Sequence[object]] | None,
) -> list[dict[str, object]]:
    base_url = profile.get("base-url")
    if not isinstance(base_url, str) or not base_url:
        msg = f"invalid {label}: {DISCOVERY_MARKER} requires base-url"
        raise ValueError(msg)
    ids: list[str] | None = None
    if discover is not None:
        try:
            ids = discover(base_url, credential.api_key)
        except (httpx.HTTPError, OSError, RuntimeError, ValueError, TypeError):
            ids = None
    if ids is not None:
        return [{"name": model_id} for model_id in ids]
    name = profile.get("name")
    previous = None
    if isinstance(name, str) and previous_models:
        previous = previous_models.get(name)
    if previous:
        warn(f"model discovery unavailable for {name}; reusing previous models")
        return [dict(item) for item in previous if _is_obj_dict(item)]
    warn(f"model discovery unavailable for {name}; no models declared")
    return []


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
    discover: ModelListFetcher | None,
    previous_models: Mapping[str, Sequence[object]] | None,
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
            if DISCOVERY_MARKER in profile:
                msg = f"invalid {label}: {DISCOVERY_MARKER} requires {POOL_MARKER}"
                raise ValueError(msg)
            result.append(profile)
            continue
        pool_marker_val = profile[POOL_MARKER]
        pool_name = _validate_pool_marker(pool_marker_val, label)
        _reject_owned_fields(profile, label, OWNED_COMPATIBILITY_FIELDS)
        credentials = _require_pool(pool_name, pools)
        referenced_pools.add(pool_name)
        shared_profile = {k: v for k, v in profile.items() if k != POOL_MARKER}
        if DISCOVERY_MARKER in shared_profile:
            _validate_discovery(shared_profile.pop(DISCOVERY_MARKER), label)
            shared_profile["models"] = _discover_profile_models(
                label,
                shared_profile,
                credentials[0],
                discover,
                previous_models,
            )
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
    discover: ModelListFetcher | None = None,
    previous_models: Mapping[str, Sequence[object]] | None = None,
) -> str:
    """Render CLIProxyAPI configuration YAML from template, secrets, and deployment."""
    try:
        parsed: object = yaml.safe_load(template)  # pyright: ignore[reportAny]
    except yaml.YAMLError as error:
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
            discover,
            previous_models,
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
        parsed: object = json.loads(stripped)  # pyright: ignore[reportAny]
    except (ValueError, TypeError) as error:
        msg = f"parse CLIProxyAPI secrets {path_obj} ({panic_message(error)})"
        raise RuntimeError(msg) from error

    try:
        return CliProxySecrets.model_validate(parsed)
    except ValidationError as error:
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
    content = render_cliproxy_config(
        template,
        secrets,
        deployment,
        discover=fetch_upstream_model_ids,
        previous_models=_read_previous_models(dst_p),
    )
    try:
        sync_private_text_file(dst_p, content)
    except (OSError, ValueError, RuntimeError) as error:
        msg = f"render CLIProxyAPI config {src_p} -> {dst_p} ({panic_message(error)})"
        raise RuntimeError(msg) from error
