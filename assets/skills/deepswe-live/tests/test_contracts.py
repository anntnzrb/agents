"""Offline tests for the DeepSWE Phase 1 contract helpers."""
# ruff: noqa: CPY001, D103, INP001, PLR2004, S101

from __future__ import annotations

import hashlib
import json
import math

import _path  # noqa: F401
import pytest
from deepswe.contracts import (
    COMPARISON_ELIGIBILITY_STATUSES,
    ELIGIBILITY_STATES,
    METRIC_SEMANTICS_STATUSES,
    SCHEMA_VERSION,
    SCOPE_VALUE_STATUSES,
    SEMANTIC_STATES,
    VALUE_STATUSES,
    compact_json,
    error_envelope,
    success_envelope,
)
from deepswe.provenance import artifact_evidence, value_evidence


def test_success_and_error_keep_the_legacy_integer_v1_shape() -> None:
    assert success_envelope("report", {"rows": []}) == {
        "ok": True,
        "schema_version": 1,
        "command": "report",
        "data": {"rows": []},
    }
    assert error_envelope("report", "MIXED_VERSION", "versions differ") == {
        "ok": False,
        "schema_version": 1,
        "command": "report",
        "error": {"code": "mixed_version", "message": "versions differ"},
    }
    assert SCHEMA_VERSION == 1


def test_compact_json_is_finite_and_keeps_safe_strings() -> None:
    assert compact_json({"b": "metric NaN", "a": 1.5}) == ('{"b":"metric NaN","a":1.5}')
    with pytest.raises(ValueError, match="Out of range"):
        compact_json({"value": math.nan})
    with pytest.raises(ValueError, match="Out of range"):
        compact_json({"values": [math.inf, -math.inf]})


def test_scope_value_and_independent_state_sets_are_explicit() -> None:
    assert set(SCOPE_VALUE_STATUSES) == {"published", "published_raw", "derived"}
    assert set(VALUE_STATUSES) == {
        "published",
        "published_raw",
        "derived",
        "missing",
        "unparsed",
    }
    assert set(METRIC_SEMANTICS_STATUSES) == {
        "known",
        "unknown",
        "ambiguous",
        "invalid",
        "placeholder",
    }
    assert set(SEMANTIC_STATES) == set(METRIC_SEMANTICS_STATUSES)
    assert set(COMPARISON_ELIGIBILITY_STATUSES) == {"eligible", "blocked"}
    assert set(ELIGIBILITY_STATES) == set(COMPARISON_ELIGIBILITY_STATUSES)


def test_artifact_and_value_evidence_retain_lineage_and_freshness() -> None:
    body = b'{"rows":[]}'
    digest = hashlib.sha256(body).hexdigest()
    artifact = artifact_evidence(
        url="https://example.test/artifact?v=1&token=secret",
        fetched_at="2026-08-09T00:00:00Z",
        generated_at="2026-08-08T00:00:00Z",
        etag='"abc"',
        last_modified="Sat, 09 Aug 2026 00:00:00 GMT",
        body=body,
        raw_bytes_ref="artifacts/example.raw",
        parser="deepswe.sources",
        parser_version="1",
        historical=True,
        freshness_mode="snapshot",
        benchmark_version="v1.1",
    )
    assert artifact["url"] == "https://example.test/artifact?v=1&token=<redacted>"
    assert artifact["artifact_sha256"] == digest
    assert artifact["sha256"] == digest
    assert artifact["byte_length"] == len(body)
    assert artifact["raw_bytes_ref"] == "artifacts/example.raw"
    assert artifact["parser"] == "deepswe.sources"
    assert artifact["parser_version"] == "1"
    assert artifact["etag"] == '"abc"'
    assert artifact["ETag"] == '"abc"'
    assert artifact["last_modified"] == "Sat, 09 Aug 2026 00:00:00 GMT"
    assert artifact["Last-Modified"] == "Sat, 09 Aug 2026 00:00:00 GMT"
    assert artifact["historical"] is True
    assert artifact["freshness"] == "snapshot"

    evidence = value_evidence(
        artifact,
        raw_value=0.5,
        normalized_value=0.5,
        unit="ratio",
        normalization="source-defined",
        source_path="$.rows[0].pass_at_1",
        source_field="pass_at_1",
        value_status="published",
        metric_semantics_status="known",
        comparison_eligibility="eligible",
        parser="deepswe.normalization",
        parser_version="1",
    )
    assert evidence["raw_value"] == 0.5
    assert evidence["normalized_value"] == 0.5
    assert evidence["source_path"] == "$.rows[0].pass_at_1"
    assert evidence["source_field"] == "pass_at_1"
    assert evidence["artifact_sha256"] == digest
    assert evidence["byte_length"] == len(body)
    assert evidence["raw_bytes_ref"] == "artifacts/example.raw"
    assert evidence["freshness"] == "snapshot"


def test_missing_and_unparsed_evidence_preserve_raw_values_without_zero() -> None:
    missing = value_evidence(
        raw_value=None,
        normalized_value=None,
        value_status="missing",
        metric_semantics_status="placeholder",
        comparison_eligibility="blocked",
        missing_reason="SOURCE_ABSENT",
        blocked_reasons=["MISSING_REQUIRED_INPUT"],
    )
    unparsed = value_evidence(
        raw_value="not-a-number",
        normalized_value=None,
        value_status="unparsed",
        metric_semantics_status="invalid",
        comparison_eligibility="blocked",
        blocked_reasons=["MALFORMED_PAYLOAD"],
    )
    assert missing["raw_value"] is None
    assert missing["normalized_value"] is None
    assert unparsed["raw_value"] == "not-a-number"
    assert unparsed["normalized_value"] is None
    assert missing["normalized_value"] != 0
    assert unparsed["normalized_value"] != 0


def test_evidence_is_json_serializable_when_values_are_finite() -> None:
    evidence = value_evidence(raw_value=3, normalized_value=3, unit="count")
    encoded = compact_json(evidence)
    assert json.loads(encoded)["normalized_value"] == 3
