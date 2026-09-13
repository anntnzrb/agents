# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""CLIProxyAPI configuration rendering and synchronization."""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Final, NotRequired, TypedDict

import httpx
import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

if TYPE_CHECKING:
    from sync.core.cliproxy_deployment import CliProxyDeployment
from sync.runtime.errors import panic_message, warn
from sync.runtime.fs import sync_text_file
from sync.runtime.jsonc import is_obj_dict, is_obj_list, strip_jsonc

POOL_NAME_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9-]*$")
POOL_MARKER: Final[str] = "x-credential-pool"
DISCOVERY_MARKER: Final[str] = "x-model-discovery"
DISCOVERY_TIMEOUT_SECONDS: Final[float] = 5.0
MODELS_DEV_URL: Final[str] = "https://models.dev/api.json"
MODELS_DEV_TTL_SECONDS: Final[float] = 24 * 60 * 60
MODELS_DEV_TIMEOUT_SECONDS: Final[float] = 10.0
MODELS_DEV_CACHE_VERSION: Final[int] = 2
MODELS_DEV_QUALIFIER_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"-(minimal|low|medium|high|max|thinking)$",
    re.IGNORECASE,
)
THINKING_LEVELS_DEFAULT: Final[tuple[str, ...]] = ("low", "medium", "high")
THINKING_LEVELS_DISABLED: Final[tuple[str, ...]] = ("none",)
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


class UpstreamModelEntry(TypedDict):
    """Model record returned by an upstream /models endpoint."""

    id: str
    name: NotRequired[str]
    context_length: NotRequired[int]


class CatalogModelEntry(TypedDict):
    """Normalized external-catalog metadata for a single model id."""

    name: NotRequired[str]
    context_length: NotRequired[int]
    reasoning: NotRequired[bool]


type ModelListFetcher = Callable[[str, str], list[UpstreamModelEntry] | None]
type CatalogLookup = Callable[[str], CatalogModelEntry | None]


@dataclass(frozen=True)
class DiscoveryOptions:
    """Collaborators for x-model-discovery pools during rendering."""

    fetch: ModelListFetcher | None = None
    previous: Mapping[str, Sequence[object]] | None = None
    catalog: CatalogLookup | None = None


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


def fetch_upstream_models(
    base_url: str,
    api_key: str,
) -> list[UpstreamModelEntry] | None:
    """Return upstream model records, or None when the endpoint is unavailable."""
    url = f"{base_url.rstrip('/')}/models"
    headers = {"Accept": "application/json", "Authorization": f"Bearer {api_key}"}
    try:
        response = httpx.get(url, headers=headers, timeout=DISCOVERY_TIMEOUT_SECONDS)
        if not response.is_success:
            return None
        payload: object = response.json()  # pyright: ignore[reportAny]
    except (httpx.HTTPError, OSError, ValueError, TypeError):
        return None
    if not is_obj_dict(payload):
        return None
    data = payload.get("data")
    if not is_obj_list(data):
        return None
    entries: list[UpstreamModelEntry] = []
    for item in data:
        if not is_obj_dict(item):
            continue
        identifier = item.get("id")
        if not isinstance(identifier, str) or not identifier:
            continue
        entry: UpstreamModelEntry = {"id": identifier}
        name = item.get("name")
        if isinstance(name, str) and name:
            entry["name"] = name
        context_length = item.get("context_length")
        if (
            isinstance(context_length, int)
            and not isinstance(context_length, bool)
            and context_length > 0
        ):
            entry["context_length"] = context_length
        entries.append(entry)
    return entries


def _models_dev_cache_path() -> Path:
    cache_home = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(cache_home) / "agents" / "models-dev.json"


def _widest_record(
    current: dict[str, object] | None,
    candidate: dict[str, object],
) -> dict[str, object]:
    """Keep the record reporting the largest context limit on id collisions."""
    if current is None:
        return candidate
    current_limit = current.get("limit")
    candidate_limit = candidate.get("limit")
    current_ctx = current_limit.get("context") if is_obj_dict(current_limit) else None
    candidate_ctx = (
        candidate_limit.get("context") if is_obj_dict(candidate_limit) else None
    )
    if (
        isinstance(candidate_ctx, int)
        and not isinstance(candidate_ctx, bool)
        and (
            not isinstance(current_ctx, int)
            or isinstance(current_ctx, bool)
            or candidate_ctx > current_ctx
        )
    ):
        return candidate
    return current


def _normalize_models_dev(
    payload: object,
) -> dict[str, dict[str, dict[str, object]]]:
    """Flatten models.dev providers into id/suffix/stripped lookup maps."""
    maps: dict[str, dict[str, dict[str, object]]] = {
        "models": {},
        "suffixes": {},
        "stripped": {},
    }
    if not is_obj_dict(payload):
        return maps
    for provider in payload.values():
        if not is_obj_dict(provider):
            continue
        provider_models = provider.get("models")
        if not is_obj_dict(provider_models):
            continue
        for model_id, raw_model in provider_models.items():
            if not is_obj_dict(raw_model):
                continue
            record = dict(raw_model)
            suffix = model_id.rsplit("/", 1)[-1]
            key = MODELS_DEV_QUALIFIER_PATTERN.sub("", suffix)
            maps["models"][model_id] = _widest_record(
                maps["models"].get(model_id), record
            )
            maps["suffixes"][suffix] = _widest_record(
                maps["suffixes"].get(suffix), record
            )
            maps["stripped"][key] = _widest_record(maps["stripped"].get(key), record)
    return maps


def _catalog_entry(raw: Mapping[str, object]) -> CatalogModelEntry:
    """Project a models.dev record into normalized catalog metadata."""
    entry: CatalogModelEntry = {}
    name = raw.get("name")
    if isinstance(name, str) and name:
        entry["name"] = name
    limit = raw.get("limit")
    if is_obj_dict(limit):
        context = limit.get("context")
        if isinstance(context, int) and not isinstance(context, bool) and context > 0:
            entry["context_length"] = context
    reasoning = raw.get("reasoning")
    if isinstance(reasoning, bool):
        entry["reasoning"] = reasoning
    return entry


def _read_models_dev_cache(
    path: Path,
) -> tuple[dict[str, dict[str, dict[str, object]]] | None, bool]:
    """Read cached models.dev maps; reports (maps, fresh)."""
    try:
        cached: object = json.loads(path.read_text(encoding="utf-8"))  # pyright: ignore[reportAny]
    except (OSError, ValueError):
        return None, False
    if not is_obj_dict(cached):
        return None, False
    maps: dict[str, dict[str, dict[str, object]]] = {}
    for key in ("models", "suffixes", "stripped"):
        value = cached.get(key)
        if is_obj_dict(value):
            maps[key] = {k: dict(v) for k, v in value.items() if is_obj_dict(v)}
    if not maps.get("models"):
        return None, False
    fetched_at = cached.get("fetchedAt")
    fresh = (
        isinstance(fetched_at, int | float)
        and not isinstance(fetched_at, bool)
        and (time.time() * 1000 - fetched_at) < MODELS_DEV_TTL_SECONDS * 1000
    )
    return maps, fresh


def _load_models_dev_maps() -> dict[str, dict[str, dict[str, object]]]:
    """Load models.dev lookup maps, refreshing the shared cache when stale."""
    path = _models_dev_cache_path()
    cached, fresh = _read_models_dev_cache(path)
    if cached is not None and fresh:
        return cached
    try:
        response = httpx.get(MODELS_DEV_URL, timeout=MODELS_DEV_TIMEOUT_SECONDS)
        if not response.is_success:
            return cached or _normalize_models_dev(None)
        payload: object = response.json()  # pyright: ignore[reportAny]
    except (httpx.HTTPError, OSError, ValueError, TypeError):
        return cached or _normalize_models_dev(None)
    maps = _normalize_models_dev(payload)
    if not maps["models"]:
        return cached or maps
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _ = path.write_text(
            json.dumps(
                {
                    "version": MODELS_DEV_CACHE_VERSION,
                    "fetchedAt": int(time.time() * 1000),
                    **maps,
                }
            ),
            encoding="utf-8",
        )
    except OSError:
        pass
    return maps


def models_dev_lookup() -> CatalogLookup:
    """Return a lazy lookup over the shared models.dev metadata cache."""
    loaded: list[dict[str, dict[str, dict[str, object]]]] = []

    def lookup(model_id: str) -> CatalogModelEntry | None:
        if not loaded:
            loaded.append(_load_models_dev_maps())
        maps = loaded[0]
        suffix = model_id.rsplit("/", 1)[-1]
        record = (
            maps["models"].get(model_id)
            or maps["suffixes"].get(model_id)
            or maps["stripped"].get(MODELS_DEV_QUALIFIER_PATTERN.sub("", model_id))
            or maps["stripped"].get(MODELS_DEV_QUALIFIER_PATTERN.sub("", suffix))
        )
        if record is None:
            return None
        return _catalog_entry(record)

    return lookup


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
    if not is_obj_dict(parsed):
        return {}
    profiles = parsed.get("openai-compatibility")
    if not is_obj_list(profiles):
        return {}
    previous: dict[str, list[object]] = {}
    for profile in profiles:
        if not is_obj_dict(profile):
            continue
        name = profile.get("name")
        models = profile.get("models")
        if isinstance(name, str) and is_obj_list(models):
            previous[name] = list(models)
    return previous


def _discovered_model_entry(
    upstream: UpstreamModelEntry,
    catalog_lookup: CatalogLookup | None,
) -> dict[str, object]:
    """Build a models[] entry from upstream data plus catalog fallback."""
    entry: dict[str, object] = {"name": upstream["id"]}
    catalog: CatalogModelEntry | None = None
    if catalog_lookup is not None:
        try:
            catalog = catalog_lookup(upstream["id"])
        except (httpx.HTTPError, OSError, RuntimeError, ValueError, TypeError):
            catalog = None
    name = upstream.get("name") or (catalog.get("name") if catalog else None)
    context_length = upstream.get("context_length") or (
        catalog.get("context_length") if catalog else None
    )
    if name:
        entry["display-name"] = name
    if context_length:
        entry["max-context-length"] = context_length
    if catalog is not None and "reasoning" in catalog:
        levels = (
            THINKING_LEVELS_DEFAULT
            if catalog["reasoning"]
            else THINKING_LEVELS_DISABLED
        )
        entry["thinking"] = {"levels": list(levels)}
    return entry


def _discover_profile_models(
    label: str,
    profile: dict[str, object],
    credential: Credential,
    discovery: DiscoveryOptions,
) -> list[dict[str, object]]:
    base_url = profile.get("base-url")
    if not isinstance(base_url, str) or not base_url:
        msg = f"invalid {label}: {DISCOVERY_MARKER} requires base-url"
        raise ValueError(msg)
    upstream_models: list[UpstreamModelEntry] | None = None
    if discovery.fetch is not None:
        try:
            upstream_models = discovery.fetch(base_url, credential.api_key)
        except (httpx.HTTPError, OSError, RuntimeError, ValueError, TypeError):
            upstream_models = None
    if upstream_models is not None:
        return [
            _discovered_model_entry(upstream, discovery.catalog)
            for upstream in upstream_models
        ]
    name = profile.get("name")
    previous = None
    if isinstance(name, str) and discovery.previous:
        previous = discovery.previous.get(name)
    if previous:
        warn(f"model discovery unavailable for {name}; reusing previous models")
        return [dict(item) for item in previous if is_obj_dict(item)]
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


def _expand_native_credential_section(
    section_name: str,
    value: object,
    pools: dict[str, list[Credential]],
    referenced_pools: set[str],
) -> list[dict[str, object]]:
    if not is_obj_list(value):
        msg = f"invalid {section_name}: expected array"
        raise TypeError(msg)
    result: list[dict[str, object]] = []
    for index, raw_item in enumerate(value):
        label = f"{section_name}[{index}]"
        if not is_obj_dict(raw_item):
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
    discovery: DiscoveryOptions,
) -> list[dict[str, object]]:
    if not is_obj_list(value):
        msg = "invalid openai-compatibility: expected array"
        raise TypeError(msg)
    result: list[dict[str, object]] = []
    for index, raw_item in enumerate(value):
        label = f"openai-compatibility[{index}]"
        if not is_obj_dict(raw_item):
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
                discovery,
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
    discovery: DiscoveryOptions | None = None,
) -> str:
    """Render CLIProxyAPI configuration YAML from template, secrets, and deployment."""
    try:
        parsed: object = yaml.safe_load(template)  # pyright: ignore[reportAny]
    except yaml.YAMLError as error:
        msg = f"parse CLIProxyAPI template ({panic_message(error)})"
        raise RuntimeError(msg) from error

    if not is_obj_dict(parsed):
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
            discovery or DiscoveryOptions(),
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
        discovery=DiscoveryOptions(
            fetch=fetch_upstream_models,
            previous=_read_previous_models(dst_p),
            catalog=models_dev_lookup(),
        ),
    )
    try:
        sync_text_file(dst_p, content)
    except (OSError, ValueError, RuntimeError) as error:
        msg = f"render CLIProxyAPI config {src_p} -> {dst_p} ({panic_message(error)})"
        raise RuntimeError(msg) from error
