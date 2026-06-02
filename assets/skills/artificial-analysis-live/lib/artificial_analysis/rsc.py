from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

BASE_URL = "https://artificialanalysis.ai/leaderboards/providers"
CODING_CAPABILITY_URL = "https://artificialanalysis.ai/models/capabilities/coding"
CACHE_META_FILE = "providers-cache.json"
CACHE_BODY_FILE = "providers.rsc"
CACHE_LAST_GOOD_FILE = "last-good.json"
SNAPSHOT_SCHEMA_VERSION = 1


class ExtractionError(RuntimeError):
    """Raised when expected Artificial Analysis payload sections are missing."""


@dataclass(frozen=True)
class FetchResult:
    body: str
    status_code: int
    headers: dict[str, str]
    fetched_at: str


@dataclass(frozen=True)
class CacheMetadata:
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
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 (trusted URL)
            body = response.read().decode("utf-8", errors="replace")
            return FetchResult(
                body=body,
                status_code=response.status,
                headers={k.lower(): v for k, v in response.headers.items()},
                fetched_at=fetched_at,
            )
    except HTTPError as exc:
        if exc.code == 304:
            return FetchResult(
                body="",
                status_code=304,
                headers={k.lower(): v for k, v in exc.headers.items()},
                fetched_at=fetched_at,
            )
        raise OSError(f"Upstream request failed: HTTP {exc.code}") from exc


def parse_json_frames(rsc_payload: str) -> list[tuple[str, Any]]:
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


def extract_lists(
    parsed_frames: list[tuple[str, Any]],
) -> tuple[list[Any], list[Any], list[Any]]:
    candidates: dict[str, list[list[Any]]] = {
        "models": [],
        "hosts": [],
        "hostsModels": [],
    }

    alias_map: dict[str, tuple[str, ...]] = {
        "models": ("models", "model_rows", "modelrows"),
        "hosts": ("hosts", "providers", "provider_rows", "host_rows"),
        "hostsModels": ("hostsmodels", "host_models", "endpoints", "hostmodels"),
    }

    def add_candidate(kind: str, value: list[Any]) -> None:
        if value:
            candidates[kind].append(value)

    def scan(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(value, list):
                    normalized = key.replace("-", "_").lower()

                    if normalized in alias_map["models"]:
                        add_candidate("models", value)
                    if normalized in alias_map["hosts"]:
                        add_candidate("hosts", value)
                    if normalized in alias_map["hostsModels"]:
                        add_candidate("hostsModels", value)

                    # Structural fallback heuristics for breaking schema changes.
                    if _looks_like_endpoint_list(value):
                        add_candidate("hostsModels", value)
                    if _looks_like_host_list(value):
                        add_candidate("hosts", value)
                    if _looks_like_model_list(value):
                        add_candidate("models", value)

                scan(value)
            return

        if isinstance(node, list):
            for item in node:
                scan(item)

    for _, frame in parsed_frames:
        scan(frame)

    selected = {
        key: _pick_best(candidates[key]) for key in ("models", "hosts", "hostsModels")
    }

    missing = [key for key, value in selected.items() if value is None]
    if missing:
        diagnostics = {
            key: [len(value) for value in values[:5]]
            for key, values in candidates.items()
            if values
        }
        raise ExtractionError(
            f"Missing sections in RSC payload: {', '.join(missing)}; candidate_sizes={diagnostics}"
        )

    return (
        selected["models"] or [],
        selected["hosts"] or [],
        selected["hostsModels"] or [],
    )


def _pick_best(options: list[list[Any]]) -> list[Any] | None:
    if not options:
        return None
    # Prefer largest candidate: most likely the complete table.
    return max(options, key=len)


def _looks_like_endpoint_list(value: list[Any]) -> bool:
    sample = [item for item in value[:25] if isinstance(item, dict)]
    if len(sample) < 2:
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
    if len(sample) < 2:
        return False

    hit = 0
    for item in sample:
        if isinstance(item.get("slug"), str) and isinstance(item.get("name"), str):
            if any(
                k in item
                for k in ("website_url", "openai_compatible", "logo", "host_url")
            ):
                hit += 1
    return hit >= max(2, len(sample) // 2)


def _looks_like_model_list(value: list[Any]) -> bool:
    sample = [item for item in value[:20] if isinstance(item, dict)]
    if len(sample) < 2:
        return False

    hit = 0
    for item in sample:
        if isinstance(item.get("slug"), str) and isinstance(item.get("name"), str):
            if any(
                k in item
                for k in ("intelligence_index", "model_creator_id", "reasoning_model")
            ):
                hit += 1
    return hit >= max(2, len(sample) // 2)


def endpoint_slugs(hosts_models: list[Any]) -> list[str]:
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
    return slug.split("_", 1)[0]


def _is_non_endpoint_slug(slug: str) -> bool:
    _, _, suffix = slug.partition("_")
    if not suffix:
        return True
    if any(ch.isdigit() for ch in suffix):
        return False
    return "-" not in suffix


def build_full_url(slugs: list[str]) -> str:
    joined = ",".join(slugs)
    encoded = quote(joined, safe="_-")
    return f"https://artificialanalysis.ai/?models=&endpoints={encoded}"


def build_snapshot_payload(
    *,
    models: list[Any],
    hosts: list[Any],
    hosts_models: list[Any],
    frame_count: int,
    fetched_at: str,
    status_code: int,
    etag: str | None,
) -> dict[str, Any]:
    slugs = endpoint_slugs(hosts_models)
    providers_by_prefix = sorted({provider_from_slug(slug) for slug in slugs})
    providers_by_host = sorted(_provider_slugs_from_hosts_models(hosts_models))

    return {
        "meta": {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "source_url": BASE_URL,
            "source_mode": "rsc",
            "fetched_at": fetched_at,
            "status_code": status_code,
            "etag": etag,
            "counts": {
                "models": len(models),
                "hosts": len(hosts),
                "hosts_models": len(hosts_models),
                "endpoint_slugs": len(slugs),
                "providers_by_prefix": len(providers_by_prefix),
                "providers": len(providers_by_host),
                "frames": frame_count,
            },
        },
        "models": models,
        "hosts": hosts,
        "hosts_models": hosts_models,
    }


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


def sanity_check(*, slugs: list[str], min_endpoints: int, min_providers: int) -> None:
    provider_count = len({provider_from_slug(slug) for slug in slugs})
    if len(slugs) < min_endpoints:
        raise ExtractionError(
            f"Too few endpoints extracted ({len(slugs)} < {min_endpoints}). Payload format likely changed."
        )
    if provider_count < min_providers:
        raise ExtractionError(
            f"Too few providers extracted ({provider_count} < {min_providers}). Payload format likely changed."
        )


def write_outputs(
    *,
    output_json: Path,
    output_endpoints: Path,
    output_url: Path,
    payload: dict[str, Any],
    slugs: list[str],
    full_url: str,
) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_endpoints.parent.mkdir(parents=True, exist_ok=True)
    output_url.parent.mkdir(parents=True, exist_ok=True)

    output_json.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    output_endpoints.write_text("\n".join(slugs) + "\n", encoding="utf-8")
    output_url.write_text(full_url + "\n", encoding="utf-8")


def load_snapshot(path: Path) -> dict[str, Any]:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ExtractionError(f"Cannot read snapshot: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ExtractionError(f"Invalid JSON snapshot: {path}") from exc

    if not isinstance(parsed, dict):
        raise ExtractionError(f"Snapshot root must be an object: {path}")
    return parsed


def snapshot_slugs(snapshot: dict[str, Any]) -> list[str]:
    for key in ("hosts_models", "hostsModels", "host_models", "endpoints"):
        value = snapshot.get(key)
        if isinstance(value, list):
            return endpoint_slugs(value)
    raise ExtractionError("Snapshot missing hosts_models-compatible list")


def load_cache_metadata(cache_dir: Path) -> CacheMetadata | None:
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
        json.dumps(meta, ensure_ascii=False), encoding="utf-8"
    )


def save_last_good_snapshot(cache_dir: Path, payload: dict[str, Any]) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / CACHE_LAST_GOOD_FILE
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def load_last_good_snapshot(cache_dir: Path) -> dict[str, Any] | None:
    path = cache_dir / CACHE_LAST_GOOD_FILE
    if not path.exists():
        return None
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None
