"""Offline tests for the Artificial Analysis contract primitives."""

from __future__ import annotations

import math
from enum import StrEnum
from http import HTTPStatus
from typing import cast

import pytest

from artificial_analysis.contracts import (
    COMPARISON_ELIGIBILITIES,
    DIAGNOSTIC_SEVERITIES,
    METRIC_SEMANTICS_STATUSES,
    PROTOCOL_VERSION,
    SNAPSHOT_SCHEMA_VERSION,
    VALUE_STATUSES,
    ComparisonEligibility,
    MetricSemanticsStatus,
    NumericEvidence,
    SourceEvidence,
    ValueStatus,
    compact_json,
)


def test_protocol_and_status_sets_remain_explicit_and_compatible() -> None:
    assert PROTOCOL_VERSION == "1"
    assert SNAPSHOT_SCHEMA_VERSION == 2
    assert set(VALUE_STATUSES) == {"published", "derived", "missing", "unparsed"}
    assert set(METRIC_SEMANTICS_STATUSES) == {"known", "unknown", "ambiguous"}
    assert set(COMPARISON_ELIGIBILITIES) == {"eligible", "blocked"}
    assert set(DIAGNOSTIC_SEVERITIES) == {"info", "warning", "blocker", "error"}


def test_source_evidence_serializes_enum_status_and_all_wire_fields() -> None:
    evidence = SourceEvidence(
        source_url="https://example.test/source",
        final_url="https://example.test/final",
        fetched_at="2026-08-10T00:00:00Z",
        observed_at="2026-08-10T00:00:01Z",
        status=HTTPStatus.OK,
        etag='"abc"',
        last_modified="Mon, 10 Aug 2026 00:00:00 GMT",
        sha256="a" * 64,
        byte_length=12,
        parser="artificial_analysis.rsc",
        parser_version="1",
        source_path="$.rows[0]",
        raw_reference="artifacts/example.raw",
    )

    assert evidence.to_dict() == {
        "source_url": "https://example.test/source",
        "final_url": "https://example.test/final",
        "fetched_at": "2026-08-10T00:00:00Z",
        "observed_at": "2026-08-10T00:00:01Z",
        "status": 200,
        "etag": '"abc"',
        "last_modified": "Mon, 10 Aug 2026 00:00:00 GMT",
        "sha256": "a" * 64,
        "byte_length": 12,
        "parser": "artificial_analysis.rsc",
        "parser_version": "1",
        "source_path": "$.rows[0]",
        "raw_reference": "artifacts/example.raw",
    }


def test_numeric_evidence_keeps_independent_statuses_and_raw_values() -> None:
    evidence = NumericEvidence(
        raw_value="source-token",
        normalized_value=42,
        unit="count",
        value_status=cast("ValueStatus", cast("object", "missing")),
        metric_semantics_status=cast(
            "MetricSemanticsStatus", cast("object", "unknown")
        ),
        comparison_eligibility=cast("ComparisonEligibility", cast("object", "blocked")),
        blocked_reasons=("PLACEHOLDER_VALUE", "PLACEHOLDER_VALUE"),
        input_paths=cast("tuple[str, ...]", cast("object", (1, "$.rows[0].value"))),
    )

    assert evidence.normalized_value is None
    assert evidence.value_status is ValueStatus.MISSING
    assert evidence.metric_semantics_status is MetricSemanticsStatus.UNKNOWN
    assert evidence.comparison_eligibility is ComparisonEligibility.BLOCKED
    assert evidence.blocked_reasons == ("PLACEHOLDER_VALUE",)
    assert evidence.input_paths == ("1", "$.rows[0].value")
    assert evidence.to_dict() == {
        "raw_value": "source-token",
        "normalized_value": None,
        "unit": "count",
        "normalization": None,
        "source_path": None,
        "source_field": None,
        "value_status": "missing",
        "metric_semantics_status": "unknown",
        "comparison_eligibility": "blocked",
        "blocked_reasons": ["PLACEHOLDER_VALUE"],
        "parser": "numeric",
        "parser_version": "1",
        "input_paths": ["1", "$.rows[0].value"],
    }


@pytest.mark.parametrize("value", [True, False, math.nan, math.inf, -math.inf, "42"])
def test_numeric_evidence_rejects_unsafe_normalized_values(value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        _ = NumericEvidence(
            raw_value=value, normalized_value=cast("int | float | None", value)
        )


def test_compact_json_is_deterministic_finite_and_collision_safe() -> None:
    class Marker(StrEnum):
        VALUE = "value"

    assert compact_json({"set": {"b", "a"}, "marker": Marker.VALUE}) == (
        '{"marker":"value","set":["a","b"]}'
    )
    with pytest.raises(ValueError, match="collision"):
        _ = compact_json({1: "integer key", "1": "string key"})
    with pytest.raises(ValueError, match=r"non-finite"):
        _ = compact_json({"value": math.nan})
