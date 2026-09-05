# Copyright 2026 Vals-live contributors.
"""Immutable content-addressed artifacts and conditional HTTP transport."""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import NoReturn, Protocol, Self, cast
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request

from .contracts import RawArtifact
from .diagnostics import redact

HTTP_OK = 200
HTTP_NOT_MODIFIED = 304
HTTP_SUCCESS_LIMIT = 300


def urlopen(request: Request, *, timeout: float = 30.0) -> object:
    """Indirection used by deterministic transport fakes."""
    return cast("object", urllib_request.urlopen(request, timeout=timeout))  # noqa: S310


class ResponseLike(Protocol):
    """Describe the HTTP response interface consumed by the cache."""

    status: int
    headers: object

    def read(self) -> bytes:
        """Read the response body."""
        ...

    def geturl(self) -> str:
        """Return the final response URL."""
        ...

    def getcode(self) -> int:
        """Return the HTTP status code."""
        ...

    def getheader(self, name: str, default: str | None = None) -> str | None:
        """Return one response header."""
        ...

    def __enter__(self) -> Self:
        """Enter the response context."""
        ...

    def __exit__(self, *args: object) -> None:
        """Exit the response context."""
        ...


@dataclass
class CacheEntry:
    """Address one immutable cached artifact."""

    url: str
    release: str | None
    sha256: str
    body_path: Path
    metadata_path: Path
    metadata: dict[str, object]
    body: bytes


class CacheError(RuntimeError):
    """Represent a structured transport/cache failure."""

    code: str
    details: dict[str, object]

    def __init__(
        self, code: str, message: str, details: Mapping[str, object] | None = None
    ) -> None:
        """Initialize the stable error code, message, and details."""
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})


def default_cache_dir() -> Path:
    """Return the platform-appropriate vals-live cache directory."""
    configured = os.environ.get("VALS_CACHE_DIR")
    if configured:
        return Path(configured).expanduser()
    if os.name == "nt":
        root = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(root) / "vals-live" / "Cache"
    if os.name == "darwin":
        return Path.home() / "Library" / "Caches" / "vals-live"
    root = os.environ.get("XDG_CACHE_HOME")
    return (Path(root).expanduser() if root else Path.home() / ".cache") / "vals-live"


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _key(url: str, release: str | None) -> str:
    return sha256(f"vals\n{release or ''}\n{url}".encode()).hexdigest()


def _header(headers: object, name: str) -> str | None:
    wanted = name.lower()
    if headers is None:
        return None
    get = getattr(headers, "get", None)
    if callable(get):
        value = get(name)
        if value is None:
            value = get(wanted)
        if value is not None:
            return str(value)
    if isinstance(headers, Mapping):
        headers_map = cast("Mapping[object, object]", headers)
        for key, value in headers_map.items():
            if str(key).lower() == wanted:
                return str(value)
    return None


def _status(response: object) -> int:
    value = getattr(response, "status", None)
    if isinstance(value, int):
        return value
    getcode = getattr(response, "getcode", None)
    if callable(getcode):
        result = getcode()
        if isinstance(result, int):
            return result
    return 200


def _final_url(response: object, requested: str) -> str:
    geturl = getattr(response, "geturl", None)
    if callable(geturl):
        value = geturl()
        if isinstance(value, str) and value:
            return value
    return requested


def _atomic_bytes(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            _ = handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        _ = Path(temp_name).replace(path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            Path(temp_name).unlink()


def _atomic_json(path: Path, value: Mapping[str, object]) -> None:
    _atomic_bytes(
        path,
        json.dumps(
            redact(dict(value)),
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8"),
    )


class CacheStore:
    """Append-only cache. Existing bytes are never replaced or evicted."""

    root: Path
    artifacts: Path
    index: Path

    def __init__(self, root: str | os.PathLike[str] | None = None) -> None:
        """Initialize cache directories without creating them yet."""
        self.root = Path(root).expanduser() if root else default_cache_dir()
        self.artifacts = self.root / "artifacts"
        self.index = self.root / "index"

    def put(self, artifact: RawArtifact) -> CacheEntry:
        """Persist an artifact without replacing existing bytes."""
        digest = artifact.sha256 or sha256(artifact.body).hexdigest()
        body_path = self.artifacts / f"{digest}.raw"
        meta_path = self.artifacts / f"{digest}.meta.json"
        if not body_path.exists():
            _atomic_bytes(body_path, artifact.body)
        metadata: dict[str, object] = {
            "source": "vals",
            "source_url": artifact.source_url,
            "discovered_from": artifact.discovered_from,
            "final_url": artifact.final_url or artifact.source_url,
            "status_code": artifact.status_code,
            "content_type": artifact.content_type,
            "etag": artifact.etag,
            "last_modified": artifact.last_modified,
            "fetched_at": artifact.fetched_at,
            "observed_at": artifact.observed_at,
            "sha256": digest,
            "byte_length": len(artifact.body),
            "release": artifact.release,
            "raw_bytes_ref": str(body_path),
            "parser": "vals.transport",
            "parser_version": "1",
        }
        if not meta_path.exists():
            _atomic_json(meta_path, metadata)
        index_path = self.index / f"{_key(artifact.source_url, artifact.release)}.json"
        if not index_path.exists():
            _atomic_json(
                index_path,
                {
                    "metadata_path": str(meta_path),
                    "body_path": str(body_path),
                    "sha256": digest,
                },
            )
        artifact.sha256 = digest
        artifact.local_path = str(body_path)
        return CacheEntry(
            artifact.source_url,
            artifact.release,
            digest,
            body_path,
            meta_path,
            metadata,
            artifact.body,
        )

    def get(self, url: str, release: str | None = None) -> CacheEntry | None:
        """Load and validate an artifact index entry."""
        index_path = self.index / f"{_key(url, release)}.json"
        try:
            pointer_raw: object = cast(
                "object", json.loads(index_path.read_text(encoding="utf-8"))
            )
            if not isinstance(pointer_raw, Mapping):
                return None
            pointer = cast("Mapping[str, object]", pointer_raw)
            body_path = Path(str(pointer["body_path"]))
            meta_path = Path(str(pointer["metadata_path"]))
            body = body_path.read_bytes()
            metadata_raw: object = cast(
                "object", json.loads(meta_path.read_text(encoding="utf-8"))
            )
            if not isinstance(metadata_raw, Mapping):
                return None
            meta_map = cast("Mapping[str, object]", metadata_raw)
            digest = sha256(body).hexdigest()
            if digest != str(meta_map.get("sha256")) or digest != str(
                pointer.get("sha256")
            ):
                return None
            if (
                str(meta_map.get("source_url")) != url
                or meta_map.get("release") != release
            ):
                return None
            return CacheEntry(
                url, release, digest, body_path, meta_path, dict(meta_map), body
            )
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None

    def manifest(
        self, entries: list[CacheEntry], *, release: str | None, source_url: str
    ) -> Path:
        """Write a content-addressed snapshot manifest."""
        payload: dict[str, object] = {
            "schema_version": "1",
            "source": "vals",
            "source_url": source_url,
            "release": release,
            "created_at": _now(),
            "artifacts": [
                dict(
                    entry.metadata,
                    body_path=str(entry.body_path),
                    metadata_path=str(entry.metadata_path),
                )
                for entry in entries
            ],
        }
        digest = sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        path = self.root / "manifests" / f"{digest}.json"
        if not path.exists():
            _atomic_json(path, payload)
        return path


def _response_body(response: object) -> bytes:
    read = getattr(response, "read", None)
    if not callable(read):
        msg = "SOURCE_UNAVAILABLE"
        raise CacheError(msg, "Response did not provide a body.")
    body = read()
    if not isinstance(body, bytes):
        body = str(body).encode("utf-8")
    return body


_SECRET_HEADERS = {
    "authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "api-key",
    "token",
    "access-token",
}


def _request_headers(
    headers: Mapping[str, str] | None, cached: CacheEntry | None
) -> dict[str, str]:
    request_headers = {
        "User-Agent": "vals-live/1",
        "Accept": "text/html,application/json,text/csv;q=0.9,*/*;q=0.1",
    }
    if headers:
        request_headers.update(
            {
                key: value
                for key, value in headers.items()
                if key.casefold() not in _SECRET_HEADERS
            }
        )
    if cached:
        etag = cached.metadata.get("etag")
        last_modified = cached.metadata.get("last_modified")
        if isinstance(etag, str) and etag:
            request_headers["If-None-Match"] = etag
        if isinstance(last_modified, str) and last_modified:
            request_headers["If-Modified-Since"] = last_modified
    return request_headers


def _cache_error(code: str, message: str, details: Mapping[str, object]) -> NoReturn:
    raise CacheError(code, message, details)


@dataclass(frozen=True)
class _FetchOptions:
    discovered_from: str
    release: str | None
    cache: CacheStore | None
    allow_stale: bool
    timeout: float
    headers: Mapping[str, str] | None


@dataclass(frozen=True)
class _FetchContext:
    url: str
    options: _FetchOptions
    store: CacheStore
    cached: CacheEntry | None
    request_headers: Mapping[str, str]
    fetched_at: str


def _option_error(message: str) -> NoReturn:
    raise TypeError(message)


def _fetch_options(kwargs: Mapping[str, object]) -> _FetchOptions:
    allowed = {
        "discovered_from",
        "release",
        "cache",
        "allow_stale",
        "timeout",
        "headers",
    }
    unexpected = set(kwargs) - allowed
    if unexpected:
        _option_error(f"Unexpected fetch options: {sorted(unexpected)}")
    discovered_from = kwargs.get("discovered_from")
    if not isinstance(discovered_from, str):
        _option_error("fetch() requires discovered_from as a string")
    release = kwargs.get("release")
    if release is not None and not isinstance(release, str):
        _option_error("fetch() release must be a string or None")
    cache = kwargs.get("cache")
    if cache is not None and not isinstance(cache, CacheStore):
        _option_error("fetch() cache must be a CacheStore or None")
    timeout = kwargs.get("timeout", 30.0)
    if not isinstance(timeout, (int, float)):
        _option_error("fetch() timeout must be numeric")
    headers_value = kwargs.get("headers")
    if headers_value is not None and not isinstance(headers_value, Mapping):
        _option_error("fetch() headers must be a mapping or None")
    headers_map = (
        cast("Mapping[object, object]", headers_value)
        if isinstance(headers_value, Mapping)
        else None
    )
    headers = (
        {str(key): str(value) for key, value in headers_map.items()}
        if headers_map is not None
        else None
    )
    return _FetchOptions(
        discovered_from=discovered_from,
        release=release,
        cache=cache,
        allow_stale=bool(kwargs.get("allow_stale", False)),
        timeout=float(timeout),
        headers=headers,
    )


def _cached_artifact(
    context: _FetchContext,
    *,
    stale_reason: CacheError | None = None,
    status_code: int | None = None,
    final_url: str | None = None,
) -> RawArtifact:
    metadata = context.cached.metadata if context.cached else {}
    reason: dict[str, object] | None = (
        {
            "code": stale_reason.code,
            "message": str(stale_reason),
            "details": dict(stale_reason.details),
        }
        if stale_reason
        else None
    )
    cached = context.cached
    if cached is None:
        _cache_error(
            "CACHE_MISSING",
            "A cached artifact was required but not available.",
            {"attempted_url": context.url},
        )
    options = context.options
    status_raw = metadata.get("status_code")
    status_val = (
        int(status_raw)
        if isinstance(status_raw, (int, str))
        else (status_code or HTTP_OK)
    )
    return RawArtifact(
        context.url,
        options.discovered_from,
        cached.body,
        status_code=status_val,
        content_type=str(metadata.get("content_type") or "application/octet-stream"),
        final_url=str(metadata.get("final_url") or final_url or context.url),
        etag=str(metadata.get("etag")) if metadata.get("etag") else None,
        last_modified=(
            str(metadata.get("last_modified"))
            if metadata.get("last_modified")
            else None
        ),
        fetched_at=context.fetched_at,
        observed_at=str(metadata.get("observed_at") or context.fetched_at),
        release=options.release,
        stale=stale_reason is not None,
        stale_reason=reason,
        cache_reused=stale_reason is None,
        sha256=cached.sha256,
        local_path=str(cached.body_path),
    )


def _fetch_once(context: _FetchContext) -> RawArtifact:
    options = context.options
    request = Request(  # noqa: S310
        context.url, headers=dict(context.request_headers), method="GET"
    )
    opened = urlopen(request, timeout=options.timeout)
    response_context = _ResponseContext(opened)
    with response_context as response:
        status = _status(response)
        response_headers: object = getattr(response, "headers", None)
        final_url = _final_url(response, context.url)
        if status == HTTP_NOT_MODIFIED:
            cached = context.cached
            if cached is None:
                _cache_error(
                    "CACHE_MISSING",
                    "Received 304 without a validated cache entry.",
                    {"attempted_url": context.url},
                )
            response_etag = _header(response_headers, "ETag") or str(
                cached.metadata.get("etag") or ""
            )
            if cached.metadata.get("etag") and response_etag != cached.metadata.get(
                "etag"
            ):
                _cache_error(
                    "CACHE_VALIDATOR_INVALID",
                    "304 validator did not match cached bytes.",
                    {"attempted_url": context.url},
                )
            return _cached_artifact(
                context, final_url=final_url, status_code=HTTP_NOT_MODIFIED
            )
        body = _response_body(response)
        content_type = _header(response_headers, "Content-Type")
        etag = _header(response_headers, "ETag")
        last_modified = _header(response_headers, "Last-Modified")
        if status in (401, 403):
            _cache_error(
                "SOURCE_AUTH_REQUIRED",
                "The official Vals source requires authentication.",
                {"attempted_url": context.url, "http_status": status},
            )
        if status < HTTP_OK or status >= HTTP_SUCCESS_LIMIT:
            _cache_error(
                "SOURCE_UNAVAILABLE",
                "The official Vals source returned an unusable status.",
                {"attempted_url": context.url, "http_status": status},
            )
        artifact = RawArtifact(
            context.url,
            options.discovered_from,
            body,
            status_code=status,
            content_type=content_type,
            final_url=final_url,
            etag=etag,
            last_modified=last_modified,
            fetched_at=context.fetched_at,
            observed_at=context.fetched_at,
            release=options.release,
            sha256=sha256(body).hexdigest(),
        )
        _ = context.store.put(artifact)
        return artifact


def fetch(url: str, **kwargs: object) -> RawArtifact:
    """Fetch bytes with both validators; stale use is opt-in and visible."""
    options = _fetch_options(kwargs)
    if urlsplit(url).scheme.casefold() not in {"http", "https"}:
        _cache_error(
            "SOURCE_UNAVAILABLE",
            "The official Vals source URL must use HTTP or HTTPS.",
            {"attempted_url": url},
        )
    store = options.cache or CacheStore()
    cached = store.get(url, options.release)
    context = _FetchContext(
        url,
        options,
        store,
        cached,
        _request_headers(options.headers, cached),
        _now(),
    )
    try:
        return _fetch_once(context)
    except CacheError as exc:
        if options.allow_stale and cached is not None:
            return _cached_artifact(context, stale_reason=exc)
        raise
    except (HTTPError, URLError, OSError, TimeoutError) as exc:
        if isinstance(exc, HTTPError):
            _ = exc.close()
        status = getattr(exc, "code", None)
        code = "SOURCE_AUTH_REQUIRED" if status in (401, 403) else "SOURCE_UNAVAILABLE"
        details: dict[str, object] = {"attempted_url": url}
        if isinstance(status, int):
            details["http_status"] = status
        if options.allow_stale and cached is not None:
            return _cached_artifact(
                context,
                stale_reason=CacheError(code, str(exc), details),
            )
        raise CacheError(
            code, "The official Vals source could not be fetched.", details
        ) from exc


class _ResponseContext:
    response: object

    def __init__(self, response: object) -> None:
        self.response = response

    def __enter__(self) -> object:
        enter = getattr(self.response, "__enter__", None)
        if callable(enter):
            return enter()
        return self.response

    def __exit__(self, *args: object) -> None:
        exit_m = getattr(self.response, "__exit__", None)
        if callable(exit_m):
            _ = exit_m(*args)
        close = getattr(self.response, "close", None)
        if callable(close):
            _ = close()
