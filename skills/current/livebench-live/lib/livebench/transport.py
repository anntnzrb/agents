# Copyright (c) 2026
"""Injectable HTTP/file transport with strict freshness and conditional caching."""

from __future__ import annotations

import mimetypes
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import NoReturn, Protocol, cast, runtime_checkable
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit
from urllib.request import Request
from urllib.request import urlopen as _stdlib_urlopen

from .cache import CacheStore, sha256_bytes
from .contracts import RawArtifact, SkillError, SourceTarget, utc_now
from .diagnostics import redact
from .identity import canonical_url

# Kept as a module-level seam for deterministic tests; no browser/runtime dependency.

HTTP_OK = 200
HTTP_NOT_MODIFIED = 304
HTTP_MULTIPLE_CHOICES = 300
HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403
urlopen = _stdlib_urlopen


class FetchError(SkillError):
    """Transport failure with attempted target details."""


def _raise_fetch(
    code: str,
    message: str,
    details: dict[str, object] | None = None,
) -> NoReturn:
    """Raise a transport error without embedding policy in call sites."""
    error = FetchError(code, message, details)
    raise error


@runtime_checkable
class _HttpResponse(Protocol):
    """Minimal readable HTTP response surface."""

    status: int

    def read(self) -> bytes: ...
    def __enter__(self) -> object: ...
    def __exit__(self, *args: object) -> bool | None: ...


@runtime_checkable
class _HeadersLike(Protocol):
    """Headers-like object exposing string pairs via items()."""

    def items(self) -> Iterable[tuple[str, str]]: ...


def _headers(response: object) -> dict[str, str]:
    raw = cast("object", getattr(response, "headers", None))
    if raw is None:
        return {}
    if not isinstance(raw, _HeadersLike):
        return {}
    result: dict[str, str] = {}
    try:
        pairs = raw.items()
    except AttributeError:
        return {}
    for key, value in pairs:
        name = str(key)
        lowered = name.casefold()
        if lowered in {"authorization", "cookie", "set-cookie", "x-api-key"}:
            continue
        result[lowered] = str(redact(str(value), key=name))
    return result


def _status(response: object) -> int:
    value = cast("object", getattr(response, "status", None))
    if value is None:
        getter = cast("object", getattr(response, "getcode", None))
        value = getter() if callable(getter) else 200
    return int(cast("int | str", value))


def _final_url(response: object, requested: str) -> str:
    getter = cast("object", getattr(response, "geturl", None))
    value = getter() if callable(getter) else requested
    return str(value)


def _is_local(url: str) -> bool:
    parsed = urlsplit(url)
    return parsed.scheme in {"", "file", "fixture"}


def _local_path(url: str) -> Path:
    parsed = urlsplit(url)
    if parsed.scheme in {"fixture", "file"}:
        raw_path = parsed.path or parsed.netloc
        return Path(unquote(raw_path))
    return Path(url).expanduser()


def fetch_target(  # noqa: C901, PLR0911, PLR0912, PLR0913, PLR0915
    target: SourceTarget,
    cache: CacheStore,
    *,
    timeout: float = 30.0,
    allow_stale: bool = False,
    opener: Callable[..., object] | None = None,
    observed_at: str | None = None,
) -> RawArtifact:
    """Fetch one target, reusing only a matching validated cache entry on 304."""
    observed = observed_at or utc_now()
    cached = cache.load(target)
    if _is_local(target.url):
        path = _local_path(target.url)
        try:
            body = path.read_bytes()
        except OSError as exc:
            _raise_fetch(
                "SOURCE_UNAVAILABLE",
                "Local source artifact could not be read.",
                {"attempted_url": target.url, "error": str(exc)},
            )
        digest = sha256_bytes(body)
        metadata: dict[str, object] = {
            "source_url": target.url,
            "discovered_from": target.discovered_from,
            "release_id": target.release_id,
            "artifact_kind": target.artifact_kind,
            "status_code": 200,
            "content_type": mimetypes.guess_type(path.name)[0]
            or "application/octet-stream",
            "headers": {},
            "fetched_at": observed,
            "observed_at": observed,
            "sha256": digest,
            "byte_length": len(body),
            "freshness_mode": "snapshot"
            if target.url.startswith("fixture:")
            else "fresh",
            "historical": target.url.startswith("fixture:"),
            "stale": False,
        }
        try:
            saved = cache.save(target, body, metadata)
            metadata.update(saved)
        except OSError:
            # Reading an explicit fixture remains useful if the cache is unwritable.
            pass
        return _artifact_from_metadata(target, body, metadata)

    request_headers = {"Accept": ", ".join(target.expected_content_types)}
    if cached is not None:
        _, cached_meta = cached
        etag = _header_value(cached_meta, "etag")
        last_modified = _header_value(cached_meta, "last-modified")
        if etag:
            request_headers["If-None-Match"] = etag
        if last_modified:
            request_headers["If-Modified-Since"] = last_modified
    request = Request(target.url, headers=request_headers)  # noqa: S310
    open_fn = opener or urlopen
    try:
        response = cast("_HttpResponse", open_fn(request, timeout=timeout))
        with response:
            status = _status(response)
            response_headers = _headers(response)
            final_url = _final_url(response, target.url)
            body = response.read()
    except HTTPError as exc:
        status = exc.code
        geturl = cast("object", getattr(exc, "geturl", None))
        raw_url = geturl() if callable(geturl) else None
        final_url = str(raw_url) if raw_url else target.url
        response_headers = _headers(exc)
        body = b""
        if status in {HTTP_UNAUTHORIZED, HTTP_FORBIDDEN}:
            _raise_fetch(
                "SOURCE_AUTH_REQUIRED",
                "The official LiveBench source requires authentication.",
                {"attempted_url": target.url, "http_status": status},
            )
        if status == HTTP_NOT_MODIFIED:
            return _reuse_304(target, cached, response_headers, observed)
        if allow_stale and cached is not None:
            return _stale_artifact(target, cached, status, observed, str(exc))
        _raise_fetch(
            "SOURCE_UNAVAILABLE",
            f"Official source returned HTTP {status}.",
            {
                "attempted_url": target.url,
                "http_status": status,
                "final_url": final_url,
            },
        )
    except (OSError, URLError, TimeoutError) as exc:
        if allow_stale and cached is not None:
            return _stale_artifact(target, cached, None, observed, str(exc))
        _raise_fetch(
            "SOURCE_UNAVAILABLE",
            "The official LiveBench source could not be reached.",
            {"attempted_url": target.url, "error": str(exc)},
        )

    if status == HTTP_NOT_MODIFIED:
        return _reuse_304(target, cached, response_headers, observed)
    if status in {HTTP_UNAUTHORIZED, HTTP_FORBIDDEN}:
        _raise_fetch(
            "SOURCE_AUTH_REQUIRED",
            "The official LiveBench source requires authentication.",
            {"attempted_url": target.url, "http_status": status},
        )
    if status < HTTP_OK or status >= HTTP_MULTIPLE_CHOICES:
        if allow_stale and cached is not None:
            return _stale_artifact(
                target, cached, status, observed, "non-success response"
            )
        _raise_fetch(
            "SOURCE_UNAVAILABLE",
            f"Official source returned HTTP {status}.",
            {
                "attempted_url": target.url,
                "http_status": status,
                "final_url": final_url,
            },
        )
    if canonical_url(final_url) != canonical_url(target.url):
        _raise_fetch(
            "SOURCE_UNAVAILABLE",
            "Redirected source identity does not match the requested artifact.",
            {"attempted_url": target.url, "final_url": final_url},
        )

    metadata = {
        "source_url": target.url,
        "final_url": final_url,
        "discovered_from": target.discovered_from,
        "release_id": target.release_id,
        "artifact_kind": target.artifact_kind,
        "status_code": status,
        "content_type": response_headers.get("content-type"),
        "headers": response_headers,
        "etag": response_headers.get("etag"),
        "last_modified": response_headers.get("last-modified"),
        "fetched_at": observed,
        "observed_at": observed,
        "sha256": sha256_bytes(body),
        "byte_length": len(body),
        "freshness_mode": "fresh",
        "historical": False,
        "stale": False,
        "cache_reused": False,
    }
    try:
        saved = cache.save(target, body, metadata)
        metadata.update(saved)
    except OSError as exc:
        _raise_fetch(
            "CACHE_WRITE_FAILED",
            "Fetched bytes could not be made immutable in the cache.",
            {"attempted_url": target.url, "error": str(exc)},
        )
    return _artifact_from_metadata(target, body, metadata)


def _header_value(metadata: Mapping[str, object], name: str) -> str | None:
    direct = metadata.get(name)
    if isinstance(direct, str) and direct:
        return direct
    headers = metadata.get("headers")
    if isinstance(headers, Mapping):
        header_map = cast("Mapping[str, object]", headers)
        value = header_map.get(name) or header_map.get(name.casefold())
        if isinstance(value, str) and value:
            return value
    return None


def _reuse_304(
    target: SourceTarget,
    cached: tuple[bytes, dict[str, object]] | None,
    response_headers: Mapping[str, str],
    observed: str,
) -> RawArtifact:
    if cached is None:
        _raise_fetch(
            "CACHE_MISSING",
            "A 304 response had no matching validated cache entry.",
            {
                "attempted_url": target.url,
                "release_id": target.release_id,
                "artifact_kind": target.artifact_kind,
            },
        )
    body, prior = cached
    prior_etag = _header_value(prior, "etag")
    response_etag = response_headers.get("etag") or response_headers.get("ETag")
    if response_etag and prior_etag and response_etag != prior_etag:
        _raise_fetch(
            "CACHE_VALIDATOR_INVALID",
            "A 304 validator did not match the cached artifact.",
            {
                "attempted_url": target.url,
                "cached_etag": prior_etag,
                "response_etag": response_etag,
            },
        )
    prior_headers = prior.get("headers", {})
    merged_headers: dict[str, object] = dict(response_headers)
    if isinstance(prior_headers, dict):
        merged_headers.update(cast("dict[str, object]", prior_headers))
    metadata = dict(prior)
    metadata.update(
        {
            "status_code": HTTP_NOT_MODIFIED,
            "headers": merged_headers,
            "fetched_at": observed,
            "observed_at": observed,
            "freshness_mode": "revalidated",
            "historical": False,
            "stale": False,
            "cache_reused": True,
        }
    )
    return _artifact_from_metadata(target, body, metadata)


def _stale_artifact(
    target: SourceTarget,
    cached: tuple[bytes, dict[str, object]],
    status: int | None,
    observed: str,
    reason: str,
) -> RawArtifact:
    body, prior = cached
    metadata = dict(prior)
    metadata.update(
        {
            "status_code": status or int(cast("int", prior.get("status_code", 200))),
            "fetched_at": observed,
            "observed_at": observed,
            "freshness_mode": "stale-cache",
            "historical": False,
            "stale": True,
            "cache_reused": True,
            "stale_reason": reason,
        }
    )
    return _artifact_from_metadata(target, body, metadata)


def _artifact_from_metadata(
    target: SourceTarget, body: bytes, metadata: Mapping[str, object]
) -> RawArtifact:
    digest = sha256_bytes(body)
    raw_headers = metadata.get("headers")
    if isinstance(raw_headers, Mapping):
        header_map = cast("Mapping[str, object]", raw_headers)
        headers = {str(key): str(value) for key, value in header_map.items()}
    else:
        headers = {}
    return RawArtifact(
        artifact_id=f"livebench:{target.release_id}:{target.artifact_kind}:sha256:{digest}",
        source="livebench",
        release_id=target.release_id,
        artifact_kind=target.artifact_kind,
        source_url=target.url,
        discovered_from=target.discovered_from,
        body=body,
        status_code=int(cast("int", metadata.get("status_code", 200))),
        content_type=str(metadata.get("content_type"))
        if metadata.get("content_type")
        else None,
        headers=headers,
        fetched_at=str(metadata.get("fetched_at", utc_now())),
        observed_at=str(
            metadata.get("observed_at", metadata.get("fetched_at", utc_now()))
        ),
        sha256=digest,
        byte_length=len(body),
        raw_bytes_ref=str(metadata.get("raw_bytes_ref"))
        if metadata.get("raw_bytes_ref")
        else None,
        freshness_mode=str(metadata.get("freshness_mode", "fresh")),
        stale=bool(metadata.get("stale", False)),
        historical=bool(metadata.get("historical", False)),
        cache_reused=bool(metadata.get("cache_reused", False)),
        generated_at=str(metadata.get("generated_at"))
        if metadata.get("generated_at")
        else None,
    )
