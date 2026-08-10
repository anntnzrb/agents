"""Contract tests for conservative DeepSWE normalization."""
# ruff: noqa: CPY001, D103, FBT003, INP001, PLR2004, S101

from __future__ import annotations

import math

import _path  # noqa: F401
from deepswe.normalization import normalize_payload, normalize_row, parse_numeric


def test_known_units_ranges_and_evidence_path() -> None:
    evidence = parse_numeric(
        "50%", metric="pass_at_1", source_path="$.rows[0].pass_at_1"
    )
    assert evidence["normalized_value"] == 0.5
    assert evidence["unit"] == "ratio"
    assert evidence["range"] == [0, 1]
    assert evidence["comparator"] == "max"
    assert evidence["denominator"] == "n_tasks_attempted"
    assert evidence["source_path"] == "$.rows[0].pass_at_1"


def test_missing_unparsed_and_placeholders_never_become_zero() -> None:
    missing = parse_numeric(None, metric="mean_cost_usd")
    malformed = parse_numeric("not numeric", metric="mean_cost_usd")
    placeholder = parse_numeric("N/A", metric="mean_cost_usd")
    assert missing["value_status"] == "missing"
    assert malformed["value_status"] == "unparsed"
    assert placeholder["metric_semantics_status"] == "placeholder"
    assert all(
        value["normalized_value"] is None for value in (missing, malformed, placeholder)
    )


def test_numeric_strings_bool_nonfinite_and_out_of_range() -> None:
    assert (
        parse_numeric("1,024", metric="mean_output_tokens")["normalized_value"] == 1024
    )
    assert (
        parse_numeric(True, metric="n_attempted")["metric_semantics_status"]
        == "invalid"
    )
    assert parse_numeric(float("nan"), metric="n_attempted")["normalized_value"] is None
    out_of_range = parse_numeric("101%", metric="pass_at_1")
    assert out_of_range["normalized_value"] is None
    assert "OUT_OF_RANGE" in out_of_range["blocked_reasons"]


def test_chart_zero_is_placeholder_but_true_zero_is_preserved() -> None:
    chart = parse_numeric(
        "0.0%", metric="pass_at_1", source_marker={"chart_zero": True}
    )
    true_zero = parse_numeric(0, metric="pass_at_1")
    assert chart["value_status"] == "missing"
    assert true_zero["normalized_value"] == 0


def test_unknown_metrics_and_raw_row_preservation() -> None:
    row = normalize_row({"model": "m", "mystery_metric": 3, "label": "future"})
    assert row["model"] == "m"
    assert row["mystery_metric"] == 3
    assert row["raw_fields"]["mystery_metric"] == 3
    assert row["raw_fields"]["label"] == "future"
    assert row["metrics"]["mystery_metric"]["metric_semantics_status"] == "unknown"
    assert row["metrics"]["mystery_metric"]["comparison_eligibility"] == "blocked"


def test_payload_unknown_metadata_is_retained() -> None:
    payload = normalize_payload(
        {"rows": [{"config": "c", "pass_at_1": 0.2}], "future_field": {"x": 1}}
    )
    assert payload["raw_metadata"]["future_field"] == {"x": 1}
    assert payload["rows"][0]["metrics"]["pass_at_1"]["normalized_value"] == 0.2


def test_nonfinite_string_is_not_json_numeric() -> None:
    evidence = parse_numeric("Infinity", metric="n_attempted")
    assert evidence["normalized_value"] is None
    assert math.isfinite(0.0)
