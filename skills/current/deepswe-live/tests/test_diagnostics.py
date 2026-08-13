"""Offline tests for deterministic DeepSWE diagnostics and redaction."""
# ruff: noqa: CPY001, D103, INP001, PLR2004, S101

from __future__ import annotations

import _path  # noqa: F401
from deepswe.diagnostics import Diagnostic, merge_diagnostics, redact


def test_recursive_redaction_removes_secret_keys_and_query_credentials() -> None:
    value = {
        "authorization": "Bearer top-secret",
        "nested": [
            {"api_key": "key-secret", "safe": "metric latency"},
            "https://example.test/report?token=query-secret&metric=0.5",
        ],
        "headers": {"Cookie": "session=secret"},
    }
    redacted = redact(value)
    assert isinstance(redacted, dict)
    assert redacted["authorization"] == "<redacted>"
    nested = redacted["nested"]
    assert isinstance(nested, list)
    assert nested[0]["api_key"] == "<redacted>"
    assert nested[0]["safe"] == "metric latency"
    assert nested[1] == ("https://example.test/report?token=<redacted>&metric=0.5")
    assert redacted["headers"]["Cookie"] == "<redacted>"


def test_redaction_does_not_hide_metric_strings_or_safe_numerics() -> None:
    value = {
        "metric": "token throughput",
        "metric_name": "mean_cost_usd",
        "token_count": 12,
        "value": 0.0,
        "count": 0,
    }
    assert redact(value) == value


def test_diagnostic_shape_redacts_message_details_and_optional_paths() -> None:
    diagnostic = Diagnostic(
        "source_unavailable",
        severity="error",
        stage="transport",
        message="request https://example.test/?api_key=secret failed",
        source_path="$.rows[0].pass_at_1",
        artifact_id="deepswe:sha256:abc",
        details={"query": "https://example.test/?password=secret", "metric": 0.5},
    ).as_dict()
    assert diagnostic["code"] == "SOURCE_UNAVAILABLE"
    assert diagnostic["severity"] == "error"
    assert diagnostic["stage"] == "transport"
    assert diagnostic["message"] == (
        "request https://example.test/?api_key=<redacted> failed"
    )
    assert diagnostic["source_path"] == "$.rows[0].pass_at_1"
    assert diagnostic["artifact_id"] == "deepswe:sha256:abc"
    assert diagnostic["details"] == {
        "query": "https://example.test/?password=<redacted>",
        "metric": 0.5,
    }


def test_merge_diagnostics_sorts_independently_of_input_order_and_deduplicates() -> (
    None
):
    first = Diagnostic("schema_drift", stage="parse", message="shape changed")
    duplicate = Diagnostic("schema_drift", stage="parse", message="shape changed")
    other = Diagnostic(
        "cache_missing", severity="blocker", stage="cache", message="no bytes"
    )
    merged = merge_diagnostics([first, other], [duplicate])
    reversed_merged = merge_diagnostics([duplicate, other], [first])
    assert merged == reversed_merged
    assert len(merged) == 2
    assert [item["code"] for item in merged] == ["CACHE_MISSING", "SCHEMA_DRIFT"]


def test_merge_diagnostics_deduplicates_after_redaction() -> None:
    left = {
        "code": "source_unavailable",
        "severity": "warning",
        "stage": "transport",
        "message": "failed",
        "details": {"token": "one"},
    }
    right = {
        "code": "SOURCE_UNAVAILABLE",
        "severity": "warning",
        "stage": "transport",
        "message": "failed",
        "details": {"token": "two"},
    }
    merged = merge_diagnostics(left, right)
    assert len(merged) == 1
    assert merged[0]["details"] == {"token": "<redacted>"}
