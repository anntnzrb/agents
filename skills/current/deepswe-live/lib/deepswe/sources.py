"""DeepSWE published-artifact resolution, validation, and caching.

The source layer deliberately knows only about the two published JSON artifacts.  It
keeps HTTP/cache concerns here so callers can consume validated payloads without
having to infer which release or URL was used.
"""
# ruff: noqa: CPY001, FBT001, FBT002

from __future__ import annotations

import contextlib
import json
import os
import re
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from .cache import (
    ArtifactError,
    ArtifactIntegrityError,
    ArtifactNotFoundError,
    ArtifactStore,
)
from .validation import PayloadValidationError, inspect_payload


# A module-level hook keeps the transport injectable while still following any
# later monkeypatch of ``urllib.request.urlopen``.
class _ResponseLike(Protocol):
    status: int
    headers: object

    def read(self) -> bytes: ...

    def getcode(self) -> int: ...

    def close(self) -> None: ...


def urlopen(
    request: urllib_request.Request,
    timeout: float | None = None,
) -> _ResponseLike:
    """Open a request through the injectable stdlib transport."""
    if timeout is None:
        return urllib_request.urlopen(request)  # noqa: S310
    return urllib_request.urlopen(request, timeout=timeout)  # noqa: S310


DEFAULT_VERSION = "v1.1"
"""The deterministic release used when no version is supplied."""

DEEPSWE_DEFAULT_VERSION_ENV = "DEEPSWE_DEFAULT_VERSION"
ARTIFACT_BASE_URL = "https://deepswe.datacurve.ai/artifacts"
LEADERBOARD_ARTIFACT = "leaderboard-live.json"
HTTP_OK = 200
HTTP_NOT_MODIFIED = 304
TRIALS_ARTIFACT = "trials.json"
ARTIFACT_NAMES = (LEADERBOARD_ARTIFACT, TRIALS_ARTIFACT)

# A published release uses a leading ``v``.  Patch, prerelease, and build
# components are accepted so a future release does not require source changes.
_VERSION_RE = re.compile(
    r"^v(?P<major>0|[1-9][0-9]*)\."
    r"(?P<minor>0|[1-9][0-9]*)"
    r"(?:\.(?P<patch>0|[1-9][0-9]*))?"
    r"(?:-(?P<pre>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+(?P<build>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$",
)
_MAJOR_ONLY_RE = re.compile(r"^v?[0-9]+$")
_ARTIFACT_PATH_RE = re.compile(
    r"/artifacts/(?P<version>[^/]+)/(?P<artifact>[^/?#]+)$",
)
_METADATA_SUFFIX = ".meta.json"

JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]


class SourceError(ValueError):
    """A source, cache, transport, or artifact validation failure."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "source_error",
        status: int | None = None,
    ) -> None:
        """Initialize an error with its stable code and optional HTTP status."""
        super().__init__(message)
        self.code = code
        self.status = status


class VersionError(ValueError):
    """An unsupported or malformed DeepSWE release identifier."""

    def __init__(self, message: str, *, code: str = "invalid_version") -> None:
        """Initialize an error with its stable classification code."""
        super().__init__(message)
        self.code = code


def resolve_version(value: str | None) -> dict[str, object]:
    """Resolve and validate a DeepSWE release identifier.

    ``None`` (and the explicit ``latest`` alias) resolve through one deterministic
    source: ``DEEPSWE_DEFAULT_VERSION`` when non-empty, otherwise ``DEFAULT_VERSION``.
    Major-only identifiers such as ``v1`` are intentionally rejected; there is no
    legacy-v1 fallback.
    """
    if value is None:
        env_value = os.environ.get(DEEPSWE_DEFAULT_VERSION_ENV, "").strip()
        candidate = env_value or DEFAULT_VERSION
        resolved_from = "env" if env_value else "default"
        requested: str | None = None
    else:
        requested = value
        candidate = value.strip()
        if not candidate:
            message = "benchmark version must not be empty"
            raise VersionError(message)
        if candidate.lower() == "latest":
            env_value = os.environ.get(DEEPSWE_DEFAULT_VERSION_ENV, "").strip()
            candidate = env_value or DEFAULT_VERSION
            resolved_from = "env" if env_value else "default"
        else:
            resolved_from = "explicit"

    version = _validate_version(candidate)
    is_default = resolved_from in {"env", "default"}
    return {
        "benchmark": "DeepSWE",
        "benchmark_version": version,
        "version": version,
        "requested": requested,
        "resolved_from": resolved_from,
        "source": resolved_from,
        "is_default": is_default,
    }


def fetch_artifacts(  # noqa: PLR0913, PLR0917
    version: str | Mapping[str, object] | None,
    output_dir: str | os.PathLike[str],
    cache_dir: str | os.PathLike[str],
    include_trials: bool = False,
    timeout: float | None = 30,
    allow_stale: bool = False,
) -> dict[str, object]:
    """Fetch and validate the published DeepSWE artifacts.

    The leaderboard is always requested.  ``trials.json`` is requested only when
    ``include_trials`` is true.  Existing validators are sent as conditional
    headers; a 304 reuses the exact cached bytes.  A stale cache is considered only
    when ``allow_stale`` is explicitly true and the network response cannot be
    used, and the returned metadata records why it is stale.
    """
    benchmark_version = _coerce_version(version)
    output_root = Path(output_dir).expanduser()
    cache_root = Path(cache_dir).expanduser()
    if timeout is not None and timeout <= 0:
        message = "timeout must be positive or None"
        raise ValueError(message)

    artifacts: dict[str, dict[str, object]] = {}
    for artifact_name in (
        (LEADERBOARD_ARTIFACT, TRIALS_ARTIFACT)
        if include_trials
        else (LEADERBOARD_ARTIFACT,)
    ):
        artifact_result = _fetch_one(
            benchmark_version,
            artifact_name,
            output_root,
            cache_root,
            timeout,
            allow_stale,
        )
        artifacts[artifact_name] = artifact_result

    sources = {
        name: {key: value for key, value in metadata.items() if key != "data"}
        for name, metadata in artifacts.items()
    }
    payloads = {name: metadata["data"] for name, metadata in artifacts.items()}
    row_counts = {name: metadata["row_count"] for name, metadata in artifacts.items()}
    local_paths = {name: metadata["local_path"] for name, metadata in artifacts.items()}
    generated_at_values = {
        str(metadata["generated_at"])
        for metadata in artifacts.values()
        if metadata.get("generated_at") is not None
    }

    result: dict[str, object] = {
        "benchmark": "DeepSWE",
        "benchmark_version": benchmark_version,
        "version": benchmark_version,
        "include_trials": include_trials,
        "artifacts": artifacts,
        "sources": sources,
        "provenance": sources,
        "payloads": payloads,
        "row_counts": row_counts,
        "local_paths": local_paths,
        "cache_reused": all(
            bool(metadata["cache_reused"]) for metadata in artifacts.values()
        ),
        "stale": any(bool(metadata["stale"]) for metadata in artifacts.values()),
    }
    # Keep the common payloads available under their natural names for analysis
    # callers while retaining a filename-keyed artifact map for provenance.
    result["leaderboard"] = payloads[LEADERBOARD_ARTIFACT]
    if include_trials:
        result["trials"] = payloads[TRIALS_ARTIFACT]
    if len(generated_at_values) == 1:
        result["generated_at"] = next(iter(generated_at_values))
    return result


def load_artifact(path: str | os.PathLike[str]) -> dict[str, object]:
    """Load and validate one local DeepSWE JSON artifact.

    The returned mapping is the artifact payload itself (including its ``rows``),
    not a cache/provenance wrapper.  A version component in the path and an
    observable ``benchmark_version``/``version`` field in the payload must agree.
    """
    artifact_path = Path(path).expanduser()
    try:
        raw = artifact_path.read_bytes()
    except OSError as exc:
        message = f"unable to read artifact {artifact_path}: {exc}"
        raise SourceError(message, code="artifact_read_failed") from exc
    payload = _decode_payload(raw, artifact_path)
    version = _version_from_path(artifact_path)
    expected_artifact = (
        artifact_path.name if artifact_path.name in ARTIFACT_NAMES else None
    )
    _validate_payload(
        payload,
        expected_artifact,
        version,
        artifact_path,
    )
    return payload


def _fetch_one(  # noqa: C901, PLR0912, PLR0913, PLR0915, PLR0917
    version: str,
    artifact_name: str,
    output_root: Path,
    cache_root: Path,
    timeout: float | None,
    allow_stale: bool,
) -> dict[str, object]:
    url = _artifact_url(version, artifact_name)
    output_path = output_root / version / artifact_name
    cache_path = cache_root / version / artifact_name
    metadata_path = _metadata_path(cache_path)
    artifact_store = ArtifactStore(cache_root)
    cached = _read_cached(
        cache_path,
        metadata_path,
        version,
        artifact_name,
        url,
        artifact_store,
    )
    headers: dict[str, str] = {"Accept": "application/json"}
    if cached is not None:
        etag = _metadata_validator(cached.metadata, "etag")
        last_modified = _metadata_validator(cached.metadata, "last_modified")
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified
    conditional_request = any(
        key in headers for key in ("If-None-Match", "If-Modified-Since")
    )

    request = urllib_request.Request(url, headers=headers, method="GET")  # noqa: S310
    attempted_at = _utc_now()
    try:
        response = urlopen(request, timeout=timeout)
        try:
            status = _response_status(response)
            _validate_response_url(response, version, artifact_name)
            response_headers = _response_headers(response)
            if status == HTTP_NOT_MODIFIED:
                _validate_304(
                    cached,
                    response_headers,
                    conditional_request=conditional_request,
                    artifact_name=artifact_name,
                )
                return _materialize_cached(
                    cached,
                    output_path,
                    version,
                    artifact_name,
                    url,
                    status=HTTP_NOT_MODIFIED,
                    response_headers=response_headers,
                    fetched_at=attempted_at,
                    stale=False,
                )
            if status != HTTP_OK:
                message = f"unexpected HTTP status {status} for {url}"
                raise SourceError(message, code="http_error", status=status)
            body = response.read()
            if isinstance(body, str):
                body = body.encode("utf-8")
            elif not isinstance(body, bytes):
                body = bytes(body)
            payload = _decode_payload(body, cache_path)
            _validate_payload(payload, artifact_name, version, cache_path)
            etag = _header(response_headers, "ETag")
            last_modified = _header(response_headers, "Last-Modified")
            metadata = _new_metadata(
                version=version,
                artifact_name=artifact_name,
                url=url,
                local_path=output_path,
                cache_path=cache_path,
                fetched_at=attempted_at,
                status=status,
                etag=etag,
                last_modified=last_modified,
                payload=payload,
                cache_reused=False,
                stale=False,
            )
            metadata.update(
                _store_immutable(
                    artifact_store,
                    source_key=url,
                    raw=body,
                    metadata=metadata,
                )
            )
            _atomic_write(cache_path, body)
            _atomic_write_json(metadata_path, metadata)
            _atomic_write(output_path, body)
            return {**metadata, "data": payload}
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()
    except urllib_error.HTTPError as exc:
        status = int(exc.code)
        _validate_response_url(exc, version, artifact_name)
        response_headers = _message_headers(exc.headers)
        # urllib may surface a conditional 304 as HTTPError rather than a normal
        # response.  Treat it exactly like a regular 304 response.
        if status == HTTP_NOT_MODIFIED:
            _validate_304(
                cached,
                response_headers,
                conditional_request=conditional_request,
                artifact_name=artifact_name,
            )
            return _materialize_cached(
                cached,
                output_path,
                version,
                artifact_name,
                url,
                status=HTTP_NOT_MODIFIED,
                response_headers=response_headers,
                fetched_at=attempted_at,
                stale=False,
            )
        message = f"HTTP {status} while fetching {url}"
        failure = SourceError(message, code="http_error", status=status)
        return _stale_or_raise(
            cached,
            output_path,
            version,
            artifact_name,
            url,
            attempted_at,
            failure,
            allow_stale,
        )
    except (
        urllib_error.URLError,
        TimeoutError,
        OSError,
        SourceError,
        ValueError,
    ) as exc:
        if isinstance(exc, SourceError):
            failure = exc
        else:
            message = f"unable to fetch {url}: {exc}"
            failure = SourceError(message, code="network_error")
        return _stale_or_raise(
            cached,
            output_path,
            version,
            artifact_name,
            url,
            attempted_at,
            failure,
            allow_stale,
        )


def _validate_304(
    cached: _CachedArtifact | None,
    response_headers: Mapping[str, str],
    *,
    conditional_request: bool,
    artifact_name: str,
) -> None:
    if cached is None:
        message = f"304 for {artifact_name} without a valid cache entry"
        raise SourceError(message, code="cache_missing", status=HTTP_NOT_MODIFIED)
    if not conditional_request:
        message = f"304 for {artifact_name} without a cache validator"
        raise SourceError(message, code="cache_invalid", status=HTTP_NOT_MODIFIED)
    cached_etag = _metadata_validator(cached.metadata, "etag")
    cached_last_modified = _metadata_validator(cached.metadata, "last_modified")
    if cached_etag is None and cached_last_modified is None:
        message = f"304 for {artifact_name} without a cached validator"
        raise SourceError(message, code="cache_invalid", status=HTTP_NOT_MODIFIED)
    response_etag = _header(response_headers, "ETag")
    response_last_modified = _header(response_headers, "Last-Modified")
    if response_etag is None and response_last_modified is None:
        message = f"304 for {artifact_name} without a response validator"
        raise SourceError(message, code="cache_invalid", status=HTTP_NOT_MODIFIED)
    if response_etag is not None and (
        cached_etag is None or response_etag != cached_etag
    ):
        message = f"304 ETag did not match cached {artifact_name}"
        raise SourceError(message, code="cache_invalid", status=HTTP_NOT_MODIFIED)
    if response_last_modified is not None and (
        cached_last_modified is None or response_last_modified != cached_last_modified
    ):
        message = f"304 Last-Modified did not match cached {artifact_name}"
        raise SourceError(message, code="cache_invalid", status=HTTP_NOT_MODIFIED)


def _metadata_validator(
    metadata: Mapping[str, object],
    name: str,
) -> str | None:
    return _nonempty_string(metadata.get(name)) or _nonempty_string(
        metadata.get(
            "ETag" if name == "etag" else "Last-Modified",
        ),
    )


def _stale_or_raise(  # noqa: PLR0913, PLR0917
    cached: _CachedArtifact | None,
    output_path: Path,
    version: str,
    artifact_name: str,
    url: str,
    fetched_at: str,
    failure: SourceError,
    allow_stale: bool,
) -> dict[str, object]:
    if (
        allow_stale
        and cached is not None
        and failure.code not in {"cache_invalid", "cache_missing", "version_mismatch"}
    ):
        return _materialize_cached(
            cached,
            output_path,
            version,
            artifact_name,
            url,
            status=failure.status,
            response_headers={},
            fetched_at=fetched_at,
            stale=True,
            stale_reason=f"{failure.code}: {failure}",
        )
    raise failure


class _CachedArtifact:
    """Validated cached artifact bytes, metadata, and payload."""

    def __init__(
        self,
        payload: dict[str, object],
        raw: bytes,
        metadata: Mapping[str, object],
        path: Path,
        immutable: Mapping[str, object] | None = None,
    ) -> None:
        """Store the cached payload and its filesystem metadata."""
        self.payload = payload
        self.raw = raw
        self.metadata = metadata
        self.path = path
        self.immutable = dict(immutable or {})


def _read_cached(  # noqa: PLR0913, PLR0917
    cache_path: Path,
    metadata_path: Path,
    version: str,
    artifact_name: str,
    url: str,
    artifact_store: ArtifactStore,
) -> _CachedArtifact | None:
    legacy = _read_legacy_cached(
        cache_path,
        metadata_path,
        version,
        artifact_name,
        url,
    )
    immutable = _read_immutable_cached(
        artifact_store,
        cache_path=cache_path,
        version=version,
        artifact_name=artifact_name,
        url=url,
    )
    if immutable is not None:
        if legacy is not None:
            metadata = dict(legacy.metadata)
        else:
            metadata = dict(immutable.metadata)
        metadata.update(immutable.metadata)
        return _CachedArtifact(
            immutable.payload,
            immutable.raw,
            metadata,
            cache_path,
            immutable.immutable,
        )
    if legacy is None:
        return None
    return _promote_legacy(
        artifact_store,
        legacy,
        version=version,
        artifact_name=artifact_name,
        url=url,
        cache_path=cache_path,
    )


def _read_legacy_cached(
    cache_path: Path,
    metadata_path: Path,
    version: str,
    artifact_name: str,
    url: str,
) -> _CachedArtifact | None:
    if not cache_path.is_file() or not metadata_path.is_file():
        return None
    try:
        metadata_value = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(metadata_value, dict):
        return None
    metadata: dict[str, object] = metadata_value
    if (
        metadata.get("benchmark_version") != version
        or metadata.get("artifact") != artifact_name
        or metadata.get("url") != url
    ):
        return None
    try:
        raw = cache_path.read_bytes()
        payload = _decode_payload(raw, cache_path)
        _validate_payload(payload, artifact_name, version, cache_path)
    except (OSError, UnicodeError, SourceError, ValueError):
        return None
    metadata.setdefault("row_count", len(payload["rows"]))
    metadata.setdefault("status", metadata.get("http_status"))
    return _CachedArtifact(payload, raw, metadata, cache_path)


def _read_immutable_cached(
    artifact_store: ArtifactStore,
    *,
    cache_path: Path,
    version: str,
    artifact_name: str,
    url: str,
) -> _CachedArtifact | None:
    if not artifact_store.index_path.exists():
        if _has_entries(artifact_store.artifacts) or _has_entries(
            artifact_store.manifests
        ):
            message = f"immutable cache index is missing for {url}"
            raise SourceError(message, code="cache_invalid")
        return None
    try:
        raw, record = artifact_store.load(source_key=url)
        manifest = artifact_store.write_manifest()
    except ArtifactNotFoundError:
        return None
    except (ArtifactError, OSError, ValueError) as exc:
        message = f"immutable cache is invalid for {url}: {exc}"
        raise SourceError(message, code="cache_invalid") from exc
    try:
        payload = _decode_payload(raw, cache_path)
        _validate_payload(payload, artifact_name, version, cache_path)
    except (SourceError, ValueError) as exc:
        message = f"immutable cache payload is invalid for {url}: {exc}"
        raise SourceError(message, code="cache_invalid") from exc
    nested = record.get("metadata")
    if not isinstance(nested, Mapping):
        message = f"immutable cache metadata is invalid for {url}"
        raise SourceError(message, code="cache_invalid")
    metadata = dict(nested)
    if (
        metadata.get("benchmark_version") not in {None, version}
        or metadata.get("artifact") not in {None, artifact_name}
        or metadata.get("url") not in {None, url}
    ):
        message = f"immutable cache source identity mismatch for {url}"
        raise SourceError(message, code="cache_invalid")
    immutable = _immutable_fields(record, manifest)
    metadata.update(immutable)
    return _CachedArtifact(payload, raw, metadata, cache_path, immutable)


def _promote_legacy(  # noqa: PLR0913
    artifact_store: ArtifactStore,
    legacy: _CachedArtifact,
    *,
    version: str,
    artifact_name: str,
    url: str,
    cache_path: Path,
) -> _CachedArtifact:
    metadata = dict(legacy.metadata)
    metadata["legacy_path"] = str(cache_path)
    try:
        record = artifact_store.promote_legacy(url, legacy.raw, metadata)
        raw, persisted = artifact_store.load(source_key=url)
        manifest = artifact_store.write_manifest()
    except (ArtifactError, OSError, ValueError) as exc:
        message = f"unable to promote legacy cache for {url}: {exc}"
        raise SourceError(message, code="cache_invalid") from exc
    try:
        payload = _decode_payload(raw, cache_path)
        _validate_payload(payload, artifact_name, version, cache_path)
    except (SourceError, ValueError) as exc:
        message = f"promoted cache payload is invalid for {url}: {exc}"
        raise SourceError(message, code="cache_invalid") from exc
    nested = persisted.get("metadata")
    merged = dict(nested) if isinstance(nested, Mapping) else metadata
    immutable = _immutable_fields(record, manifest)
    merged.update(immutable)
    return _CachedArtifact(payload, raw, merged, cache_path, immutable)


def _store_immutable(
    artifact_store: ArtifactStore,
    *,
    source_key: str,
    raw: bytes,
    metadata: Mapping[str, object],
) -> dict[str, object]:
    try:
        record = artifact_store.store(source_key, raw, metadata)
        manifest = artifact_store.write_manifest()
    except ArtifactIntegrityError as exc:
        message = f"immutable cache is invalid for {source_key}: {exc}"
        raise SourceError(message, code="cache_invalid") from exc
    except (ArtifactError, OSError, ValueError) as exc:
        message = f"unable to write immutable cache for {source_key}: {exc}"
        raise SourceError(message, code="cache_write_failed") from exc
    return _immutable_fields(record, manifest)


def _immutable_fields(
    record: Mapping[str, object],
    manifest: Mapping[str, object],
) -> dict[str, object]:
    digest = record.get("sha256")
    raw_path = record.get("raw_path")
    metadata_path = record.get("metadata_path")
    manifest_path = manifest.get("path")
    return {
        "sha256": digest,
        "artifact_sha256": digest,
        "length": record.get("length"),
        "raw_path": raw_path,
        "metadata_path": metadata_path,
        "artifact_ref": raw_path,
        "manifest_sha256": manifest.get("manifest_sha256", manifest.get("sha256")),
        "manifest_path": manifest_path,
        "manifest_ref": manifest_path,
        "legacy_unverified": record.get("legacy_unverified"),
    }


def _has_entries(path: Path) -> bool:
    if not path.exists():
        return False
    if path.is_file():
        return True
    try:
        return any(path.iterdir())
    except OSError as exc:
        message = f"unable to inspect immutable cache path {path}: {exc}"
        raise SourceError(message, code="cache_invalid") from exc


def _materialize_cached(  # noqa: PLR0913
    cached: _CachedArtifact,
    output_path: Path,
    version: str,
    artifact_name: str,
    url: str,
    *,
    status: int | None,
    response_headers: Mapping[str, str],
    fetched_at: str,
    stale: bool,
    stale_reason: str | None = None,
) -> dict[str, object]:
    metadata = dict(cached.metadata)
    if cached.immutable:
        metadata.update(cached.immutable)
    original_fetched_at = _nonempty_string(metadata.get("fetched_at"))
    metadata.update(
        {
            "benchmark": "DeepSWE",
            "benchmark_version": version,
            "artifact": artifact_name,
            "url": url,
            "local_path": str(output_path),
            "cache_path": str(cached.path),
            "fetched_at": original_fetched_at
            if stale and original_fetched_at
            else fetched_at,
            "http_status": status,
            "status": status,
            "cache_reused": True,
            "stale": stale,
        },
    )
    etag = _header(response_headers, "ETag") or _metadata_validator(
        metadata,
        "etag",
    )
    last_modified = _header(
        response_headers,
        "Last-Modified",
    ) or _metadata_validator(metadata, "last_modified")
    metadata["etag"] = etag
    metadata["last_modified"] = last_modified
    metadata["ETag"] = etag
    metadata["Last-Modified"] = last_modified
    if stale_reason is not None:
        metadata["stale_reason"] = stale_reason
    else:
        metadata.pop("stale_reason", None)
    if not stale and cached.immutable.get("legacy_unverified") is not True:
        _atomic_write_json(_metadata_path(cached.path), metadata)
    _atomic_write(output_path, cached.raw)
    return {**metadata, "data": cached.payload}


def _new_metadata(  # noqa: PLR0913
    *,
    version: str,
    artifact_name: str,
    url: str,
    local_path: Path,
    cache_path: Path,
    fetched_at: str,
    status: int | None,
    etag: str | None,
    last_modified: str | None,
    payload: Mapping[str, object],
    cache_reused: bool,
    stale: bool,
) -> dict[str, object]:
    generated_at = payload.get("generated_at")
    metadata: dict[str, object] = {
        "schema_version": 1,
        "benchmark": "DeepSWE",
        "benchmark_version": version,
        "artifact": artifact_name,
        "url": url,
        "fetched_at": fetched_at,
        "http_status": status,
        "status": status,
        "etag": etag,
        "ETag": etag,
        "last_modified": last_modified,
        "Last-Modified": last_modified,
        "generated_at": generated_at if isinstance(generated_at, str) else None,
        "row_count": len(payload["rows"]),
        "n_rows": len(payload["rows"]),
        "local_path": str(local_path),
        "cache_path": str(cache_path),
        "cache_reused": cache_reused,
        "stale": stale,
    }
    return metadata


def _decode_payload(raw: bytes, path: Path) -> dict[str, object]:
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        message = f"malformed JSON artifact {path}: {exc}"
        raise SourceError(message, code="malformed_json") from exc
    if not isinstance(decoded, dict):
        message = f"artifact {path} must contain a JSON object"
        raise SourceError(message, code="invalid_artifact_shape")
    payload: dict[str, object] = decoded
    return payload


def _validate_payload(
    payload: Mapping[str, object],
    artifact_name: str | None,
    expected_version: str | None,
    path: Path,
) -> None:
    """Validate an artifact through the source-local strict boundary."""
    try:
        inspect_payload(
            payload,
            artifact_name=artifact_name,
            expected_version=expected_version,
            path=path,
        )
    except PayloadValidationError as exc:
        raise SourceError(str(exc), code=exc.code) from exc


def _coerce_version(value: str | Mapping[str, object] | None) -> str:
    if isinstance(value, Mapping):
        declared_benchmark = value.get("benchmark")
        if declared_benchmark is not None and declared_benchmark != "DeepSWE":
            message = (
                f"version mapping declares benchmark {declared_benchmark!r}, "
                "expected 'DeepSWE'"
            )
            raise SourceError(message, code="benchmark_mismatch")
        candidate = value.get("benchmark_version", value.get("version"))
        if not isinstance(candidate, str):
            message = "version mapping must contain benchmark_version"
            raise VersionError(message)
        return _validate_version(candidate)
    return str(resolve_version(value)["benchmark_version"])


def _validate_version(value: str) -> str:
    candidate = value.strip()
    if _MAJOR_ONLY_RE.fullmatch(candidate):
        message = (
            f"major-only version {candidate!r} is unsupported; "
            "use a semantic release such as v1.1"
        )
        raise VersionError(message, code="major_only_version")
    match = _VERSION_RE.fullmatch(candidate)
    if match is None:
        message = f"invalid DeepSWE version {value!r}; expected vMAJOR.MINOR[.PATCH]"
        raise VersionError(message)
    major = int(match.group("major"))
    minor = int(match.group("minor"))
    if major < 1 or (major == 1 and minor < 1):
        message = "legacy DeepSWE releases before v1.1 are unsupported"
        raise VersionError(message, code="legacy_version")
    return candidate


def _artifact_url(version: str, artifact_name: str) -> str:
    if artifact_name not in ARTIFACT_NAMES:
        message = f"unsupported DeepSWE artifact {artifact_name!r}"
        raise ValueError(message)
    return f"{ARTIFACT_BASE_URL.rstrip('/')}/{version}/{artifact_name}"


def _version_from_path(path: Path) -> str | None:
    found: list[str] = []
    for index, component in enumerate(path.parts):
        is_artifact_parent = index == len(path.parts) - 2
        is_artifact_base_child = (
            index > 0 and path.parts[index - 1].lower() == "artifacts"
        )
        if component.lower() == "latest" and (
            is_artifact_parent or is_artifact_base_child
        ):
            message = f"artifact path {path} must use a concrete benchmark version"
            raise SourceError(message, code="invalid_version")
        if _MAJOR_ONLY_RE.fullmatch(component) and (
            is_artifact_parent or is_artifact_base_child
        ):
            message = (
                f"artifact path {path} contains unsupported major-only "
                f"version {component!r}"
            )
            raise SourceError(message, code="major_only_version")
        if _VERSION_RE.fullmatch(component):
            found.append(_validate_version(component))
    if not found:
        return None
    if len(set(found)) != 1:
        message = f"artifact path {path} contains mixed benchmark versions"
        raise SourceError(message, code="version_mismatch")
    return found[0]


def _validate_response_url(
    response: object,
    expected_version: str,
    expected_artifact: str,
) -> None:
    geturl = getattr(response, "geturl", None)
    if not callable(geturl):
        return
    final_url = geturl()
    if not isinstance(final_url, str) or not final_url:
        return
    path = urllib_parse.urlsplit(final_url).path
    match = _ARTIFACT_PATH_RE.search(path)
    if match is None or (
        match.group("version") != expected_version
        or match.group("artifact") != expected_artifact
    ):
        message = (
            f"redirected artifact URL {final_url!r} does not match requested "
            f"{expected_version}/{expected_artifact}"
        )
        raise SourceError(message, code="version_mismatch")


def _response_status(response: object) -> int:
    value = getattr(response, "status", None)
    if value is None:
        getcode = getattr(response, "getcode", None)
        value = getcode() if callable(getcode) else None
    if value is None:
        return HTTP_OK
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        message = "HTTP response had an invalid status"
        raise SourceError(message, code="http_error") from exc


def _response_headers(response: object) -> Mapping[str, str]:
    headers = getattr(response, "headers", None)
    return _message_headers(headers)


def _message_headers(headers: object) -> Mapping[str, str]:
    if headers is None:
        return {}
    if isinstance(headers, Mapping):
        return {str(key): str(value) for key, value in headers.items()}
    items = getattr(headers, "items", None)
    if callable(items):
        return {str(key): str(value) for key, value in items()}
    return {}


def _header(headers: Mapping[str, str], name: str) -> str | None:
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted and value:
            return str(value)
    return None


def _nonempty_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _metadata_path(cache_path: Path) -> Path:
    return cache_path.with_name(cache_path.name + _METADATA_SUFFIX)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    except OSError as exc:
        message = f"unable to write {path}: {exc}"
        raise SourceError(message, code="cache_write_failed") from exc
    finally:
        if temporary is not None and temporary.exists():
            with contextlib.suppress(OSError):
                temporary.unlink()


def _atomic_write_json(path: Path, value: Mapping[str, object]) -> None:
    try:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8",
        )
    except (TypeError, ValueError) as exc:
        message = f"unable to serialize cache metadata for {path}: {exc}"
        raise SourceError(message, code="cache_write_failed") from exc
    _atomic_write(path, encoded)
