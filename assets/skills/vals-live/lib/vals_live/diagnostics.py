# Copyright 2026 Vals-live contributors.
"""Stable diagnostics and redaction helpers."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

CODES = {
    "SOURCE_UNAVAILABLE",
    "SOURCE_AUTH_REQUIRED",
    "REQUIRES_RENDERED_SOURCE",
    "RELEASE_NOT_FOUND",
    "MIXED_RELEASE",
    "STALE_DATA",
    "HISTORICAL_SNAPSHOT",
    "RELEASE_DISCOVERY_LIMITED",
    "DUPLICATE_SOURCE_FIELD",
    "CACHE_MISSING",
    "CACHE_VALIDATOR_INVALID",
    "MALFORMED_PAYLOAD",
    "SCHEMA_DRIFT",
    "UNKNOWN_SCORE_SEMANTICS",
    "UNKNOWN_CATEGORY",
    "PLACEHOLDER_VALUE",
    "NUMERIC_AMBIGUITY",
    "OUT_OF_RANGE",
    "DUPLICATE_MODEL_VARIANT",
    "MISSING_REQUIRED_IDENTITY",
    "PARTIAL_EXTRACTION",
    "SNAPSHOT_INVALID",
    "MODEL_NOT_FOUND",
    "BENCHMARK_NOT_FOUND",
    "COMPARISON_INCOMPARABLE",
    "OVERLAP_DOUBLE_COUNTING_RISK",
    "SOURCE_REDIRECT_MISMATCH",
}

_SECRET_KEYS = re.compile(
    r"(?i)(authorization|cookie|set-cookie|x-api-key|api[-_]?key|token|password|secret)"
)
_SECRET_VALUES = re.compile(
    r"(?i)(bearer\s+[^\s,;]+|"
    r"sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9_]{10,}|"
    r"-----BEGIN .*PRIVATE KEY-----)"
)
_SECRET_QUERY = re.compile(
    r"(?i)([?&](?:api[-_]?key|access_token|token|secret|password|authorization|credential)=[^&#\s]+)"
)


def redact(value: object) -> object:
    """Recursively remove credentials from diagnostic/provenance data."""
    if isinstance(value, Mapping):
        out: dict[str, object] = {}
        for key, item in value.items():
            name = str(key)
            if _SECRET_KEYS.search(name):
                out[name] = "<redacted>"
            else:
                out[name] = redact(item)
        return out
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return [redact(item) for item in value]
    if isinstance(value, str):
        if _SECRET_VALUES.search(value):
            return "<redacted>"
        return _SECRET_QUERY.sub(
            lambda match: match.group(1).split("=", 1)[0] + "=<redacted>", value
        )
    return value


def make(code: str, message: str, **kwargs: object) -> dict[str, object]:
    """Create one redacted, schema-valid diagnostic."""
    severity = str(kwargs.get("severity", "warning"))
    stage = str(kwargs.get("stage", "validate"))
    source_path_value = kwargs.get("source_path")
    source_path = source_path_value if isinstance(source_path_value, str) else None
    artifact_value = kwargs.get("artifact_id")
    artifact_id = artifact_value if isinstance(artifact_value, str) else None
    details_value = kwargs.get("details")
    details = details_value if isinstance(details_value, Mapping) else {}
    if code not in CODES:
        code = "SCHEMA_DRIFT"
    result: dict[str, object] = {
        "code": code,
        "severity": severity,
        "stage": stage,
        "message": message,
        "details": redact(dict(details)),
    }
    if source_path is not None:
        result["source_path"] = source_path
    if artifact_id is not None:
        result["artifact_id"] = artifact_id
    return result


def codes(diags: Iterable[Mapping[str, object]]) -> list[str]:
    """Extract stable diagnostic codes."""
    return [str(d.get("code")) for d in diags]


def has_error(diags: Iterable[Mapping[str, object]]) -> bool:
    """Return whether any diagnostic is an error."""
    return any(str(d.get("severity")) == "error" for d in diags)


def merge(*groups: Iterable[Mapping[str, object]]) -> list[dict[str, object]]:
    """Merge diagnostics while preserving first-seen order."""
    result: list[dict[str, object]] = []
    seen: set[tuple[object, ...]] = set()
    for group in groups:
        for item in group:
            normalized = redact(dict(item))
            if not isinstance(normalized, dict):
                continue
            key = (
                normalized.get("code"),
                normalized.get("stage"),
                normalized.get("source_path"),
                normalized.get("message"),
            )
            if key not in seen:
                seen.add(key)
                result.append(normalized)
    return result


def warning(code: str, message: str, **kwargs: object) -> dict[str, object]:
    """Create a warning diagnostic."""
    return make(code, message, severity="warning", **kwargs)


def blocker(code: str, message: str, **kwargs: object) -> dict[str, object]:
    """Create a blocking diagnostic."""
    return make(code, message, severity="blocker", **kwargs)


def error(code: str, message: str, **kwargs: object) -> dict[str, object]:
    """Create an error diagnostic."""
    return make(code, message, severity="error", **kwargs)
