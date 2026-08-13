"""Source and value evidence projections for DeepSWE artifacts."""

# Copyright 2026 DeepSWE contributors.
from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence

from .diagnostics import redact

_UNSET = object()


def _read(value: object, *names: str) -> object | None:
    if isinstance(value, Mapping):
        for name in names:
            if name in value:
                return value[name]
        return None
    if value is not None:
        for name in names:
            candidate = getattr(value, name, None)
            if candidate is not None:
                return candidate
    return None


def _mapping(value: object) -> Mapping[str, object] | None:
    return value if isinstance(value, Mapping) else None


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _bytes(value: object) -> bytes | None:
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, memoryview):
        return value.tobytes()
    return None


def _integer(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _boolean(value: object, *, default: bool = False) -> bool:
    return value if isinstance(value, bool) else default


def _first(*values: object | None) -> object | None:
    for value in values:
        if value is not None:
            return value
    return None


def _header(headers: Mapping[str, object] | None, *names: str) -> object | None:
    if headers is None:
        return None
    lowered = {str(key).lower(): value for key, value in headers.items()}
    for name in names:
        value = lowered.get(name.lower())
        if value is not None:
            return value
    return None


def _mode(
    *,
    explicit: object | None,
    historical: bool,
    stale: bool,
    cache_reused: bool,
) -> str:
    if isinstance(explicit, str) and explicit:
        return explicit
    if historical:
        return "historical"
    if stale:
        return "stale"
    if cache_reused:
        return "revalidated"
    return "fresh"


def sha256_bytes(body: bytes | bytearray | memoryview) -> str:
    """Return the SHA-256 digest for exact artifact bytes."""
    raw = _bytes(body)
    if raw is None:  # pragma: no cover - guarded by the type and callers
        msg = "body must be bytes-like"
        raise TypeError(msg)
    return hashlib.sha256(raw).hexdigest()


def artifact_evidence(  # noqa: C901, PLR0912, PLR0913, PLR0915
    artifact: object = None,
    *,
    metadata: Mapping[str, object] | None = None,
    benchmark_version: str | None = None,
    version: str | None = None,
    url: str | None = None,
    source_url: str | None = None,
    discovered_from: str | None = None,
    final_url: str | None = None,
    fetched_at: str | None = None,
    timestamp: str | None = None,
    observed_at: str | None = None,
    generated_at: str | None = None,
    etag: str | None = None,
    last_modified: str | None = None,
    validator: object = None,
    headers: Mapping[str, object] | None = None,
    body: bytes | bytearray | memoryview | None = None,
    raw_bytes: bytes | bytearray | memoryview | None = None,
    artifact_sha256: str | None = None,
    sha256: str | None = None,
    byte_length: int | None = None,
    raw_bytes_ref: str | None = None,
    artifact_id: str | None = None,
    parser: str | None = None,
    parser_version: str | None = None,
    stale: bool | None = None,
    historical: bool | None = None,
    freshness_mode: str | None = None,
    freshness: str | None = None,
    cache_reused: bool | None = None,
    stale_reason: object = None,
    source_path: str | None = None,
) -> dict[str, object]:
    """Project transport, parser, hash, validator, and freshness evidence.

    ``artifact`` may be an existing metadata mapping/object, a URL string, or
    exact bytes.  Passing bytes computes the digest and byte length without
    retaining the body in the returned projection.
    """
    base: dict[str, object] = {}
    artifact_mapping = _mapping(artifact)
    if artifact_mapping is not None:
        base.update(artifact_mapping)
    if metadata is not None:
        base.update(metadata)

    body_value = _bytes(_first(body, raw_bytes))
    if body_value is None:
        body_value = _bytes(artifact)
    if body_value is None:
        body_value = _bytes(_read(base, "body", "raw_bytes"))

    if url is None and isinstance(artifact, str):
        url = artifact
    selected_url = _text(_first(url, source_url, _read(base, "url", "source_url")))
    selected_source_url = _text(
        _first(source_url, selected_url, _read(base, "source_url", "url"))
    )
    selected_discovered = _text(_first(discovered_from, _read(base, "discovered_from")))
    selected_final = _text(_first(final_url, _read(base, "final_url"), selected_url))
    selected_fetched = _text(
        _first(fetched_at, timestamp, _read(base, "fetched_at", "timestamp"))
    )
    selected_observed = _text(_first(observed_at, _read(base, "observed_at")))
    selected_generated = _text(_first(generated_at, _read(base, "generated_at")))

    validator_value = _first(validator, _read(base, "validator"))
    validator_mapping = _mapping(validator_value)
    validator_scalar = validator_value if validator_mapping is None else None

    header_mapping = headers or _mapping(_read(base, "headers"))
    selected_etag = _text(
        _first(
            etag,
            _read(base, "etag", "ETag"),
            _read(validator_mapping, "etag", "ETag", "value"),
            validator_scalar,
            _header(header_mapping, "etag", "ETag"),
        )
    )
    selected_last_modified = _text(
        _first(
            last_modified,
            _read(base, "last_modified", "Last-Modified"),
            _read(
                validator_mapping,
                "last_modified",
                "Last-Modified",
                "last-modified",
            ),
            _header(header_mapping, "last-modified", "Last-Modified"),
        )
    )

    digest = _text(
        _first(
            artifact_sha256,
            sha256,
            _read(base, "artifact_sha256", "sha256"),
        )
    )
    if digest is None and body_value is not None:
        digest = sha256_bytes(body_value)
    length = _integer(
        _first(
            byte_length,
            _read(base, "byte_length", "content_length"),
        )
    )
    if length is None and body_value is not None:
        length = len(body_value)
    selected_ref = _text(
        _first(
            raw_bytes_ref,
            _read(base, "raw_bytes_ref", "raw_reference", "local_path"),
        )
    )
    selected_version = _text(
        _first(
            benchmark_version,
            version,
            _read(base, "benchmark_version", "source_version", "release", "version"),
        )
    )
    selected_id = _text(_first(artifact_id, _read(base, "artifact_id")))
    if selected_id is None and digest is not None:
        prefix = f"deepswe:{selected_version}:" if selected_version else "deepswe:"
        selected_id = f"{prefix}sha256:{digest}"

    stale_flag = _boolean(
        _first(stale, _read(base, "stale")),
    )
    historical_flag = _boolean(
        _first(historical, _read(base, "historical", "snapshot")),
    )
    cache_flag = _boolean(
        _first(cache_reused, _read(base, "cache_reused")),
    )
    selected_freshness = _first(
        freshness_mode,
        freshness,
        _read(base, "freshness_mode", "mode"),
        _read(base, "freshness") if isinstance(_read(base, "freshness"), str) else None,
    )
    mode = _mode(
        explicit=selected_freshness,
        historical=historical_flag,
        stale=stale_flag,
        cache_reused=cache_flag,
    )

    selected_parser = _text(_first(parser, _read(base, "parser"))) or "deepswe.sources"
    selected_parser_version = (
        _text(_first(parser_version, _read(base, "parser_version"))) or "1"
    )
    result: dict[str, object] = {
        "url": selected_url,
        "source_url": selected_source_url,
        "discovered_from": selected_discovered,
        "final_url": selected_final,
        "fetched_at": selected_fetched,
        "observed_at": selected_observed,
        "generated_at": selected_generated,
        "etag": selected_etag,
        "ETag": selected_etag,
        "last_modified": selected_last_modified,
        "Last-Modified": selected_last_modified,
        "validators": {
            "etag": selected_etag,
            "last_modified": selected_last_modified,
        },
        "parser": selected_parser,
        "parser_version": selected_parser_version,
        "artifact_sha256": digest,
        "sha256": digest,
        "byte_length": length,
        "raw_bytes_ref": selected_ref,
        "artifact_id": selected_id,
        "freshness": mode,
        "freshness_mode": mode,
        "stale": stale_flag,
        "historical": historical_flag,
        "cache_reused": cache_flag,
    }
    if selected_version is not None:
        result["benchmark_version"] = selected_version
    if source_path is not None or _read(base, "source_path") is not None:
        result["source_path"] = _text(_first(source_path, _read(base, "source_path")))
    for key in (
        "benchmark",
        "benchmark_version",
        "artifact",
        "http_status",
        "status",
        "content_type",
        "local_path",
        "cache_path",
    ):
        value = _read(base, key)
        if value is not None and key not in result:
            result[key] = value
    selected_stale_reason = _first(stale_reason, _read(base, "stale_reason"))
    if selected_stale_reason is not None:
        result["stale_reason"] = selected_stale_reason
    redacted = redact(result)
    return dict(redacted) if isinstance(redacted, Mapping) else result


def value_evidence(  # noqa: PLR0913
    artifact: object = None,
    *,
    raw_value: object = _UNSET,
    normalized_value: object = _UNSET,
    unit: object = None,
    normalization: object = None,
    source_path: str | None = None,
    source_field: str | None = None,
    family: str | None = None,
    value_status: str = "published",
    metric_semantics_status: str = "known",
    comparison_eligibility: str = "eligible",
    blocked_reasons: Sequence[object] | str | None = None,
    missing_reason: str | None = None,
    parser: str = "deepswe.normalization",
    parser_version: str = "1",
    formula: str | None = None,
    input_paths: Sequence[str] | None = None,
) -> dict[str, object]:
    """Project one metric's raw value and complete source lineage.

    Missing and unparsed inputs remain explicit statuses with their raw value;
    this constructor never coerces an unavailable value to zero.
    """
    artifact_projection = artifact_evidence(artifact) if artifact is not None else {}
    reasons: list[object]
    if blocked_reasons is None:
        reasons = []
    elif isinstance(blocked_reasons, str):
        reasons = [blocked_reasons]
    else:
        reasons = list(blocked_reasons)
    deduped_reasons: list[object] = []
    for reason in reasons:
        if reason not in deduped_reasons:
            deduped_reasons.append(reason)

    result: dict[str, object] = {
        "raw_value": None if raw_value is _UNSET else raw_value,
        "normalized_value": None if normalized_value is _UNSET else normalized_value,
        "unit": unit,
        "normalization": normalization,
        "source_path": source_path,
        "source_field": source_field,
        "value_status": value_status,
        "metric_semantics_status": metric_semantics_status,
        "comparison_eligibility": comparison_eligibility,
        "blocked_reasons": deduped_reasons,
        "missing_reason": missing_reason,
        "parser": parser,
        "parser_version": parser_version,
    }
    if family is not None:
        result["family"] = family
    if formula is not None:
        result["formula"] = formula
    if input_paths is not None:
        result["input_paths"] = list(input_paths)

    for key in (
        "url",
        "source_url",
        "fetched_at",
        "observed_at",
        "generated_at",
        "etag",
        "ETag",
        "last_modified",
        "Last-Modified",
        "validators",
        "artifact_sha256",
        "sha256",
        "byte_length",
        "raw_bytes_ref",
        "artifact_id",
        "freshness",
        "freshness_mode",
        "stale",
        "historical",
        "cache_reused",
        "source_path",
        "benchmark",
        "benchmark_version",
        "artifact",
    ):
        if key in artifact_projection and key not in result:
            result[key] = artifact_projection[key]
    redacted = redact(result)
    return dict(redacted) if isinstance(redacted, Mapping) else result


__all__ = ["artifact_evidence", "sha256_bytes", "value_evidence"]
