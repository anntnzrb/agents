# ruff: noqa: CPY001
# ruff: noqa: S310
"""Fetch, normalize, and persist Artificial Analysis data snapshots."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

if TYPE_CHECKING:
    from pathlib import Path
    from typing import Any, NoReturn

NOT_MODIFIED = 304
MIN_SAMPLE_SIZE = 2
BASE_URL = "https://artificialanalysis.ai/leaderboards/providers"
MODEL_API_URL = "https://artificialanalysis.ai/api/v2/data/llms/models"
MODEL_API_KEY_ENV = "ARTIFICIAL_ANALYSIS_API_KEY"
MODEL_API_BASE_URL_ENV = "ARTIFICIAL_ANALYSIS_API_BASE_URL"
CODING_CAPABILITY_URL = "https://artificialanalysis.ai/models/capabilities/coding"
CACHE_META_FILE = "providers-cache.json"
CACHE_BODY_FILE = "providers.rsc"
CACHE_LAST_GOOD_FILE = "last-good.json"
SNAPSHOT_SCHEMA_VERSION = 2


class ExtractionError(RuntimeError):
    """Raised when expected Artificial Analysis payload sections are missing."""


def _raise_extraction_error(
    message: str,
    cause: BaseException | None = None,
) -> NoReturn:
    if cause is None:
        raise ExtractionError(message)
    raise ExtractionError(message) from cause


def _raise_os_error(message: str, cause: BaseException) -> NoReturn:
    raise OSError(message) from cause


@dataclass(frozen=True)
class FetchResult:
    """HTTP response data captured while fetching a source."""

    body: str
    status_code: int
    headers: dict[str, str]
    fetched_at: str


@dataclass(frozen=True)
class CacheMetadata:
    """Metadata describing the cached provider response."""

    etag: str | None
    fetched_at: str | None
    status_code: int | None
    body_file: str


def fetch_rsc(
    url: str = BASE_URL,
    *,
    timeout_seconds: float = 60.0,
    if_none_match: str | None = None,
) -> FetchResult:
    """Fetch the provider endpoint payload using the RSC request protocol."""
    headers = {
        "RSC": "1",
        "Accept": "text/x-component, */*;q=0.8",
        "User-Agent": "artificial-analysis/0.3",
    }
    if if_none_match:
        headers["If-None-Match"] = if_none_match

    request = Request(url, headers=headers)
    fetched_at = datetime.now(UTC).isoformat()

    try:
        with urlopen(
            request,
            timeout=timeout_seconds,
        ) as response:
            body = response.read().decode("utf-8", errors="replace")
            return FetchResult(
                body=body,
                status_code=response.status,
                headers={k.lower(): v for k, v in response.headers.items()},
                fetched_at=fetched_at,
            )
    except HTTPError as exc:
        if exc.code == NOT_MODIFIED:
            return FetchResult(
                body="",
                status_code=NOT_MODIFIED,
                headers={k.lower(): v for k, v in exc.headers.items()},
                fetched_at=fetched_at,
            )
        message = f"Upstream request failed: HTTP {exc.code}"
        _raise_os_error(message, exc)


def fetch_models(
    api_key: str,
    *,
    timeout_seconds: float = 60.0,
    url: str | None = None,
) -> FetchResult:
    """Fetch the authenticated canonical-model source without retaining credentials."""
    request_url = url or os.environ.get(MODEL_API_BASE_URL_ENV) or MODEL_API_URL
    request = Request(
        request_url,
        headers={
            "Accept": "application/json",
            "User-Agent": "artificial-analysis/0.3",
            "x-api-key": api_key,
        },
    )
    fetched_at = datetime.now(UTC).isoformat()

    try:
        with urlopen(
            request,
            timeout=timeout_seconds,
        ) as response:
            return FetchResult(
                body=response.read().decode("utf-8", errors="replace"),
                status_code=response.status,
                headers={key.lower(): value for key, value in response.headers.items()},
                fetched_at=fetched_at,
            )
    except HTTPError as exc:
        message = f"Official model API request failed: HTTP {exc.code}"
        _raise_os_error(message, exc)


def normalize_official_models(api_payload: str) -> list[dict[str, object]]:
    """Validate the public API envelope and project it into canonical field names."""
    try:
        parsed: object = json.loads(api_payload)
    except json.JSONDecodeError as exc:
        _raise_extraction_error("Official model API returned invalid JSON.", exc)
    if not isinstance(parsed, dict):
        _raise_extraction_error("Official model API envelope must be an object.")

    status = parsed.get("status")
    prompt_options = parsed.get("prompt_options")
    rows = parsed.get("data")
    if (
        not isinstance(status, int)
        or not isinstance(prompt_options, dict)
        or not isinstance(rows, list)
    ):
        _raise_extraction_error(
            "Official model API envelope requires integer status, object "
            "prompt_options, and list data.",
        )

    return [_normalize_official_model(row) for row in rows]


def _normalize_official_model(row: object) -> dict[str, object]:
    if not isinstance(row, dict):
        _raise_extraction_error("Official model API data rows must be objects.")

    slug = row.get("slug")
    name = row.get("name")
    creator = row.get("model_creator")
    evaluations = row.get("evaluations")
    pricing = row.get("pricing")
    if (
        not isinstance(slug, str)
        or not slug
        or not isinstance(name, str)
        or not name
        or not isinstance(creator, dict)
        or not isinstance(evaluations, dict)
        or not isinstance(pricing, dict)
    ):
        _raise_extraction_error(
            "Official model API rows require non-empty slug/name and object "
            "model_creator/evaluations/pricing.",
        )

    normalized_evaluations = {
        _OFFICIAL_EVALUATION_NAMES.get(key, key): value
        for key, value in evaluations.items()
        if isinstance(key, str)
    }
    return {
        "id": row.get("id"),
        "slug": slug,
        "name": name,
        "release_date": row.get("release_date"),
        "creator": _normalize_camel_keys(creator),
        "evaluations": normalized_evaluations,
        "pricing": _normalize_camel_keys(pricing),
        "median_output_tokens_per_second": row.get("median_output_tokens_per_second"),
        "median_time_to_first_token_seconds": row.get(
            "median_time_to_first_token_seconds",
        ),
        "median_time_to_first_answer_token": row.get(
            "median_time_to_first_answer_token",
        ),
    }


_OFFICIAL_EVALUATION_NAMES = {
    "artificial_analysis_intelligence_index": "intelligence_index",
    "artificial_analysis_coding_index": "coding_index",
    "artificial_analysis_math_index": "math_index",
    "terminalbench_v2_1": "terminalbench_v21",
    "tau2": "tau_2",
}


def parse_json_frames(rsc_payload: str) -> list[tuple[str, Any]]:
    """Parse JSON-bearing React Server Component frames."""
    parsed_frames: list[tuple[str, Any]] = []
    for line in rsc_payload.splitlines():
        if ":" not in line:
            continue
        frame_id, payload = line.split(":", 1)
        if not payload or payload[0] not in ("[", "{", '"'):
            continue
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            continue
        parsed_frames.append((frame_id, parsed))
    return parsed_frames


def _add_candidate(
    candidates: dict[str, list[list[Any]]],
    kind: str,
    value: list[Any],
) -> None:
    if value:
        candidates[kind].append(value)


def _record_list_candidates(
    key: str,
    value: list[Any],
    candidates: dict[str, list[list[Any]]],
    alias_map: dict[str, tuple[str, ...]],
) -> None:
    normalized = key.replace("-", "_").lower()
    for kind in ("models", "hosts", "hostsModels"):
        if normalized in alias_map[kind]:
            _add_candidate(candidates, kind, value)

    # Structural fallback heuristics for breaking schema changes.
    if normalized == "rows" and _looks_like_current_endpoint_rows(value):
        _add_candidate(candidates, "rows", value)
    if _looks_like_endpoint_list(value):
        _add_candidate(candidates, "hostsModels", value)
    if _looks_like_host_list(value):
        _add_candidate(candidates, "hosts", value)
    if _looks_like_model_list(value):
        _add_candidate(candidates, "models", value)


def _scan_node(
    node: object,
    candidates: dict[str, list[list[Any]]],
    alias_map: dict[str, tuple[str, ...]],
) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(value, list) and isinstance(key, str):
                _record_list_candidates(key, value, candidates, alias_map)
            _scan_node(value, candidates, alias_map)
    elif isinstance(node, list):
        for item in node:
            _scan_node(item, candidates, alias_map)


def extract_lists(
    parsed_frames: list[tuple[str, Any]],
) -> tuple[list[Any], list[Any], list[Any]]:
    """Extract model, host, and endpoint lists from parsed frames."""
    candidates: dict[str, list[list[Any]]] = {
        "models": [],
        "hosts": [],
        "hostsModels": [],
        "rows": [],
    }
    alias_map: dict[str, tuple[str, ...]] = {
        "models": ("models", "model_rows", "modelrows"),
        "hosts": ("hosts", "providers", "provider_rows", "host_rows"),
        "hostsModels": ("hostsmodels", "host_models", "endpoints", "hostmodels"),
    }

    for _, frame in parsed_frames:
        _scan_node(frame, candidates, alias_map)

    selected = {
        key: _pick_best(candidates[key]) for key in ("models", "hosts", "hostsModels")
    }
    if selected["hostsModels"] is None:
        selected["hostsModels"] = _normalize_current_rows(
            _pick_best(candidates["rows"]),
        )

    missing = [key for key, value in selected.items() if value is None]
    if missing:
        diagnostics = {
            key: [len(value) for value in values[:5]]
            for key, values in candidates.items()
            if values
        }
        message = (
            f"Missing sections in RSC payload: {', '.join(missing)}; "
            f"candidate_sizes={diagnostics}"
        )
        _raise_extraction_error(message)

    return (
        selected["models"] or [],
        selected["hosts"] or [],
        selected["hostsModels"] or [],
    )


def _normalize_current_rows(rows: list[Any] | None) -> list[dict[str, Any]] | None:
    if rows is None:
        return None

    endpoints = [
        endpoint
        for row in rows
        if (endpoint := _normalize_current_row(row)) is not None
    ]
    if not endpoints:
        return None
    return endpoints


def _normalize_current_row(row: object) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None

    host = row.get("host")
    model = row.get("model")
    if not isinstance(host, dict) or not isinstance(model, dict):
        return None

    host_slug = host.get("slug")
    model_slug = model.get("slug")
    if not isinstance(host_slug, str) or not host_slug:
        return None
    if not isinstance(model_slug, str) or not model_slug:
        return None

    normalized_host = _normalize_camel_keys(host)
    normalized_model = _normalize_camel_keys(model)
    normalized_features = _normalize_camel_keys(row.get("features"))
    normalized_pricing = _normalize_camel_keys(row.get("pricing"))
    performance = row.get("performance")
    if not isinstance(performance, dict):
        performance = {}

    endpoint: dict[str, Any] = {
        "slug": f"{host_slug}_{model_slug}",
        "name": row.get("label"),
        "host_api_id": row.get("hostApiId"),
        "host": normalized_host,
        "model": normalized_model,
        "timescaleData": {
            "median_output_speed": performance.get("medianOutputTokensPerSecond"),
            "median_time_to_first_chunk": performance.get(
                "medianTimeToFirstTokenSeconds",
            ),
        },
        "end_to_end_response_time_metrics": {
            "total_time": performance.get("medianEndToEndResponseTimeSeconds"),
        },
    }

    if isinstance(normalized_features, dict):
        endpoint.update(normalized_features)
    if isinstance(normalized_pricing, dict):
        endpoint.update(normalized_pricing)

    return endpoint


def _normalize_camel_keys(value: object) -> object:
    if isinstance(value, dict):
        return {
            _camel_to_snake(key): _normalize_camel_keys(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_normalize_camel_keys(item) for item in value]
    return value


def _camel_to_snake(value: object) -> object:
    if not isinstance(value, str):
        return value

    result: list[str] = []
    previous_lower = False
    previous_lower_or_digit = False
    for char in value.replace("-", "_"):
        if char.isupper():
            if previous_lower_or_digit:
                result.append("_")
            result.append(char.lower())
            previous_lower = False
            previous_lower_or_digit = False
            continue
        if char.isdigit() and previous_lower:
            result.append("_")
        result.append(char)
        previous_lower = char.islower()
        previous_lower_or_digit = previous_lower or char.isdigit()
    return "".join(result)


def _looks_like_current_endpoint_rows(value: list[Any]) -> bool:
    sample = [item for item in value[:25] if isinstance(item, dict)]
    if not sample:
        return False

    hits = 0
    for item in sample:
        host = item.get("host")
        model = item.get("model")
        if (
            isinstance(host.get("slug"), str)
            and isinstance(model.get("slug"), str)
            and any(key in item for key in ("features", "pricing", "performance"))
        ):
            hits += 1
    return hits >= max(1, len(sample) // 2)


def _pick_best(options: list[list[Any]]) -> list[Any] | None:
    if not options:
        return None
    # Prefer largest candidate: most likely the complete table.
    return max(options, key=len)


def _looks_like_endpoint_list(value: list[Any]) -> bool:
    sample = [item for item in value[:25] if isinstance(item, dict)]
    if len(sample) < MIN_SAMPLE_SIZE:
        return False

    score = 0
    for item in sample:
        slug = item.get("slug")
        if isinstance(slug, str) and "_" in slug:
            score += 1
        if "host_id" in item:
            score += 1
        if "model_id" in item:
            score += 1
    return score >= len(sample) * 2


def _looks_like_host_list(value: list[Any]) -> bool:
    sample = [item for item in value[:20] if isinstance(item, dict)]
    if len(sample) < MIN_SAMPLE_SIZE:
        return False

    hit = 0
    for item in sample:
        if (
            isinstance(item.get("slug"), str)
            and isinstance(item.get("name"), str)
            and any(
                k in item
                for k in ("website_url", "openai_compatible", "logo", "host_url")
            )
        ):
            hit += 1
    return hit >= max(MIN_SAMPLE_SIZE, len(sample) // 2)


def _looks_like_model_list(value: list[Any]) -> bool:
    sample = [item for item in value[:20] if isinstance(item, dict)]
    if len(sample) < MIN_SAMPLE_SIZE:
        return False

    hit = 0
    for item in sample:
        if (
            isinstance(item.get("slug"), str)
            and isinstance(item.get("name"), str)
            and any(
                k in item
                for k in ("intelligence_index", "model_creator_id", "reasoning_model")
            )
        ):
            hit += 1
    return hit >= max(MIN_SAMPLE_SIZE, len(sample) // 2)


def endpoint_slugs(hosts_models: list[Any]) -> list[str]:
    """Return sorted endpoint slugs from provider/model rows."""
    slugs = {
        item["slug"]
        for item in hosts_models
        if isinstance(item, dict)
        and isinstance(item.get("slug"), str)
        and "_" in item["slug"]
        and not _is_non_endpoint_slug(item["slug"])
    }
    return sorted(slugs)


def provider_from_slug(slug: str) -> str:
    """Extract the provider slug prefix from an endpoint slug."""
    return slug.split("_", 1)[0]


def _is_non_endpoint_slug(slug: str) -> bool:
    _, _, suffix = slug.partition("_")
    if not suffix:
        return True
    if any(ch.isdigit() for ch in suffix):
        return False
    return "-" not in suffix


def build_full_url(slugs: list[str]) -> str:
    """Build a shareable Artificial Analysis URL for endpoint slugs."""
    joined = ",".join(slugs)
    encoded = quote(joined, safe="_-")
    return f"https://artificialanalysis.ai/?models=&endpoints={encoded}"


def build_snapshot_payload(  # noqa: PLR0913
    *,
    models: list[Any],
    hosts: list[Any],
    hosts_models: list[Any],
    frame_count: int,
    rsc_result: FetchResult,
    rsc_etag: str | None,
    rsc_reused_cached_payload: bool,
    official_result: FetchResult,
    official_models: list[dict[str, object]],
) -> dict[str, Any]:
    """Merge source rows into the persisted schema-v2 snapshot."""
    slim_endpoints = _slim_endpoints(hosts_models)
    canonical_models, unmatched_rsc, unmatched_api = _merge_canonical_models(
        rsc_models=models,
        rsc_endpoints=hosts_models,
        official_models=official_models,
    )
    slugs = endpoint_slugs(slim_endpoints)
    providers_by_prefix = sorted({provider_from_slug(slug) for slug in slugs})
    providers_by_host = sorted(_provider_slugs_from_hosts_models(slim_endpoints))
    api_url = os.environ.get(MODEL_API_BASE_URL_ENV) or MODEL_API_URL

    return {
        "meta": {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "fetched_at": rsc_result.fetched_at,
            "sources": {
                "rsc": {
                    "url": BASE_URL,
                    "status_code": rsc_result.status_code,
                    "fetched_at": rsc_result.fetched_at,
                    "etag": rsc_etag,
                    "reused_cached_payload": rsc_reused_cached_payload,
                    "unmatched_api_model_slugs": unmatched_api,
                },
                "official_api": {
                    "url": api_url,
                    "status_code": official_result.status_code,
                    "fetched_at": official_result.fetched_at,
                    "etag": official_result.headers.get("etag"),
                    "reused_cached_payload": False,
                    "unmatched_rsc_model_slugs": unmatched_rsc,
                },
            },
            "counts": {
                "models": len(canonical_models),
                "hosts": len(hosts),
                "hosts_models": len(slim_endpoints),
                "endpoint_slugs": len(slugs),
                "providers_by_prefix": len(providers_by_prefix),
                "providers": len(providers_by_host),
                "frames": frame_count,
            },
        },
        "models": canonical_models,
        "hosts": hosts,
        "hosts_models": slim_endpoints,
    }


def _slim_endpoints(hosts_models: list[Any]) -> list[dict[str, Any]]:
    endpoints: list[dict[str, Any]] = []
    for endpoint in hosts_models:
        if not isinstance(endpoint, dict):
            continue
        model = endpoint.get("model")
        model_slug = (
            model.get("slug")
            if isinstance(model, dict) and isinstance(model.get("slug"), str)
            else endpoint.get("model_slug")
        )
        if not isinstance(model_slug, str) or not model_slug:
            continue
        slim = {key: value for key, value in endpoint.items() if key != "model"}
        slim["model_slug"] = model_slug
        endpoints.append(slim)
    return endpoints


def _merge_canonical_models(
    *,
    rsc_models: list[Any],
    rsc_endpoints: list[Any],
    official_models: list[dict[str, object]],
) -> tuple[list[dict[str, object]], list[str], list[str]]:
    rsc_by_slug = _rsc_models_by_slug(rsc_models, rsc_endpoints)
    official_by_slug = {
        model["slug"]: model
        for model in official_models
        if isinstance(model.get("slug"), str)
    }
    all_slugs = sorted(set(rsc_by_slug) | set(official_by_slug))
    merged = [
        _merge_canonical_model(
            rsc_by_slug.get(slug),
            official_by_slug.get(slug),
        )
        for slug in all_slugs
    ]
    return (
        merged,
        sorted(set(rsc_by_slug) - set(official_by_slug)),
        sorted(set(official_by_slug) - set(rsc_by_slug)),
    )


def _rsc_models_by_slug(
    rsc_models: list[Any],
    rsc_endpoints: list[Any],
) -> dict[str, dict[str, object]]:
    values: dict[str, dict[str, object]] = {}
    for candidate in [
        *rsc_models,
        *(item.get("model") for item in rsc_endpoints if isinstance(item, dict)),
    ]:
        if not isinstance(candidate, dict):
            continue
        slug = candidate.get("slug")
        if isinstance(slug, str) and slug:
            values[slug] = dict(candidate) | values.get(slug, {})
    return values


def _merge_canonical_model(
    rsc_model: dict[str, object] | None,
    official_model: dict[str, object] | None,
) -> dict[str, object]:
    merged = dict(rsc_model or {})
    if official_model is None:
        if "creator" not in merged and isinstance(merged.get("model_creators"), dict):
            merged["creator"] = merged["model_creators"]
        return merged

    for key in (
        "id",
        "slug",
        "name",
        "release_date",
        "creator",
        "pricing",
        "median_output_tokens_per_second",
        "median_time_to_first_token_seconds",
        "median_time_to_first_answer_token",
    ):
        merged[key] = official_model[key]
    evaluations = official_model["evaluations"]
    if isinstance(evaluations, dict):
        merged.update(
            {name: value for name, value in evaluations.items() if value is not None}
        )
    return merged


def _provider_slugs_from_hosts_models(hosts_models: list[Any]) -> set[str]:
    values: set[str] = set()
    for item in hosts_models:
        if not isinstance(item, dict):
            continue
        host = item.get("host")
        if isinstance(host, dict) and isinstance(host.get("slug"), str):
            values.add(host["slug"])
            continue
        slug = item.get("slug")
        if isinstance(slug, str) and "_" in slug:
            values.add(provider_from_slug(slug))
    return values


def sanity_check(
    *,
    slugs: list[str],
    min_endpoints: int,
    min_providers: int,
) -> None:
    """Validate endpoint and provider counts against configured thresholds."""
    provider_count = len({provider_from_slug(slug) for slug in slugs})
    if len(slugs) < min_endpoints:
        message = (
            f"Too few endpoints extracted ({len(slugs)} < {min_endpoints}). "
            "Payload format likely changed."
        )
        _raise_extraction_error(message)
    if provider_count < min_providers:
        message = (
            f"Too few providers extracted ({provider_count} < {min_providers}). "
            "Payload format likely changed."
        )
        _raise_extraction_error(message)


def write_outputs(  # noqa: PLR0913
    *,
    output_json: Path,
    output_endpoints: Path,
    output_url: Path,
    payload: dict[str, Any],
    slugs: list[str],
    full_url: str,
) -> None:
    """Write the snapshot and its endpoint/url companion files."""
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_endpoints.parent.mkdir(parents=True, exist_ok=True)
    output_url.parent.mkdir(parents=True, exist_ok=True)

    output_json.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    output_endpoints.write_text("\n".join(slugs) + "\n", encoding="utf-8")
    output_url.write_text(full_url + "\n", encoding="utf-8")


def load_snapshot(path: Path) -> dict[str, Any]:
    """Load and validate a JSON snapshot object."""
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        _raise_extraction_error(f"Cannot read snapshot: {path}", exc)
    except json.JSONDecodeError as exc:
        _raise_extraction_error(f"Invalid JSON snapshot: {path}", exc)

    if not isinstance(parsed, dict):
        _raise_extraction_error(f"Snapshot root must be an object: {path}")
    return parsed


def snapshot_slugs(snapshot: dict[str, Any]) -> list[str]:
    """Return endpoint slugs from any supported snapshot key."""
    for key in ("hosts_models", "hostsModels", "host_models", "endpoints"):
        value = snapshot.get(key)
        if isinstance(value, list):
            return endpoint_slugs(value)
    _raise_extraction_error("Snapshot missing hosts_models-compatible list")


def load_cache_metadata(cache_dir: Path) -> CacheMetadata | None:
    """Read cache metadata, returning None for absent or malformed files."""
    meta_path = cache_dir / CACHE_META_FILE
    if not meta_path.exists():
        return None
    try:
        parsed = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, dict):
        return None
    etag = parsed.get("etag")
    fetched_at = parsed.get("fetched_at")
    status_code = parsed.get("status_code")
    body_file = parsed.get("body_file")
    if not isinstance(body_file, str) or not body_file:
        body_file = CACHE_BODY_FILE
    return CacheMetadata(
        etag=etag if isinstance(etag, str) else None,
        fetched_at=fetched_at if isinstance(fetched_at, str) else None,
        status_code=status_code if isinstance(status_code, int) else None,
        body_file=body_file,
    )


def load_cached_body(cache_dir: Path, metadata: CacheMetadata | None) -> str | None:
    """Read a cached provider response body if available."""
    body_file = metadata.body_file if metadata is not None else CACHE_BODY_FILE
    body_path = cache_dir / body_file
    try:
        if not body_path.exists():
            return None
        return body_path.read_text(encoding="utf-8")
    except OSError:
        return None


def save_cache(
    *,
    cache_dir: Path,
    fetched_at: str,
    status_code: int,
    etag: str | None,
    body: str | None,
) -> None:
    """Persist provider response metadata and body in the cache directory."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    if body is not None:
        (cache_dir / CACHE_BODY_FILE).write_text(body, encoding="utf-8")
    meta = {
        "etag": etag,
        "fetched_at": fetched_at,
        "status_code": status_code,
        "body_file": CACHE_BODY_FILE,
    }
    (cache_dir / CACHE_META_FILE).write_text(
        json.dumps(meta, ensure_ascii=False),
        encoding="utf-8",
    )


def save_last_good_snapshot(cache_dir: Path, payload: dict[str, Any]) -> Path:
    """Persist a last-good snapshot for fetch fallback."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / CACHE_LAST_GOOD_FILE
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def load_last_good_snapshot(cache_dir: Path) -> dict[str, Any] | None:
    """Load a last-good snapshot, returning None when unavailable."""
    path = cache_dir / CACHE_LAST_GOOD_FILE
    if not path.exists():
        return None
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None
