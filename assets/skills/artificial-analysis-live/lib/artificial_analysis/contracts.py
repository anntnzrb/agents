# Copyright (c) 2026 anntnzrb
"""Small, source-local contracts for Artificial Analysis data.

The live skill has a deliberately tiny wire contract.  This module owns the
values which are useful to both the parser and callers without importing any
other skill or transport implementation.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field, fields, is_dataclass
from decimal import Decimal
from enum import Enum
from typing import Final, NoReturn

# Keep these values in sync with the established Artificial Analysis protocol.
PROTOCOL_VERSION: Final[str] = "1"
SNAPSHOT_SCHEMA_VERSION: Final[int] = 2


class ValueStatus(str, Enum):
    """Whether a value exists and where its value came from."""

    PUBLISHED = "published"
    DERIVED = "derived"
    MISSING = "missing"
    UNPARSED = "unparsed"


class MetricSemanticsStatus(str, Enum):
    """Whether a numeric value has an unambiguous metric meaning."""

    KNOWN = "known"
    UNKNOWN = "unknown"
    AMBIGUOUS = "ambiguous"


class ComparisonEligibility(str, Enum):
    """Whether an evidence value may participate in a comparison."""

    ELIGIBLE = "eligible"
    BLOCKED = "blocked"


NON_NORMALIZED_VALUE_STATUSES: Final[frozenset[ValueStatus]] = frozenset(
    {ValueStatus.MISSING, ValueStatus.UNPARSED}
)


VALUE_STATUSES: Final[tuple[str, ...]] = tuple(item.value for item in ValueStatus)
METRIC_SEMANTICS_STATUSES: Final[tuple[str, ...]] = tuple(
    item.value for item in MetricSemanticsStatus
)
COMPARISON_ELIGIBILITIES: Final[tuple[str, ...]] = tuple(
    item.value for item in ComparisonEligibility
)

# Keep diagnostics source-local.  These names are additive metadata and do not
# replace the lower-case v1 RPC error codes.
DIAGNOSTIC_CODES: Final[frozenset[str]] = frozenset(
    {
        "CACHE_ARTIFACTS_EMPTY",
        "CACHE_METADATA_INVALID",
        "CACHE_MISSING",
        "CACHE_VALIDATOR_INVALID",
        "COMPARISON_INCOMPARABLE",
        "DUPLICATE_CONFLICT",
        "DUPLICATE_IDENTITY",
        "DUPLICATE_SOURCE_FIELD",
        "DUPLICATE_SOURCE_ROW",
        "FALLBACK_STATE_UNKNOWN",
        "FRESHNESS_UNKNOWN",
        "HISTORICAL_SNAPSHOT",
        "MALFORMED_PAYLOAD",
        "MISSING_REQUIRED_INPUT",
        "MIXED_RELEASE",
        "MIXED_SCOPE",
        "MIXED_VERSION",
        "NETWORK_ERROR",
        "NON_FINITE",
        "NUMERIC_AMBIGUITY",
        "PARSER_VERSION_MISSING",
        "PLACEHOLDER_VALUE",
        "SCHEMA_DRIFT",
        "SNAPSHOT_INVALID",
        "SNAPSHOT_MISSING",
        "SNAPSHOT_NOT_SELECTED",
        "SNAPSHOT_SCHEMA_MISSING",
        "SNAPSHOT_SCHEMA_UNSUPPORTED",
        "SOURCE_UNAVAILABLE",
        "STALE_DATA",
        "UNKNOWN_SCORE_SEMANTICS",
        "UNIT_MISMATCH",
        "UNPARSED_VALUE",
        "VERSION_MISMATCH",
    }
)
DIAGNOSTIC_SEVERITIES: Final[tuple[str, ...]] = ("info", "warning", "blocker", "error")


@dataclass(frozen=True, slots=True)
class SourceEvidence:
    """Provenance fields for one observed source artifact."""

    source_url: str | None = None
    final_url: str | None = None
    fetched_at: str | None = None
    observed_at: str | None = None
    status: object | None = None
    etag: str | None = None
    last_modified: str | None = None
    sha256: str | None = None
    byte_length: int | None = None
    parser: str | None = None
    parser_version: str | None = None
    source_path: str | None = None
    raw_reference: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Return the stable provenance fields for serialization."""
        status = self.status.value if isinstance(self.status, Enum) else self.status
        return {
            "source_url": self.source_url,
            "final_url": self.final_url,
            "fetched_at": self.fetched_at,
            "observed_at": self.observed_at,
            "status": status,
            "etag": self.etag,
            "last_modified": self.last_modified,
            "sha256": self.sha256,
            "byte_length": self.byte_length,
            "parser": self.parser,
            "parser_version": self.parser_version,
            "source_path": self.source_path,
            "raw_reference": self.raw_reference,
        }


def _raise_type(message: str) -> NoReturn:
    raise TypeError(message)


def _raise_value(message: str) -> NoReturn:
    raise ValueError(message)


def _normalise_numeric(value: object) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        _raise_type("normalized_value must not be bool")
    if isinstance(value, int):
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            _raise_value("normalized_value must be finite")
        if value == value.to_integral_value():
            return int(value)
        value = float(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            _raise_value("normalized_value must be finite")
        return value
    _raise_type("normalized_value must be a finite number or None")


@dataclass(frozen=True, slots=True)
class NumericEvidence:
    """A numeric observation with independent value, meaning, and eligibility."""

    raw_value: object
    normalized_value: int | float | Decimal | None = None
    unit: str | None = None
    normalization: str | None = None
    source_path: str | None = None
    source_field: str | None = None
    value_status: ValueStatus = ValueStatus.MISSING
    metric_semantics_status: MetricSemanticsStatus = MetricSemanticsStatus.UNKNOWN
    comparison_eligibility: ComparisonEligibility = ComparisonEligibility.BLOCKED
    blocked_reasons: tuple[str, ...] = field(default_factory=tuple)
    parser: str = "numeric"
    parser_version: str = "1"
    artifact_id: str | None = None
    sha256: str | None = None
    formula: str | None = None
    input_paths: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        """Normalize enum fields, numbers, and stable blocker ordering."""
        object.__setattr__(self, "value_status", ValueStatus(self.value_status))
        object.__setattr__(
            self,
            "metric_semantics_status",
            MetricSemanticsStatus(self.metric_semantics_status),
        )
        object.__setattr__(
            self,
            "comparison_eligibility",
            ComparisonEligibility(self.comparison_eligibility),
        )
        normalized = _normalise_numeric(self.normalized_value)
        if self.value_status in NON_NORMALIZED_VALUE_STATUSES:
            normalized = None
        object.__setattr__(self, "normalized_value", normalized)
        reasons: list[str] = []
        seen: set[str] = set()
        for reason in self.blocked_reasons:
            stable = str(reason)
            if stable and stable not in seen:
                seen.add(stable)
                reasons.append(stable)
        object.__setattr__(self, "blocked_reasons", tuple(reasons))
        object.__setattr__(
            self, "input_paths", tuple(str(path) for path in self.input_paths)
        )

    def to_dict(self) -> dict[str, object]:
        """Return the evidence fields using the stable wire names."""
        result: dict[str, object] = {
            "raw_value": self.raw_value,
            "normalized_value": self.normalized_value,
            "unit": self.unit,
            "normalization": self.normalization,
            "source_path": self.source_path,
            "source_field": self.source_field,
            "value_status": self.value_status.value,
            "metric_semantics_status": self.metric_semantics_status.value,
            "comparison_eligibility": self.comparison_eligibility.value,
            "blocked_reasons": list(self.blocked_reasons),
            "parser": self.parser,
            "parser_version": self.parser_version,
        }
        if self.artifact_id is not None:
            result["artifact_id"] = self.artifact_id
        if self.sha256 is not None:
            result["sha256"] = self.sha256
        if self.formula is not None:
            result["formula"] = self.formula
            result["input_paths"] = list(self.input_paths)
        elif self.input_paths:
            result["input_paths"] = list(self.input_paths)
        return result


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """One stable source-local diagnostic record."""

    code: str
    severity: str
    stage: str
    message: str
    source_path: str | None = None
    artifact_id: str | None = None
    details: object | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a redacted, stable diagnostic mapping."""
        # Import lazily: diagnostics.py imports the contract constants and
        # must remain independent from every other skill.
        from .diagnostics import redact  # noqa: PLC0415

        result: dict[str, object] = {
            "code": self.code,
            "severity": self.severity,
            "stage": self.stage,
            "message": str(redact(self.message)),
        }
        if self.source_path is not None:
            result["source_path"] = redact(self.source_path)
        if self.artifact_id is not None:
            result["artifact_id"] = redact(self.artifact_id)
        if self.details is not None:
            result["details"] = redact(self.details)
        return result

    def as_dict(self) -> dict[str, object]:
        """Alias used by callers that share a diagnostics boundary."""
        return self.to_dict()


def _plain_json(value: object) -> object:
    """Project common Python values to finite, JSON-compatible values."""
    if isinstance(value, Enum):
        value = _plain_json(value.value)
    elif hasattr(value, "to_dict") and callable(value.to_dict):
        value = _plain_json(value.to_dict())
    elif is_dataclass(value) and not isinstance(value, type):
        value = _plain_json(
            {item.name: getattr(value, item.name) for item in fields(value)}
        )
    elif isinstance(value, Mapping):
        value = _plain_mapping(value)
    elif isinstance(value, (list, tuple)):
        value = [_plain_json(item) for item in value]
    elif isinstance(value, (set, frozenset)):
        value = _plain_set(value)
    elif isinstance(value, Decimal):
        value = _plain_decimal(value)
    elif isinstance(value, float) and not math.isfinite(value):
        _raise_value("compact JSON does not accept non-finite numbers")
    return value


def _plain_mapping(value: Mapping[object, object]) -> dict[str, object]:
    """Project mapping keys and reject collisions or non-finite keys."""
    projected: dict[str, object] = {}
    for key, item in value.items():
        if isinstance(key, float) and not math.isfinite(key):
            _raise_value("compact JSON does not accept non-finite numbers")
        if isinstance(key, Decimal) and not key.is_finite():
            _raise_value("compact JSON does not accept non-finite numbers")
        key_text = str(key)
        if key_text in projected:
            _raise_value(f"compact JSON mapping key collision: {key_text!r}")
        projected[key_text] = _plain_json(item)
    return projected


def _plain_set(value: set[object] | frozenset[object]) -> list[object]:
    projected = [_plain_json(item) for item in value]
    try:
        return sorted(
            projected,
            key=lambda item: json.dumps(
                item,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
        )
    except (TypeError, ValueError):
        return sorted(projected, key=repr)


def _plain_decimal(value: Decimal) -> int | float:
    if not value.is_finite():
        _raise_value("compact JSON does not accept non-finite numbers")
    if value == value.to_integral_value():
        return int(value)
    result = float(value)
    if not math.isfinite(result):
        _raise_value("compact JSON does not accept non-finite numbers")
    return result


def compact_json(value: object) -> str:
    """Serialize a value as deterministic compact JSON.

    ``allow_nan=False`` is intentional: NaN and infinities are not JSON
    numbers and silently emitting JavaScript spellings would make a snapshot
    impossible to consume consistently.
    """
    return json.dumps(
        _plain_json(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


__all__ = [
    "COMPARISON_ELIGIBILITIES",
    "DIAGNOSTIC_CODES",
    "DIAGNOSTIC_SEVERITIES",
    "METRIC_SEMANTICS_STATUSES",
    "PROTOCOL_VERSION",
    "SNAPSHOT_SCHEMA_VERSION",
    "VALUE_STATUSES",
    "ComparisonEligibility",
    "Diagnostic",
    "MetricSemanticsStatus",
    "NumericEvidence",
    "SourceEvidence",
    "ValueStatus",
    "compact_json",
]
