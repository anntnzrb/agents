"""Local, additive DeepSWE wire and value contracts.

The public CLI still owns dispatch.  This module only centralises the stable
wire constants and pure JSON/envelope helpers that later callers can adopt.
"""

# Copyright 2026 DeepSWE contributors.
from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

# The envelope is the existing DeepSWE protocol.  Keep this an integer: it is
# intentionally distinct from parser and artifact versions.
SCHEMA_VERSION = 1
ENVELOPE_SCHEMA_VERSION = SCHEMA_VERSION

# ``scope.value_status`` is a legacy nearest-scope field and deliberately
# remains three-valued in schema 1.  Value-level evidence uses VALUE_STATUSES.
SCOPE_VALUE_STATUSES = ("published", "published_raw", "derived")
VALUE_STATUSES = (*SCOPE_VALUE_STATUSES, "missing", "unparsed")

# A value can exist, have a meaning, and be usable for a comparison
# independently.  Keep the state vocabularies explicit and source-local.
SEMANTIC_STATUSES = ("known", "unknown", "ambiguous", "invalid", "placeholder")
METRIC_SEMANTICS_STATUSES = SEMANTIC_STATUSES
SEMANTIC_STATES = SEMANTIC_STATUSES
ELIGIBILITY_STATUSES = ("eligible", "blocked")
COMPARISON_ELIGIBILITY_STATUSES = ELIGIBILITY_STATUSES
ELIGIBILITY_STATES = ELIGIBILITY_STATUSES

# Phase 5 keeps overlap claims explicit: DeepSWE publishes none today.
DEPENDENCIES_DEFAULT: tuple[object, ...] = ()
INDEPENDENCE_CLASSES = ("unknown", "independent", "dependent", "overlapping")

# Stable additive field inventories advertised by ``schema``.
DIAGNOSTIC_FIELDS = (
    "code",
    "severity",
    "stage",
    "message",
    "source_path",
    "artifact_id",
    "details",
)
EVIDENCE_FIELDS = (
    "raw_value",
    "normalized_value",
    "unit",
    "normalization",
    "source_path",
    "source_field",
    "parser",
    "parser_version",
    "artifact_sha256",
    "value_status",
    "metric_semantics_status",
    "comparison_eligibility",
    "blocked_reasons",
)
COMPARISON_SEMANTIC_FIELDS = ("unit", "scope", "denominator")


def compact_json(value: object) -> str:
    """Return one compact JSON value and reject non-finite numbers.

    ``json.dumps(..., allow_nan=False)`` rejects NaN and both infinities at any
    depth while retaining ordinary strings (including strings containing words
    such as ``NaN``) exactly as strings.
    """
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


def success_envelope(command: str, data: Mapping[str, object]) -> dict[str, object]:
    """Build the legacy success envelope without renaming or adding keys."""
    return {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "command": command,
        "data": dict(data),
    }


def error_envelope(
    command: str,
    code: str,
    message: str,
    *,
    details: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Build the legacy error envelope with a lower-case error code.

    ``details`` is optional and additive.  When omitted, the historical
    ``error: {code, message}`` shape is emitted exactly.
    """
    normalized_code = str(code).strip().lower()
    if not normalized_code:
        msg = "error code must be non-empty"
        raise ValueError(msg)
    error: dict[str, object] = {
        "code": normalized_code,
        "message": str(message),
    }
    if details is not None:
        error["details"] = dict(details)
    return {
        "ok": False,
        "schema_version": SCHEMA_VERSION,
        "command": command,
        "error": error,
    }


def ensure_scope_status(status: str) -> str:
    """Validate a nearest-scope value status and return it unchanged."""
    if status not in SCOPE_VALUE_STATUSES:
        msg = f"unsupported scope value status: {status}"
        raise ValueError(msg)
    return status


def ensure_value_status(status: str) -> str:
    """Validate a value-level existence status and return it unchanged."""
    if status not in VALUE_STATUSES:
        msg = f"unsupported value status: {status}"
        raise ValueError(msg)
    return status


def ensure_semantic_status(status: str) -> str:
    """Validate a metric semantic state and return it unchanged."""
    if status not in SEMANTIC_STATUSES:
        msg = f"unsupported semantic status: {status}"
        raise ValueError(msg)
    return status


def ensure_eligibility(status: str) -> str:
    """Validate a comparison eligibility state and return it unchanged."""
    if status not in ELIGIBILITY_STATUSES:
        msg = f"unsupported comparison eligibility: {status}"
        raise ValueError(msg)
    return status


__all__ = [
    "COMPARISON_ELIGIBILITY_STATUSES",
    "COMPARISON_SEMANTIC_FIELDS",
    "DEPENDENCIES_DEFAULT",
    "DIAGNOSTIC_FIELDS",
    "ELIGIBILITY_STATES",
    "ELIGIBILITY_STATUSES",
    "ENVELOPE_SCHEMA_VERSION",
    "EVIDENCE_FIELDS",
    "INDEPENDENCE_CLASSES",
    "METRIC_SEMANTICS_STATUSES",
    "SCHEMA_VERSION",
    "SCOPE_VALUE_STATUSES",
    "SEMANTIC_STATES",
    "SEMANTIC_STATUSES",
    "VALUE_STATUSES",
    "compact_json",
    "ensure_eligibility",
    "ensure_scope_status",
    "ensure_semantic_status",
    "ensure_value_status",
    "error_envelope",
    "success_envelope",
]
