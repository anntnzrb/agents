# Copyright (c) 2026
"""Stable diagnostics and redaction helpers."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import cast

from .contracts import Diagnostic

CODES = frozenset(
    {
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
        "COMPARISON_INCOMPARABLE",
        "OVERLAP_DOUBLE_COUNTING_RISK",
        "CACHE_WRITE_FAILED",
    }
)

_SECRET_KEYS = re.compile(
    r"(?i)(authorization|cookie|set-cookie|x-api-key|api[-_]?key|token|secret|password)"
)
_BEARER = re.compile(r"(?i)\b(?:bearer|basic)\s+[^\s,;]+")
_QUERY_SECRET = re.compile(
    r"(?i)([?&](?:authorization|cookie|token|secret|password|api[-_]?key)=)[^&#\s]+"
)


def redact_text(value: str) -> str:
    """Redact text for the LiveBench adapter."""
    value = _BEARER.sub("<redacted>", value)
    value = _QUERY_SECRET.sub(r"\1<redacted>", value)
    return value.replace("Authorization:", "Authorization: <redacted>").replace(
        "Cookie:", "Cookie: <redacted>"
    )


def redact(value: object, *, key: str | None = None) -> object:
    """Redact for the LiveBench adapter."""
    if key is not None and _SECRET_KEYS.search(key):
        return "<redacted>"
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        mapping = cast("Mapping[str, object]", value)
        return {str(k): redact(v, key=str(k)) for k, v in mapping.items()}
    if isinstance(value, list):
        items = cast("list[object]", cast("object", value))
        return [redact(item) for item in items]
    if isinstance(value, tuple):
        entries = cast("tuple[object, ...]", cast("object", value))
        return [redact(item) for item in entries]
    return value


def make_diagnostic(  # noqa: PLR0913
    code: str,
    message: str,
    *,
    severity: str = "warning",
    stage: str = "validate",
    source: str | None = None,
    artifact: str | None = None,
    path: str | None = None,
    details: Mapping[str, object] | None = None,
) -> Diagnostic:
    """Make diagnostic for the LiveBench adapter."""
    if code not in CODES:
        # Unknown upstream signals are still visible but remain uppercase and stable.
        code = code.upper().replace("-", "_")
    source_details: dict[str, object] = dict(details) if details is not None else {}
    safe = redact(source_details)
    safe_details = cast("dict[str, object]", safe) if isinstance(safe, dict) else {}
    return Diagnostic(
        code,
        severity,
        stage,
        redact_text(message),
        source,
        artifact,
        path,
        safe_details,
    )


def diagnostics_dict(items: Iterable[Diagnostic]) -> list[dict[str, object]]:
    """Diagnostics dict for the LiveBench adapter."""
    return [item.as_dict() for item in items]


def codes(items: Iterable[Diagnostic]) -> list[str]:
    """Codes for the LiveBench adapter."""
    return sorted({item.code for item in items})


def has_error(items: Iterable[Diagnostic]) -> bool:
    """Has error for the LiveBench adapter."""
    return any(item.severity == "error" for item in items)


def has_blocker(items: Iterable[Diagnostic]) -> bool:
    """Has blocker for the LiveBench adapter."""
    return any(item.severity == "blocker" for item in items)
