# ruff: noqa: S310
"""Fetch, normalize, and persist Artificial Analysis data snapshots."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import tempfile
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .diagnostics import Diagnostic, redact, redact_query
from .identity import (
    canonical_endpoint_identity,
    canonical_model_identity,
    classify_duplicate_rows,
    normalize_mapping,
)
from .identity import (
    source_hash as calculate_source_hash,
)
from .provenance import (
    ArtifactError,
    ArtifactNotFoundError,
    ArtifactStore,
)

if TYPE_CHECKING:
    from http.client import HTTPResponse
    from typing import NoReturn

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
MIN_NEXT_PUSH_ITEMS = 2
DEFAULT_MIN_EVALUATION_ROWS = 1
RSC_SOURCE_KEY = BASE_URL


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


class CacheError(ExtractionError):
    """Structured failure while validating a conditional cache response."""

    code: str
    details: dict[str, object]

    def __init__(
        self,
        code: str,
        message: str,
        details: dict[str, object] | None = None,
    ) -> None:
        """Initialize a structured cache failure."""
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})


def _safe_headers(headers: object) -> dict[str, str]:
    if headers is None:
        return {}
    items = getattr(headers, "items", None)
    if not callable(items):
        return {}
    result: dict[str, str] = {}
    items_fn = cast("Callable[[], Iterable[tuple[object, object]]]", items)
    for key, value in items_fn():
        name = str(key).casefold()
        if name in {"authorization", "cookie", "set-cookie", "x-api-key", "api-key"}:
            continue
        result[name] = str(redact(str(value)))
    return result


def _response_status(response: object, default: int = 200) -> int:
    status = getattr(response, "status", None)
    if isinstance(status, int):
        return status
    getter = getattr(response, "getcode", None)
    value = getter() if callable(getter) else default
    return value if isinstance(value, int) else default


def _response_final_url(response: object, requested: str) -> str:
    getter = getattr(response, "geturl", None)
    value = getter() if callable(getter) else requested
    return value if isinstance(value, str) and value else requested


@dataclass(frozen=True)
class FetchResult:
    """HTTP response data captured while fetching a source."""

    body: str
    status_code: int
    headers: dict[str, str]
    fetched_at: str
    final_url: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    sha256: str | None = None
    byte_length: int | None = None
    artifact_ref: str | None = None


@dataclass(frozen=True)
class CacheMetadata:
    """Metadata describing the cached provider response."""

    etag: str | None
    fetched_at: str | None
    status_code: int | None
    body_file: str
    last_modified: str | None = None
    source_key: str | None = None
    source_url: str | None = None
    final_url: str | None = None
    sha256: str | None = None
    byte_length: int | None = None
    artifact_ref: str | None = None
    legacy_unverified: bool = False


def fetch_rsc(
    url: str = BASE_URL,
    *,
    timeout_seconds: float = 60.0,
    if_none_match: str | None = None,
    if_modified_since: str | None = None,
) -> FetchResult:
    """Fetch the provider endpoint payload using the RSC request protocol."""
    request_headers = {
        "RSC": "1",
        "Accept": "text/x-component, */*;q=0.8",
        "User-Agent": "artificial-analysis/0.3",
    }
    if if_none_match:
        request_headers["If-None-Match"] = if_none_match
    if if_modified_since:
        request_headers["If-Modified-Since"] = if_modified_since

    request = Request(url, headers=request_headers)
    fetched_at = datetime.now(UTC).isoformat()

    try:
        raw_resp = cast("object", urlopen(request, timeout=timeout_seconds))
        with cast("HTTPResponse", raw_resp) as response:
            status_code = _response_status(response)
            headers = _safe_headers(getattr(response, "headers", None))
            final_url = _response_final_url(response, url)
            raw = response.read()
            body = raw.decode("utf-8", errors="replace")
            raw_bytes = body.encode("utf-8")
            return FetchResult(
                body=body,
                status_code=status_code,
                headers=headers,
                fetched_at=fetched_at,
                final_url=final_url,
                etag=headers.get("etag"),
                last_modified=headers.get("last-modified"),
                sha256=hashlib.sha256(raw_bytes).hexdigest() if body else None,
                byte_length=len(raw_bytes) if body else None,
            )
    except HTTPError as exc:
        if exc.code == NOT_MODIFIED:
            headers = _safe_headers(exc.headers)
            final_url = _response_final_url(exc, url)
            return FetchResult(
                body="",
                status_code=NOT_MODIFIED,
                headers=headers,
                fetched_at=fetched_at,
                final_url=final_url,
                etag=headers.get("etag"),
                last_modified=headers.get("last-modified"),
            )
        message = f"Upstream request failed: HTTP {exc.code}"
        _raise_os_error(message, exc)


def fetch_page(
    url: str,
    *,
    timeout_seconds: float = 60.0,
    if_none_match: str | None = None,
    if_modified_since: str | None = None,
) -> FetchResult:
    """Fetch a public Artificial Analysis page containing embedded RSC data."""
    request_headers = {
        "Accept": "text/html,application/xhtml+xml",
        "User-Agent": "artificial-analysis/0.3",
    }
    if if_none_match:
        request_headers["If-None-Match"] = if_none_match
    if if_modified_since:
        request_headers["If-Modified-Since"] = if_modified_since
    request = Request(url, headers=request_headers)
    fetched_at = datetime.now(UTC).isoformat()

    try:
        raw_resp = cast("object", urlopen(request, timeout=timeout_seconds))
        with cast("HTTPResponse", raw_resp) as response:
            status_code = _response_status(response)
            headers = _safe_headers(getattr(response, "headers", None))
            final_url = _response_final_url(response, url)
            raw = response.read()
            body = raw.decode("utf-8", errors="replace")
            raw_bytes = body.encode("utf-8")
            return FetchResult(
                body=body,
                status_code=status_code,
                headers=headers,
                fetched_at=fetched_at,
                final_url=final_url,
                etag=headers.get("etag"),
                last_modified=headers.get("last-modified"),
                sha256=hashlib.sha256(raw_bytes).hexdigest() if body else None,
                byte_length=len(raw_bytes) if body else None,
            )
    except HTTPError as exc:
        if exc.code == NOT_MODIFIED:
            headers = _safe_headers(exc.headers)
            return FetchResult(
                body="",
                status_code=NOT_MODIFIED,
                headers=headers,
                fetched_at=fetched_at,
                final_url=_response_final_url(exc, url),
                etag=headers.get("etag"),
                last_modified=headers.get("last-modified"),
            )
        message = f"Upstream page request failed: HTTP {exc.code}"
        _raise_os_error(message, exc)


def fetch_models(
    api_key: str,
    *,
    timeout_seconds: float = 60.0,
    url: str | None = None,
    if_none_match: str | None = None,
    if_modified_since: str | None = None,
) -> FetchResult:
    """Fetch the authenticated canonical-model source without retaining credentials."""
    request_url = url or os.environ.get(MODEL_API_BASE_URL_ENV) or MODEL_API_URL
    request_headers = {
        "Accept": "application/json",
        "User-Agent": "artificial-analysis/0.3",
        "x-api-key": api_key,
    }
    if if_none_match:
        request_headers["If-None-Match"] = if_none_match
    if if_modified_since:
        request_headers["If-Modified-Since"] = if_modified_since
    request = Request(request_url, headers=request_headers)
    fetched_at = datetime.now(UTC).isoformat()

    try:
        raw_resp = cast("object", urlopen(request, timeout=timeout_seconds))
        with cast("HTTPResponse", raw_resp) as response:
            status_code = _response_status(response)
            headers = _safe_headers(getattr(response, "headers", None))
            final_url = _response_final_url(response, request_url)
            raw = response.read()
            body = raw.decode("utf-8", errors="replace")
            raw_bytes = body.encode("utf-8")
            return FetchResult(
                body=body,
                status_code=status_code,
                headers=headers,
                fetched_at=fetched_at,
                final_url=final_url,
                etag=headers.get("etag"),
                last_modified=headers.get("last-modified"),
                sha256=hashlib.sha256(raw_bytes).hexdigest() if body else None,
                byte_length=len(raw_bytes) if body else None,
            )
    except HTTPError as exc:
        if exc.code == NOT_MODIFIED:
            headers = _safe_headers(exc.headers)
            return FetchResult(
                body="",
                status_code=NOT_MODIFIED,
                headers=headers,
                fetched_at=fetched_at,
                final_url=_response_final_url(exc, request_url),
                etag=headers.get("etag"),
                last_modified=headers.get("last-modified"),
            )
        message = f"Official model API request failed: HTTP {exc.code}"
        _raise_os_error(message, exc)


def normalize_official_models(
    api_payload: str,
    *,
    source_path: str | None = None,
    source_hash: str | None = None,
    parser: str = "official-api-v2",
    diagnostics: list[Diagnostic] | None = None,
) -> list[dict[str, object]]:
    """Validate and project official models without losing source fields."""
    try:
        parsed = cast("object", json.loads(api_payload))
    except json.JSONDecodeError as exc:
        _raise_extraction_error("Official model API returned invalid JSON.", exc)
    if not isinstance(parsed, dict):
        _raise_extraction_error("Official model API envelope must be an object.")
    parsed_dict = cast("dict[str, object]", parsed)

    status = parsed_dict.get("status")
    prompt_options = parsed_dict.get("prompt_options")
    rows_raw = parsed_dict.get("data")
    if (
        not isinstance(status, int)
        or not isinstance(prompt_options, dict)
        or not isinstance(rows_raw, list)
    ):
        msg = (
            "Official model API envelope requires integer status, object "
            + "prompt_options, and list data."
        )
        _raise_extraction_error(msg)

    rows = cast("list[object]", rows_raw)
    effective_hash = source_hash or calculate_source_hash(api_payload)
    collected = diagnostics if diagnostics is not None else []
    result = [
        _normalize_official_model(
            row,
            source_path=(
                f"{source_path}.data[{index}]" if source_path else f"data[{index}]"
            ),
            source_hash=effective_hash,
            parser=parser,
            diagnostics=collected,
        )
        for index, row in enumerate(rows)
    ]
    selected = _deduplicate_models(
        result,
        source_path=source_path,
        diagnostics=collected,
    )
    _attach_row_diagnostics(selected, collected)
    return selected


_OFFICIAL_MODEL_FIELDS = frozenset(
    {
        "id",
        "slug",
        "name",
        "release_date",
        "model_creator",
        "evaluations",
        "pricing",
        "median_output_tokens_per_second",
        "median_time_to_first_token_seconds",
        "median_time_to_first_answer_token",
    },
)
_MODEL_CREATOR_FIELDS = frozenset({"id", "name", "slug"})
_MODEL_PRICING_FIELDS = frozenset(
    {
        "price_1m_blended_3_to_1",
        "price_1m_input",
        "price_1m_output",
        "price_1m_cached_input",
        "price_1m_cache_read",
    },
)


def _raw_metadata(
    *,
    source_path: str | None,
    source_hash: str | None,
    parser: str | None,
    diagnostics: list[Diagnostic] | None = None,
) -> dict[str, object]:
    metadata: dict[str, object] = {}
    if source_path:
        metadata["source_path"] = source_path
    if source_hash:
        metadata["source_hash"] = source_hash
    if parser:
        metadata["parser"] = parser
    if diagnostics:
        metadata["diagnostics"] = [item.to_dict() for item in diagnostics]
    return metadata


def _normalize_nested_source(  # noqa: PLR0913
    value: object,
    *,
    known_fields: frozenset[str] | None,
    path: str,
    source_path: str | None,
    source_hash: str | None,
    parser: str,
    diagnostics: list[Diagnostic] | None,
) -> object:
    if not isinstance(value, dict):
        return value
    dict_val = cast("dict[str, object]", value)
    return normalize_mapping(
        cast("Mapping[object, object]", dict_val),
        known_fields=known_fields,
        path=path,
        source_path=source_path,
        source_hash=source_hash,
        parser=parser,
        diagnostics=diagnostics,
    )


def _normalize_official_model(
    row: object,
    *,
    source_path: str | None = None,
    source_hash: str | None = None,
    parser: str = "official-api-v2",
    diagnostics: list[Diagnostic] | None = None,
) -> dict[str, object]:
    if not isinstance(row, dict):
        _raise_extraction_error("Official model API data rows must be objects.")
    row_dict = cast("dict[str, object]", row)

    slug = row_dict.get("slug")
    name = row_dict.get("name")
    creator = row_dict.get("model_creator")
    evaluations = row_dict.get("evaluations")
    pricing = row_dict.get("pricing")
    if (
        not isinstance(slug, str)
        or not slug
        or not isinstance(name, str)
        or not name
        or not isinstance(creator, dict)
        or not isinstance(evaluations, dict)
        or not isinstance(pricing, dict)
    ):
        msg = (
            "Official model API rows require non-empty slug/name and object "
            + "model_creator/evaluations/pricing."
        )
        _raise_extraction_error(msg)

    creator_dict = cast("dict[str, object]", creator)
    evaluations_dict = cast("dict[str, object]", evaluations)
    pricing_dict = cast("dict[str, object]", pricing)

    source = normalize_mapping(
        cast("Mapping[object, object]", row_dict),
        known_fields=_OFFICIAL_MODEL_FIELDS,
        path=source_path or "data",
        source_path=source_path,
        source_hash=source_hash,
        parser=parser,
        diagnostics=diagnostics,
    )
    normalized_creator = _normalize_nested_source(
        creator_dict,
        known_fields=_MODEL_CREATOR_FIELDS,
        path=f"{source_path}.model_creator" if source_path else "model_creator",
        source_path=source_path,
        source_hash=source_hash,
        parser=parser,
        diagnostics=diagnostics,
    )
    normalized_pricing = _normalize_nested_source(
        pricing_dict,
        known_fields=_MODEL_PRICING_FIELDS,
        path=f"{source_path}.pricing" if source_path else "pricing",
        source_path=source_path,
        source_hash=source_hash,
        parser=parser,
        diagnostics=diagnostics,
    )
    normalized_evaluations = normalize_mapping(
        cast("Mapping[object, object]", evaluations_dict),
        known_fields=frozenset(_OFFICIAL_EVALUATION_NAMES)
        | {"coding_index", "intelligence_index", "math_index", "tau_2"},
        path=f"{source_path}.evaluations" if source_path else "evaluations",
        source_path=source_path,
        source_hash=source_hash,
        parser=parser,
        diagnostics=diagnostics,
    )
    result: dict[str, object] = {
        "id": source.get("id"),
        "slug": slug,
        "name": name,
        "release_date": source.get("release_date"),
        "creator": normalized_creator,
        "evaluations": {
            _OFFICIAL_EVALUATION_NAMES.get(key, key): value
            for key, value in normalized_evaluations.items()
            if key not in {"raw_fields", "raw_metadata"}
        },
        "pricing": normalized_pricing,
        "median_output_tokens_per_second": source.get(
            "median_output_tokens_per_second",
        ),
        "median_time_to_first_token_seconds": source.get(
            "median_time_to_first_token_seconds",
        ),
        "median_time_to_first_answer_token": source.get(
            "median_time_to_first_answer_token",
        ),
        "identity": canonical_model_identity(
            slug,
            source_path=source_path,
            source_hash=source_hash,
        ),
    }
    raw_fields: dict[str, object] = {}
    source_raw_fields = source.get("raw_fields")
    if isinstance(source_raw_fields, dict):
        raw_fields.update(cast("dict[str, object]", source_raw_fields))
    creator_raw = (
        cast("dict[str, object]", normalized_creator).get("raw_fields")
        if isinstance(normalized_creator, dict)
        else None
    )
    pricing_raw = (
        cast("dict[str, object]", normalized_pricing).get("raw_fields")
        if isinstance(normalized_pricing, dict)
        else None
    )
    evaluations_raw = normalized_evaluations.get("raw_fields")
    if isinstance(creator_raw, dict) and creator_raw:
        raw_fields["model_creator"] = cast("dict[str, object]", creator_raw)
    if isinstance(pricing_raw, dict) and pricing_raw:
        raw_fields["pricing"] = cast("dict[str, object]", pricing_raw)
    if isinstance(evaluations_raw, dict) and evaluations_raw:
        raw_fields["evaluations"] = cast("dict[str, object]", evaluations_raw)
    if raw_fields:
        result["raw_fields"] = raw_fields
    metadata = _raw_metadata(
        source_path=source_path,
        source_hash=source_hash,
        parser=parser,
    )
    if metadata:
        result["raw_metadata"] = metadata
    return result


_OFFICIAL_EVALUATION_NAMES = {
    "artificial_analysis_intelligence_index": "intelligence_index",
    "artificial_analysis_coding_index": "coding_index",
    "artificial_analysis_math_index": "math_index",
    "terminalbench_v2_1": "terminalbench_v21",
    "tau2": "tau_2",
}


def _deduplicate_models(
    rows: list[dict[str, object]],
    *,
    source_path: str | None,
    diagnostics: list[Diagnostic] | None,
) -> list[dict[str, object]]:
    def key(row: object) -> str | None:
        if isinstance(row, dict):
            val = cast("dict[str, object]", row).get("slug")
            return val if isinstance(val, str) else None
        return None

    return [
        row
        for row in classify_duplicate_rows(
            rows,
            identity=key,
            source_path=source_path,
            diagnostics=diagnostics,
        )
        if isinstance(row, dict)
    ]


def parse_json_frames(rsc_payload: str) -> list[tuple[str, object]]:
    """Parse JSON-bearing React Server Component frames."""
    parsed_frames: list[tuple[str, object]] = []
    for line in rsc_payload.splitlines():
        if ":" not in line:
            continue
        frame_id, payload = line.split(":", 1)
        if not payload or payload[0] not in ("[", "{", '"'):
            continue
        try:
            parsed = cast("object", json.loads(payload))
        except json.JSONDecodeError:
            continue
        parsed_frames.append((frame_id, parsed))
    return parsed_frames


def parse_next_payload(document: str) -> list[tuple[str, object]]:
    """Extract embedded Next.js Flight pushes and parse their RSC frames."""
    marker = "self.__next_f.push("
    decoder = json.JSONDecoder()
    frames: list[tuple[str, object]] = []
    cursor = 0
    while True:
        marker_start = document.find(marker, cursor)
        if marker_start < 0:
            break
        payload_start = marker_start + len(marker)
        try:
            payload_raw, cursor = cast(
                "tuple[object, int]",
                decoder.raw_decode(document, payload_start),
            )
        except json.JSONDecodeError:
            cursor = payload_start
            continue
        payload = payload_raw
        if (
            not isinstance(payload, list)
            or len(cast("list[object]", payload)) < MIN_NEXT_PUSH_ITEMS
        ):
            continue
        payload_list = cast("list[object]", payload)
        frame_id = payload_list[0]
        value = payload_list[1]
        if isinstance(value, str):
            frames.extend(parse_json_frames(value))
        elif isinstance(frame_id, (str, int, float)):
            frames.append((str(frame_id), value))

    if frames:
        return frames
    return [(frame_id, value) for frame_id, value in parse_json_frames(document)]


def _default_evaluation_row(row: dict[str, object]) -> bool:
    identity_keys = ("slug", "model", "model_slug", "model_name", "name")
    score_keys = (
        "score",
        "value",
        "overall",
        "headlineValue",
        "pass_at_1",
        "coding",
    )
    has_identity = any(isinstance(row.get(key), str) for key in identity_keys)
    has_score = any(
        isinstance(row.get(key), (int, float)) and not isinstance(row.get(key), bool)
        for key in score_keys
    )
    return has_identity and has_score


def _scan_evaluation_node(
    node: object,
    *,
    predicate: Callable[[dict[str, object]], bool],
    min_rows: int,
    candidates: list[list[dict[str, object]]],
    seen_lists: set[int],
) -> None:
    if isinstance(node, list):
        list_node = cast("list[object]", node)
        node_id = id(list_node)
        if node_id not in seen_lists:
            seen_lists.add(node_id)
            matched: list[dict[str, object]] = [
                cast("dict[str, object]", item)
                for item in list_node
                if isinstance(item, dict) and predicate(cast("dict[str, object]", item))
            ]
            if len(matched) >= min_rows:
                candidates.append(matched)
        for item in list_node:
            _scan_evaluation_node(
                item,
                predicate=predicate,
                min_rows=min_rows,
                candidates=candidates,
                seen_lists=seen_lists,
            )
    elif isinstance(node, dict):
        dict_node = cast("dict[str, object]", node)
        for value in dict_node.values():
            _scan_evaluation_node(
                value,
                predicate=predicate,
                min_rows=min_rows,
                candidates=candidates,
                seen_lists=seen_lists,
            )


def extract_evaluation_rows(
    parsed_frames: list[tuple[str, object]],
    *,
    row_predicate: Callable[[dict[str, object]], bool] | None = None,
    min_rows: int = DEFAULT_MIN_EVALUATION_ROWS,
) -> list[dict[str, object]]:
    """Select the largest recognizable model-evaluation row list."""
    if min_rows < DEFAULT_MIN_EVALUATION_ROWS:
        message = "min_rows must be positive"
        raise ValueError(message)
    predicate = row_predicate or _default_evaluation_row
    candidates: list[list[dict[str, object]]] = []
    seen_lists: set[int] = set()
    for _, frame in parsed_frames:
        _scan_evaluation_node(
            frame,
            predicate=predicate,
            min_rows=min_rows,
            candidates=candidates,
            seen_lists=seen_lists,
        )
    if not candidates:
        _raise_extraction_error(
            "Evaluation payload missing recognizable model rows.",
        )
    return max(candidates, key=len)


def _add_candidate(
    candidates: dict[str, list[list[object]]],
    kind: str,
    value: list[object],
) -> None:
    if value:
        candidates[kind].append(value)


def _record_list_candidates(
    key: str,
    value: list[object],
    candidates: dict[str, list[list[object]]],
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
    candidates: dict[str, list[list[object]]],
    alias_map: dict[str, tuple[str, ...]],
) -> None:
    if isinstance(node, dict):
        dict_node = cast("dict[str, object]", node)
        for key, value in dict_node.items():
            if isinstance(value, list):
                _record_list_candidates(
                    key, cast("list[object]", value), candidates, alias_map
                )
            _scan_node(cast("object", value), candidates, alias_map)
    elif isinstance(node, list):
        list_node = cast("list[object]", node)
        for item in list_node:
            _scan_node(item, candidates, alias_map)


def extract_lists(
    parsed_frames: list[tuple[str, object]],
    *,
    source_path: str | None = None,
    source_hash: str | None = None,
    diagnostics: list[Diagnostic] | None = None,
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    """Extract provider lists while preserving source spelling and diagnostics."""
    diagnostics = diagnostics if diagnostics is not None else []
    candidates: dict[str, list[list[object]]] = {
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

    best_models = _pick_best(candidates["models"])
    best_hosts = _pick_best(candidates["hosts"])
    best_hosts_models = _pick_best(candidates["hostsModels"])
    best_rows = _pick_best(candidates["rows"])

    norm_hosts_models = (
        _normalize_current_rows(
            best_rows,
            source_path=source_path,
            source_hash=source_hash,
            diagnostics=diagnostics,
        )
        if best_hosts_models is None
        else _normalize_provider_rows(
            best_hosts_models,
            kind="hostsModels",
            source_path=source_path,
            source_hash=source_hash,
            diagnostics=diagnostics,
        )
    )
    norm_models = (
        _normalize_provider_rows(
            best_models,
            kind="models",
            source_path=source_path,
            source_hash=source_hash,
            diagnostics=diagnostics,
        )
        if best_models is not None
        else None
    )
    norm_hosts = (
        _normalize_provider_rows(
            best_hosts,
            kind="hosts",
            source_path=source_path,
            source_hash=source_hash,
            diagnostics=diagnostics,
        )
        if best_hosts is not None
        else None
    )
    selected: dict[str, list[dict[str, object]] | None] = {
        "models": norm_models,
        "hosts": norm_hosts,
        "hostsModels": norm_hosts_models,
    }
    missing = [key for key, value in selected.items() if value is None]
    if missing:
        candidate_details = {
            key: [len(value) for value in values[:5]]
            for key, values in candidates.items()
            if values
        }
        message = (
            f"Missing sections in RSC payload: {', '.join(missing)}; "
            f"candidate_sizes={candidate_details}"
        )
        _raise_extraction_error(message)

    models_list = selected["models"] or []
    hosts_list = selected["hosts"] or []
    hosts_models_list = selected["hostsModels"] or []
    _attach_row_diagnostics(models_list, diagnostics)
    _attach_row_diagnostics(hosts_list, diagnostics)
    _attach_row_diagnostics(hosts_models_list, diagnostics)
    return (
        models_list,
        hosts_list,
        hosts_models_list,
    )


_PROVIDER_HOST_FIELDS = frozenset(
    {
        "slug",
        "name",
        "website_url",
        "openai_compatible",
        "logo",
        "host_url",
        "api_url",
        "host_id",
        "id",
    },
)
_PROVIDER_MODEL_FIELDS = frozenset(
    {
        "slug",
        "name",
        "model_creator_id",
        "model_creators",
        "model_creator",
        "reasoning_model",
        "release_date",
        "context_window_tokens",
        "id",
        "intelligence_index",
        "coding_index",
        "math_index",
        "agentic_index",
        "gpqa",
        "mmlu_pro",
        "ifbench",
        "scicode",
        "tau_2",
        "terminalbench_hard",
        "license_name",
    },
)
_PROVIDER_ENDPOINT_FIELDS = frozenset(
    {
        "slug",
        "label",
        "name",
        "host_api_id",
        "host",
        "model",
        "features",
        "pricing",
        "performance",
    },
)
_PROVIDER_PRICING_FIELDS = frozenset(
    {
        "price_1m_input_tokens",
        "price_1m_output_tokens",
        "price_1m_blended_3_to_1",
        "price_1m_blended_7_to_2_to_1",
        "price_1m_cached_input_tokens",
        "price_1m_cache_read_tokens",
        "price_1m_cache_write_tokens",
    },
)
_PROVIDER_FEATURE_FIELDS = frozenset(
    {
        "context_window_tokens",
        "supports_function_calling",
        "supports_vision",
        "supports_json_mode",
        "supports_parallel_tool_calls",
    },
)
_PROVIDER_PERFORMANCE_FIELDS = frozenset(
    {
        "median_output_tokens_per_second",
        "median_time_to_first_token_seconds",
        "median_end_to_end_response_time_seconds",
    },
)


def _normalize_current_rows(
    rows: list[object] | None,
    *,
    source_path: str | None = None,
    source_hash: str | None = None,
    diagnostics: list[Diagnostic] | None = None,
) -> list[dict[str, object]] | None:
    if rows is None:
        return None

    endpoints: list[dict[str, object]] = []
    for index, row in enumerate(rows):
        endpoint = _normalize_current_row(
            row,
            source_path=(
                f"{source_path}[{index}]" if source_path else f"rows[{index}]"
            ),
            source_hash=source_hash,
            diagnostics=diagnostics,
        )
        if endpoint is not None:
            endpoints.append(endpoint)
    if not endpoints:
        return None
    return _deduplicate_endpoints(
        endpoints,
        source_path=source_path,
        diagnostics=diagnostics,
    )


def _normalize_current_row(  # noqa: C901
    row: object,
    *,
    source_path: str | None = None,
    source_hash: str | None = None,
    diagnostics: list[Diagnostic] | None = None,
) -> dict[str, object] | None:
    if not isinstance(row, dict):
        return None
    row_dict = cast("dict[str, object]", row)
    source = normalize_mapping(
        cast("Mapping[object, object]", row_dict),
        known_fields=_PROVIDER_ENDPOINT_FIELDS,
        path=source_path or "rows",
        source_path=source_path,
        source_hash=source_hash,
        parser="provider-rsc-current",
        diagnostics=diagnostics,
    )
    host = source.get("host")
    model = source.get("model")
    if not isinstance(host, dict) or not isinstance(model, dict):
        return None
    host_dict = cast("dict[str, object]", host)
    model_dict = cast("dict[str, object]", model)

    host_source = normalize_mapping(
        cast("Mapping[object, object]", host_dict),
        known_fields=_PROVIDER_HOST_FIELDS,
        path=f"{source_path}.host" if source_path else "rows.host",
        source_path=source_path,
        source_hash=source_hash,
        parser="provider-rsc-current",
        diagnostics=diagnostics,
    )
    model_source = normalize_mapping(
        cast("Mapping[object, object]", model_dict),
        known_fields=_PROVIDER_MODEL_FIELDS,
        path=f"{source_path}.model" if source_path else "rows.model",
        source_path=source_path,
        source_hash=source_hash,
        parser="provider-rsc-current",
        diagnostics=diagnostics,
    )
    host_slug = host_source.get("slug")
    model_slug = model_source.get("slug")
    if not isinstance(host_slug, str) or not host_slug:
        return None
    if not isinstance(model_slug, str) or not model_slug:
        return None

    normalized_features = _normalize_nested_source(
        source.get("features"),
        known_fields=_PROVIDER_FEATURE_FIELDS,
        path=f"{source_path}.features" if source_path else "rows.features",
        source_path=source_path,
        source_hash=source_hash,
        parser="provider-rsc-current",
        diagnostics=diagnostics,
    )
    normalized_pricing = _normalize_nested_source(
        source.get("pricing"),
        known_fields=_PROVIDER_PRICING_FIELDS,
        path=f"{source_path}.pricing" if source_path else "rows.pricing",
        source_path=source_path,
        source_hash=source_hash,
        parser="provider-rsc-current",
        diagnostics=diagnostics,
    )
    performance = _normalize_nested_source(
        source.get("performance"),
        known_fields=_PROVIDER_PERFORMANCE_FIELDS,
        path=f"{source_path}.performance" if source_path else "rows.performance",
        source_path=source_path,
        source_hash=source_hash,
        parser="provider-rsc-current",
        diagnostics=diagnostics,
    )
    performance_mapping: Mapping[str, object] = (
        cast("Mapping[str, object]", performance)
        if isinstance(performance, Mapping)
        else {}
    )
    endpoint: dict[str, object] = {
        "slug": f"{host_slug}_{model_slug}",
        "name": source.get("label"),
        "host_api_id": source.get("host_api_id"),
        "host": host_source,
        "model": model_source,
        "timescaleData": {
            "median_output_speed": performance_mapping.get(
                "median_output_tokens_per_second",
            ),
            "median_time_to_first_chunk": performance_mapping.get(
                "median_time_to_first_token_seconds",
            ),
        },
        "end_to_end_response_time_metrics": {
            "total_time": performance_mapping.get(
                "median_end_to_end_response_time_seconds",
            ),
        },
        "identity": canonical_endpoint_identity(
            host_slug,
            model_slug,
            source_path=source_path,
            source_hash=source_hash,
        ),
    }

    if isinstance(normalized_features, dict):
        features_dict = cast("dict[str, object]", normalized_features)
        endpoint.update(
            {
                key: value
                for key, value in features_dict.items()
                if key not in {"raw_fields", "raw_metadata"}
            },
        )
    if isinstance(normalized_pricing, dict):
        pricing_dict = cast("dict[str, object]", normalized_pricing)
        endpoint.update(
            {
                key: value
                for key, value in pricing_dict.items()
                if key not in {"raw_fields", "raw_metadata"}
            },
        )

    raw_fields: dict[str, object] = {}
    for value, prefix in (
        (source.get("raw_fields"), ""),
        (host_source.get("raw_fields"), "host"),
        (model_source.get("raw_fields"), "model"),
        (
            cast("dict[str, object]", normalized_features).get("raw_fields")
            if isinstance(normalized_features, dict)
            else None,
            "features",
        ),
        (
            cast("dict[str, object]", normalized_pricing).get("raw_fields")
            if isinstance(normalized_pricing, dict)
            else None,
            "pricing",
        ),
        (
            performance_mapping.get("raw_fields"),
            "performance",
        ),
    ):
        if not isinstance(value, dict):
            continue
        dict_val = cast("dict[str, object]", value)
        if prefix:
            raw_fields[prefix] = dict_val
        else:
            raw_fields.update(dict_val)
    if raw_fields:
        endpoint["raw_fields"] = raw_fields
    metadata = _raw_metadata(
        source_path=source_path,
        source_hash=source_hash,
        parser="provider-rsc-current",
    )
    if metadata:
        endpoint["raw_metadata"] = metadata
    return endpoint


def _normalize_camel_keys(
    value: object,
    *,
    path: str = "",
    source_path: str | None = None,
    source_hash: str | None = None,
    diagnostics: list[Diagnostic] | None = None,
) -> object:
    if isinstance(value, dict):
        dict_val = cast("dict[str, object]", value)
        return normalize_mapping(
            cast("Mapping[object, object]", dict_val),
            path=path,
            source_path=source_path,
            source_hash=source_hash,
            parser="provider-rsc",
            diagnostics=diagnostics,
        )
    if isinstance(value, list):
        list_val = cast("list[object]", value)
        return [
            _normalize_camel_keys(
                item,
                path=f"{path}[{index}]",
                source_path=source_path,
                source_hash=source_hash,
                diagnostics=diagnostics,
            )
            for index, item in enumerate(list_val)
        ]
    return value


def _looks_like_current_endpoint_rows(value: list[object]) -> bool:
    sample = [
        cast("dict[str, object]", item) for item in value[:25] if isinstance(item, dict)
    ]
    if not sample:
        return False
    hits = 0
    for item in sample:
        host = item.get("host")
        model = item.get("model")
        if (
            isinstance(host, dict)
            and isinstance(model, dict)
            and isinstance(cast("dict[str, object]", host).get("slug"), str)
            and isinstance(cast("dict[str, object]", model).get("slug"), str)
            and any(key in item for key in ("features", "pricing", "performance"))
        ):
            hits += 1
    return hits >= max(1, len(sample) // 2)


def _deduplicate_endpoints(
    rows: list[dict[str, object]],
    *,
    source_path: str | None,
    diagnostics: list[Diagnostic] | None,
) -> list[dict[str, object]]:
    def key(row: object) -> str | None:
        if isinstance(row, dict):
            val = cast("dict[str, object]", row).get("slug")
            return val if isinstance(val, str) else None
        return None

    return [
        row
        for row in classify_duplicate_rows(
            rows,
            identity=key,
            source_path=source_path,
            diagnostics=diagnostics,
        )
        if isinstance(row, dict)
    ]


def _normalize_provider_rows(
    rows: list[object],
    *,
    kind: str,
    source_path: str | None,
    source_hash: str | None,
    diagnostics: list[Diagnostic] | None,
) -> list[dict[str, object]]:
    known_fields = {
        "models": _PROVIDER_MODEL_FIELDS,
        "hosts": _PROVIDER_HOST_FIELDS,
        "hostsModels": _PROVIDER_ENDPOINT_FIELDS,
    }[kind]
    normalized_rows: list[dict[str, object]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        row_dict = cast("dict[str, object]", row)
        path = f"{source_path}[{index}]" if source_path else f"{kind}[{index}]"
        projected = normalize_mapping(
            cast("Mapping[object, object]", row_dict),
            known_fields=known_fields,
            path=path,
            source_path=path,
            source_hash=source_hash,
            parser="provider-rsc-legacy",
            diagnostics=diagnostics,
        )
        slug = projected.get("slug")
        if kind == "models" and isinstance(slug, str) and slug:
            projected["identity"] = canonical_model_identity(
                slug,
                source_path=path,
                source_hash=source_hash,
            )
        elif kind == "hostsModels" and isinstance(slug, str) and "_" in slug:
            host_slug, _, model_slug = slug.partition("_")
            if host_slug and model_slug:
                projected["identity"] = canonical_endpoint_identity(
                    host_slug,
                    model_slug,
                    endpoint_slug=slug,
                    source_path=path,
                    source_hash=source_hash,
                )
        metadata = _raw_metadata(
            source_path=path,
            source_hash=source_hash,
            parser="provider-rsc-legacy",
        )
        if metadata:
            projected["raw_metadata"] = metadata
        normalized_rows.append(projected)
    if kind == "models":
        return _deduplicate_models(
            normalized_rows,
            source_path=source_path,
            diagnostics=diagnostics,
        )
    if kind == "hostsModels":
        return _deduplicate_endpoints(
            normalized_rows,
            source_path=source_path,
            diagnostics=diagnostics,
        )
    return normalized_rows


def _pick_best[T: list[object]](options: list[T]) -> T | None:
    if not options:
        return None
    # Prefer largest candidate: most likely the complete table.
    return max(options, key=len)


def _looks_like_endpoint_list(value: list[object]) -> bool:
    sample = [
        cast("dict[str, object]", item) for item in value[:25] if isinstance(item, dict)
    ]
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


def _looks_like_host_list(value: list[object]) -> bool:
    sample = [
        cast("dict[str, object]", item) for item in value[:20] if isinstance(item, dict)
    ]
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


def _looks_like_model_list(value: list[object]) -> bool:
    sample = [
        cast("dict[str, object]", item) for item in value[:20] if isinstance(item, dict)
    ]
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


def endpoint_slugs(hosts_models: list[object]) -> list[str]:
    """Return sorted endpoint slugs from provider/model rows."""
    slugs: set[str] = set()
    for item in hosts_models:
        if not isinstance(item, dict):
            continue
        dict_item = cast("dict[str, object]", item)
        slug = dict_item.get("slug")
        if isinstance(slug, str) and "_" in slug and not _is_non_endpoint_slug(slug):
            slugs.add(slug)
    return sorted(slugs)


def _is_non_endpoint_slug(slug: str) -> bool:
    _, _, suffix = slug.partition("_")
    if not suffix:
        return True
    if any(ch.isdigit() for ch in suffix):
        return False
    return "-" not in suffix


def provider_from_slug(slug: str) -> str:
    """Extract the provider slug prefix from an endpoint slug."""
    return slug.split("_", 1)[0]


def build_full_url(slugs: list[str]) -> str:
    """Build a shareable Artificial Analysis URL for endpoint slugs."""
    joined = ",".join(slugs)
    encoded = quote(joined, safe="_-")
    return f"https://artificialanalysis.ai/?models=&endpoints={encoded}"


def _attach_row_diagnostics(
    rows: list[dict[str, object]],
    diagnostics: list[Diagnostic],
) -> None:
    if not diagnostics:
        return
    values = [item.to_dict() for item in diagnostics]
    for row in rows:
        metadata = row.get("raw_metadata")
        if not isinstance(metadata, dict):
            metadata_dict: dict[str, object] = {}
            row["raw_metadata"] = metadata_dict
        else:
            metadata_dict = cast("dict[str, object]", metadata)
        metadata_dict["diagnostics"] = values


def _diagnostics_from_rows(rows: list[object]) -> list[Diagnostic]:
    result: list[Diagnostic] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        dict_row = cast("dict[str, object]", row)
        metadata = dict_row.get("raw_metadata")
        if not isinstance(metadata, dict):
            continue
        metadata_dict = cast("dict[str, object]", metadata)
        values = metadata_dict.get("diagnostics")
        if not isinstance(values, list):
            continue
        values_list = cast("list[object]", values)
        for value in values_list:
            if isinstance(value, Diagnostic):
                result.append(value)
            elif isinstance(value, dict):
                dict_value = cast("dict[str, object]", value)
                result.append(
                    Diagnostic(
                        code=str(dict_value.get("code", "")),
                        severity=str(dict_value.get("severity", "")),
                        stage=str(dict_value.get("stage", "")),
                        message=str(dict_value.get("message", "")),
                        source_path=(
                            str(dict_value["source_path"])
                            if dict_value.get("source_path") is not None
                            else None
                        ),
                        artifact_id=(
                            str(dict_value["artifact_id"])
                            if dict_value.get("artifact_id") is not None
                            else None
                        ),
                        details=dict_value.get("details"),
                    ),
                )
    return result


def _stable_diagnostic_dicts(
    diagnostics: list[Diagnostic],
) -> list[dict[str, object]]:
    values: list[dict[str, object]] = []
    seen: set[str] = set()
    for diagnostic in diagnostics:
        projected = diagnostic.to_dict()
        marker = json.dumps(
            projected, sort_keys=True, separators=(",", ":"), default=str
        )
        if marker in seen:
            continue
        seen.add(marker)
        values.append(projected)
    return values


def build_snapshot_payload(  # noqa: PLR0913
    *,
    models: list[object],
    hosts: list[object],
    hosts_models: list[object],
    frame_count: int,
    rsc_result: FetchResult,
    rsc_etag: str | None,
    rsc_reused_cached_payload: bool,
    official_result: FetchResult,
    official_models: list[dict[str, object]],
    rsc_freshness: str | None = None,
    parser: str | None = None,
    source_path: str | None = None,
    diagnostics: list[Diagnostic] | None = None,
) -> dict[str, object]:
    """Merge sources into a schema-v2 snapshot with additive provenance."""
    slim_endpoints = _slim_endpoints(hosts_models)
    collected_diagnostics = list(diagnostics or [])
    collected_diagnostics.extend(_diagnostics_from_rows(models))
    collected_diagnostics.extend(_diagnostics_from_rows(hosts))
    collected_diagnostics.extend(_diagnostics_from_rows(hosts_models))
    canonical_models, unmatched_rsc, unmatched_api = _merge_canonical_models(
        rsc_models=models,
        rsc_endpoints=hosts_models,
        official_models=official_models,
        diagnostics=collected_diagnostics,
        source_path=source_path,
    )
    slugs = endpoint_slugs(cast("list[object]", slim_endpoints))
    providers_by_prefix = sorted({provider_from_slug(slug) for slug in slugs})
    providers_by_host = sorted(
        _provider_slugs_from_hosts_models(cast("list[object]", slim_endpoints))
    )
    api_url = redact_query(os.environ.get(MODEL_API_BASE_URL_ENV) or MODEL_API_URL)
    freshness = rsc_freshness or (
        "cache-revalidated" if rsc_reused_cached_payload else "fresh"
    )
    rsc_source: dict[str, object] = {
        "url": redact_query(rsc_result.final_url or BASE_URL),
        "status_code": rsc_result.status_code,
        "fetched_at": rsc_result.fetched_at,
        "etag": rsc_result.etag or rsc_etag,
        "last_modified": rsc_result.last_modified,
        "final_url": redact_query(rsc_result.final_url or BASE_URL),
        "sha256": rsc_result.sha256,
        "byte_length": rsc_result.byte_length,
        "artifact_ref": rsc_result.artifact_ref,
        "reused_cached_payload": rsc_reused_cached_payload,
        "freshness": freshness,
        "parser": parser or "provider-rsc",
        "source_path": source_path,
        "unmatched_api_model_slugs": unmatched_api,
    }
    official_source: dict[str, object] = {
        "url": api_url,
        "final_url": redact_query(official_result.final_url or api_url),
        "status_code": official_result.status_code,
        "fetched_at": official_result.fetched_at,
        "etag": official_result.etag or official_result.headers.get("etag"),
        "last_modified": official_result.last_modified,
        "sha256": official_result.sha256,
        "byte_length": official_result.byte_length,
        "artifact_ref": official_result.artifact_ref,
        "reused_cached_payload": False,
        "freshness": "fresh",
        "parser": "official-api-v2",
        "unmatched_rsc_model_slugs": unmatched_rsc,
    }

    return {
        "meta": {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "fetched_at": rsc_result.fetched_at,
            "freshness": {
                "mode": freshness,
                "stale": freshness in {"stale-last-good", "stale-cache"},
                "fallback": freshness == "stale-last-good",
            },
            "freshness_mode": freshness,
            "parser": {
                "name": parser or "artificial_analysis.rsc",
                "version": "3",
                "frame_count": frame_count,
                "source_path": source_path,
            },
            "artifacts": {
                "rsc": {
                    "sha256": rsc_result.sha256,
                    "byte_length": rsc_result.byte_length,
                    "artifact_ref": rsc_result.artifact_ref,
                },
                "official_api": {
                    "sha256": official_result.sha256,
                    "byte_length": official_result.byte_length,
                    "artifact_ref": official_result.artifact_ref,
                },
            },
            "diagnostics": _stable_diagnostic_dicts(collected_diagnostics),
            "sources": {"rsc": rsc_source, "official_api": official_source},
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


def _slim_endpoints(hosts_models: list[object]) -> list[dict[str, object]]:
    endpoints: list[dict[str, object]] = []
    for endpoint in hosts_models:
        if not isinstance(endpoint, dict):
            continue
        dict_endpoint = cast("dict[str, object]", endpoint)
        model = dict_endpoint.get("model")
        model_slug = (
            cast("dict[str, object]", model).get("slug")
            if isinstance(model, dict)
            and isinstance(cast("dict[str, object]", model).get("slug"), str)
            else dict_endpoint.get("model_slug")
        )
        if not isinstance(model_slug, str) or not model_slug:
            continue
        slim: dict[str, object] = {
            str(key): value for key, value in dict_endpoint.items() if key != "model"
        }
        slim["model_slug"] = model_slug
        endpoint_slug_raw = slim.get("slug")
        endpoint_slug = (
            endpoint_slug_raw
            if isinstance(endpoint_slug_raw, str) and endpoint_slug_raw
            else None
        )
        host = dict_endpoint.get("host")
        host_slug = (
            cast("dict[str, object]", host).get("slug")
            if isinstance(host, dict)
            and isinstance(cast("dict[str, object]", host).get("slug"), str)
            else (
                endpoint_slug.split("_", 1)[0]
                if endpoint_slug is not None and "_" in endpoint_slug
                else ""
            )
        )
        host_slug_str = host_slug if isinstance(host_slug, str) else ""
        if endpoint_slug is not None and host_slug_str and "identity" not in slim:
            slim["identity"] = canonical_endpoint_identity(
                host_slug_str,
                model_slug,
                endpoint_slug=endpoint_slug,
            )
        endpoints.append(slim)
    return endpoints


def _merge_canonical_models(
    *,
    rsc_models: list[object],
    rsc_endpoints: list[object],
    official_models: list[dict[str, object]],
    diagnostics: list[Diagnostic] | None = None,
    source_path: str | None = None,
) -> tuple[list[dict[str, object]], list[str], list[str]]:
    rsc_by_slug = _rsc_models_by_slug(
        rsc_models,
        rsc_endpoints,
        diagnostics=diagnostics,
        source_path=source_path,
    )
    official_by_slug: dict[str, dict[str, object]] = {}
    for model in official_models:
        slug = model.get("slug")
        if not isinstance(slug, str) or not slug:
            continue
        previous = official_by_slug.get(slug)
        if previous is None:
            official_by_slug[slug] = dict(model)
            continue
        if previous != model and diagnostics is not None:
            diagnostics.append(
                Diagnostic(
                    code="DUPLICATE_SOURCE_ROW",
                    severity="error",
                    stage="identity",
                    message=f"Conflicting official model rows for {slug!r}.",
                    source_path=source_path,
                    details={"identity": slug, "classification": "conflicting"},
                ),
            )
    all_slugs = sorted(set(rsc_by_slug) | set(official_by_slug))
    merged = [
        _merge_canonical_model(
            rsc_by_slug.get(slug),
            official_by_slug.get(slug),
            diagnostics=diagnostics,
            source_path=source_path,
        )
        for slug in all_slugs
    ]
    return (
        merged,
        sorted(set(rsc_by_slug) - set(official_by_slug)),
        sorted(set(official_by_slug) - set(rsc_by_slug)),
    )


def _rsc_models_by_slug(
    rsc_models: list[object],
    rsc_endpoints: list[object],
    *,
    diagnostics: list[Diagnostic] | None = None,
    source_path: str | None = None,
) -> dict[str, dict[str, object]]:
    values: dict[str, dict[str, object]] = {}
    candidates: list[object] = [
        *rsc_models,
        *[
            cast("dict[str, object]", item).get("model")
            for item in rsc_endpoints
            if isinstance(item, dict)
        ],
    ]
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        dict_candidate = cast("dict[str, object]", candidate)
        slug = dict_candidate.get("slug")
        if not isinstance(slug, str) or not slug:
            continue
        current = values.get(slug)
        if current is None:
            values[slug] = dict(dict_candidate)
            continue
        for key, value in dict_candidate.items():
            if key not in current or current[key] is None:
                current[key] = value
            elif current[key] != value and diagnostics is not None:
                diagnostics.append(
                    Diagnostic(
                        code="DUPLICATE_SOURCE_ROW",
                        severity="error",
                        stage="identity",
                        message=f"Conflicting RSC model fields for {slug!r}.",
                        source_path=source_path,
                        details={
                            "identity": slug,
                            "field": key,
                            "classification": "conflicting",
                        },
                    ),
                )
    return values


def _merge_canonical_model(  # noqa: C901, PLR0912
    rsc_model: dict[str, object] | None,
    official_model: dict[str, object] | None,
    *,
    diagnostics: list[Diagnostic] | None = None,
    source_path: str | None = None,
) -> dict[str, object]:
    if rsc_model is None and official_model is None:
        return {}
    if rsc_model is None:
        dict_off = cast("dict[str, object]", official_model)
        return dict(dict_off)
    merged = dict(rsc_model)
    if official_model is None:
        if "creator" not in merged and isinstance(merged.get("model_creators"), dict):
            merged["creator"] = merged["model_creators"]
        slug = merged.get("slug")
        if isinstance(slug, str) and slug and "identity" not in merged:
            merged["identity"] = canonical_model_identity(
                slug,
                source_path=source_path,
            )
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
        if key in official_model:
            merged[key] = official_model[key]
    evaluations = official_model.get("evaluations")
    if isinstance(evaluations, dict):
        dict_evals = cast("dict[str, object]", evaluations)
        merged.update(
            {name: value for name, value in dict_evals.items() if value is not None}
        )
    rsc_raw = merged.get("raw_fields")
    official_raw = official_model.get("raw_fields")
    if isinstance(official_raw, dict):
        dict_official_raw = cast("dict[str, object]", official_raw)
        if isinstance(rsc_raw, dict):
            dict_rsc_raw = cast("dict[str, object]", rsc_raw)
            combined = dict(dict_rsc_raw)
            for key, value in dict_official_raw.items():
                if (
                    key in combined
                    and combined[key] != value
                    and diagnostics is not None
                ):
                    slug_val = merged.get("slug")
                    diagnostics.append(
                        Diagnostic(
                            code="DUPLICATE_SOURCE_FIELD",
                            severity="error",
                            stage="identity",
                            message=f"Conflicting raw fields for model {slug_val!r}.",
                            source_path=source_path,
                            details={"field": key, "classification": "conflicting"},
                        ),
                    )
                elif key not in combined:
                    combined[key] = value
            merged["raw_fields"] = combined
        else:
            merged["raw_fields"] = dict(dict_official_raw)
    slug = merged.get("slug")
    if isinstance(slug, str) and slug:
        merged["identity"] = official_model.get(
            "identity",
            canonical_model_identity(slug, source_path=source_path),
        )
    return merged


def _provider_slugs_from_hosts_models(hosts_models: list[object]) -> set[str]:
    values: set[str] = set()
    for item in hosts_models:
        if not isinstance(item, dict):
            continue
        dict_item = cast("dict[str, object]", item)
        host = dict_item.get("host")
        if isinstance(host, dict) and isinstance(
            cast("dict[str, object]", host).get("slug"), str
        ):
            values.add(str(cast("dict[str, object]", host)["slug"]))
            continue
        slug = dict_item.get("slug")
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
        msg = (
            f"Too few endpoints extracted ({len(slugs)} < {min_endpoints}). "
            + "Payload format likely changed."
        )
        _raise_extraction_error(msg)
    if provider_count < min_providers:
        msg = (
            f"Too few providers extracted ({provider_count} < {min_providers}). "
            + "Payload format likely changed."
        )
        _raise_extraction_error(msg)


def _atomic_write(path: Path, data: bytes) -> None:
    """Replace a file atomically, leaving existing bytes intact on failure."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            _ = handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        _ = temporary.replace(path)
    finally:
        with contextlib.suppress(OSError):
            temporary.unlink()


def atomic_write(path: Path, data: bytes) -> None:
    """Expose the same atomic writer for command-specific output files."""
    _atomic_write(path, data)


def write_outputs(  # noqa: PLR0913
    *,
    output_json: Path,
    output_endpoints: Path,
    output_url: Path,
    payload: dict[str, object],
    slugs: list[str],
    full_url: str,
) -> None:
    """Write the snapshot and its endpoint/url companion files atomically."""
    _atomic_write(
        output_json,
        json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    )
    _atomic_write(output_endpoints, ("\n".join(slugs) + "\n").encode("utf-8"))
    _atomic_write(output_url, (full_url + "\n").encode("utf-8"))


def load_snapshot(path: Path) -> dict[str, object]:
    """Load and validate a JSON snapshot object."""
    try:
        parsed = cast("object", json.loads(path.read_text(encoding="utf-8")))
    except OSError as exc:
        _raise_extraction_error(f"Cannot read snapshot: {path}", exc)
    except json.JSONDecodeError as exc:
        _raise_extraction_error(f"Invalid JSON snapshot: {path}", exc)

    if not isinstance(parsed, dict):
        _raise_extraction_error(f"Snapshot root must be an object: {path}")
    return cast("dict[str, object]", parsed)


def snapshot_slugs(snapshot: dict[str, object]) -> list[str]:
    """Return endpoint slugs from any supported snapshot key."""
    for key in ("hosts_models", "hostsModels", "host_models", "endpoints"):
        value = snapshot.get(key)
        if isinstance(value, list):
            return endpoint_slugs(cast("list[object]", value))
    _raise_extraction_error("Snapshot missing hosts_models-compatible list")


def _text_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def load_cache_metadata(cache_dir: Path) -> CacheMetadata | None:
    """Read legacy mutable metadata, returning None when malformed."""
    meta_path = cache_dir / CACHE_META_FILE
    if not meta_path.exists():
        return None
    try:
        parsed = cast("object", json.loads(meta_path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, dict):
        return None
    dict_parsed = cast("dict[str, object]", parsed)
    body_file = _text_or_none(dict_parsed.get("body_file")) or CACHE_BODY_FILE
    return CacheMetadata(
        etag=_text_or_none(dict_parsed.get("etag")),
        fetched_at=_text_or_none(dict_parsed.get("fetched_at")),
        status_code=_int_or_none(dict_parsed.get("status_code")),
        body_file=body_file,
        last_modified=(
            _text_or_none(dict_parsed.get("last_modified"))
            or _text_or_none(dict_parsed.get("last-modified"))
        ),
        source_key=_text_or_none(dict_parsed.get("source_key")),
        source_url=_text_or_none(dict_parsed.get("source_url"))
        or _text_or_none(dict_parsed.get("url")),
        final_url=_text_or_none(dict_parsed.get("final_url")),
        sha256=_text_or_none(dict_parsed.get("sha256")),
        byte_length=_int_or_none(dict_parsed.get("byte_length")),
        artifact_ref=_text_or_none(dict_parsed.get("artifact_ref")),
        legacy_unverified=bool(dict_parsed.get("legacy_unverified", False)),
    )


def load_cached_body(cache_dir: Path, metadata: CacheMetadata | None) -> str | None:
    """Read a legacy mutable provider response body if available."""
    body_file = metadata.body_file if metadata is not None else CACHE_BODY_FILE
    body_path = cache_dir / body_file
    try:
        if not body_path.exists() or not body_path.is_file():
            return None
        return body_path.read_text(encoding="utf-8")
    except OSError:
        return None


def _record_metadata(
    record: dict[str, object],
    *,
    body_file: str = CACHE_BODY_FILE,
) -> CacheMetadata:
    nested = record.get("metadata")
    metadata: Mapping[str, object] = (
        cast("Mapping[str, object]", nested) if isinstance(nested, Mapping) else {}
    )
    return CacheMetadata(
        etag=_text_or_none(metadata.get("etag")),
        fetched_at=_text_or_none(metadata.get("fetched_at")),
        status_code=_int_or_none(metadata.get("status_code")),
        body_file=body_file,
        last_modified=_text_or_none(metadata.get("last_modified")),
        source_key=_text_or_none(record.get("source_key")),
        source_url=_text_or_none(metadata.get("source_url")),
        final_url=_text_or_none(metadata.get("final_url")),
        sha256=_text_or_none(record.get("sha256")),
        byte_length=_int_or_none(record.get("length")),
        artifact_ref=_text_or_none(record.get("raw_path")),
        legacy_unverified=record.get("legacy_unverified") is True,
    )


def load_cached_artifact(
    cache_dir: Path,
    *,
    source_key: str = RSC_SOURCE_KEY,
) -> tuple[bytes, dict[str, object]] | None:
    """Load an immutable source artifact, promoting valid legacy files once."""
    store = ArtifactStore(cache_dir)
    try:
        raw, record = store.load(source_key=source_key)
    except ArtifactNotFoundError:
        legacy_metadata = load_cache_metadata(cache_dir)
        body = load_cached_body(cache_dir, legacy_metadata)
        if body is None:
            return None
        raw = body.encode("utf-8")
        if legacy_metadata is not None:
            if (
                legacy_metadata.sha256 is not None
                and legacy_metadata.sha256 != hashlib.sha256(raw).hexdigest()
            ):
                return None
            if (
                legacy_metadata.byte_length is not None
                and legacy_metadata.byte_length != len(raw)
            ):
                return None
        legacy_path = cache_dir / (
            legacy_metadata.body_file if legacy_metadata else CACHE_BODY_FILE
        )
        promotion_metadata: dict[str, object] = {
            "source_url": legacy_metadata.source_url if legacy_metadata else source_key,
            "final_url": legacy_metadata.final_url if legacy_metadata else source_key,
            "etag": legacy_metadata.etag if legacy_metadata else None,
            "last_modified": legacy_metadata.last_modified if legacy_metadata else None,
            "fetched_at": legacy_metadata.fetched_at if legacy_metadata else None,
            "status_code": legacy_metadata.status_code if legacy_metadata else None,
            "legacy_path": str(legacy_path),
        }
        record = store.promote_legacy(source_key, raw, promotion_metadata)
        _ = store.write_manifest()
        return raw, record
    except ArtifactError:
        return None
    else:
        return raw, record


def save_cache(  # noqa: PLR0913
    *,
    cache_dir: Path,
    fetched_at: str,
    status_code: int,
    etag: str | None,
    body: str | None,
    last_modified: str | None = None,
    source_url: str = RSC_SOURCE_KEY,
    final_url: str | None = None,
    headers: dict[str, str] | None = None,
) -> None:
    """Persist mutable compatibility files and an immutable artifact record."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    store = ArtifactStore(cache_dir)
    record: dict[str, object] | None = None
    if body is not None:
        raw = body.encode("utf-8")
        artifact_metadata: dict[str, object] = {
            "source_url": source_url,
            "final_url": final_url or source_url,
            "status_code": status_code,
            "etag": etag,
            "last_modified": last_modified,
            "fetched_at": fetched_at,
            "headers": headers or {},
            "sha256": hashlib.sha256(raw).hexdigest(),
            "byte_length": len(raw),
        }
        record = store.store(source_url, raw, artifact_metadata)
        _atomic_write(cache_dir / CACHE_BODY_FILE, raw)
    else:
        cached = load_cached_artifact(cache_dir, source_key=source_url)
        if cached is not None:
            _, record = cached

    record_meta = _record_metadata(record) if record is not None else None
    digest = record_meta.sha256 if record_meta else None
    length = record_meta.byte_length if record_meta else None
    artifact_ref = record_meta.artifact_ref if record_meta else None
    meta = redact(
        {
            "etag": etag,
            "last_modified": last_modified,
            "fetched_at": fetched_at,
            "status_code": status_code,
            "body_file": CACHE_BODY_FILE,
            "source_key": source_url,
            "source_url": source_url,
            "final_url": final_url or source_url,
            "sha256": digest,
            "byte_length": length,
            "artifact_ref": artifact_ref,
            "legacy_unverified": (
                record.get("legacy_unverified") is True if record is not None else False
            ),
        },
    )
    _atomic_write(
        cache_dir / CACHE_META_FILE,
        json.dumps(meta, ensure_ascii=False).encode("utf-8"),
    )
    _ = store.write_manifest()


def save_last_good_snapshot(cache_dir: Path, payload: dict[str, object]) -> Path:
    """Persist a last-good snapshot for fetch fallback atomically."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / CACHE_LAST_GOOD_FILE
    _atomic_write(path, json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    return path


def load_last_good_snapshot(cache_dir: Path) -> dict[str, object] | None:
    """Load a last-good snapshot, returning None when unavailable."""
    path = cache_dir / CACHE_LAST_GOOD_FILE
    if not path.exists():
        return None
    try:
        parsed = cast("object", json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, dict):
        return None
    return cast("dict[str, object]", parsed)


__all__ = [
    "BASE_URL",
    "CACHE_BODY_FILE",
    "CACHE_LAST_GOOD_FILE",
    "CACHE_META_FILE",
    "CODING_CAPABILITY_URL",
    "DEFAULT_MIN_EVALUATION_ROWS",
    "MIN_NEXT_PUSH_ITEMS",
    "MIN_SAMPLE_SIZE",
    "MODEL_API_BASE_URL_ENV",
    "MODEL_API_KEY_ENV",
    "MODEL_API_URL",
    "NOT_MODIFIED",
    "RSC_SOURCE_KEY",
    "SNAPSHOT_SCHEMA_VERSION",
    "CacheError",
    "CacheMetadata",
    "ExtractionError",
    "FetchResult",
    "atomic_write",
    "build_full_url",
    "build_snapshot_payload",
    "endpoint_slugs",
    "extract_evaluation_rows",
    "extract_lists",
    "fetch_models",
    "fetch_page",
    "fetch_rsc",
    "load_cache_metadata",
    "load_cached_artifact",
    "load_cached_body",
    "load_last_good_snapshot",
    "load_snapshot",
    "normalize_official_models",
    "parse_json_frames",
    "parse_next_payload",
    "provider_from_slug",
    "sanity_check",
    "save_cache",
    "save_last_good_snapshot",
    "snapshot_slugs",
    "write_outputs",
]
