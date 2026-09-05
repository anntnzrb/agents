"""Phase 4 projection evidence and ordering contracts."""

# ruff: noqa: FBT003
from __future__ import annotations

import math
from typing import cast

from artificial_analysis.cli import (
    _attach_row_evidence,  # pyright: ignore[reportPrivateUsage]
    _evidence_record,  # pyright: ignore[reportPrivateUsage]
    _harness_score,  # pyright: ignore[reportPrivateUsage]
    _sort_metric,  # pyright: ignore[reportPrivateUsage]
)


def test_metric_evidence_retains_known_missing_unknown_and_derived_statuses() -> None:
    known = _evidence_record(
        "42",
        source_path="$.rows[0].score",
        source_field="score",
        artifact_hash="a" * 64,
    )
    missing = _evidence_record(
        None,
        source_path="$.rows[0].missing",
        source_field="missing",
    )
    unknown = _evidence_record(
        7,
        source_path="$.rows[0].mystery",
        source_field="mystery",
        semantics="unknown",
    )
    derived = _evidence_record(
        21,
        source_path="$.derived.total",
        source_field="total",
        value_status="derived",
        formula="a + b",
        input_paths=("$.a", "$.b"),
    )

    assert known["raw"] == "42"
    assert known["normalized"] == 42
    assert known["status"] == "published"
    assert known["eligibility"] == "eligible"
    assert known["artifact_hash"] == "a" * 64
    assert missing["raw"] is None
    assert missing["normalized"] is None
    assert missing["status"] == "missing"
    assert missing["eligibility"] == "blocked"
    assert unknown["normalized"] == 7
    assert unknown["semantics"] == "unknown"
    assert unknown["eligibility"] == "blocked"
    assert derived["status"] == "derived"
    assert derived["formula"] == "a + b"
    assert derived["input_paths"] == ["$.a", "$.b"]


def test_evidence_sorting_places_only_eligible_finite_values_first() -> None:
    rows: list[dict[str, object]] = [
        {
            "score": None,
            "metric_evidence": {
                "score": _evidence_record(
                    None, source_path="$.score", source_field="score"
                )
            },
        },
        {
            "score": True,
            "metric_evidence": {
                "score": _evidence_record(
                    True, source_path="$.score", source_field="score"
                )
            },
        },
        {
            "score": float("nan"),
            "metric_evidence": {
                "score": _evidence_record(
                    float("nan"), source_path="$.score", source_field="score"
                )
            },
        },
        {
            "score": 2,
            "metric_evidence": {
                "score": _evidence_record(
                    2, source_path="$.score", source_field="score"
                )
            },
        },
        {
            "score": 9,
            "metric_evidence": {
                "score": _evidence_record(
                    9, source_path="$.score", source_field="score"
                )
            },
        },
    ]

    def _key(row: dict[str, object]) -> tuple[int, float]:
        return _sort_metric(row, "score", reverse=True)

    rows.sort(key=_key)
    assert [row["score"] for row in rows[:2]] == [9, 2]
    assert all(not isinstance(row["score"], bool) for row in rows[:2])
    assert all(_sort_metric(row, "score", reverse=True)[0] == 1 for row in rows[2:])
    score_val = cast("float", rows[-1]["score"])
    assert math.isnan(score_val)


def test_row_projection_preserves_raw_unknowns_and_published_values() -> None:
    row: dict[str, object] = {
        "coding": 80,
        "harness": 71,
        "raw_fields": {"futureMetric": 123},
        "unknowns": {"sourceFlag": "x"},
    }
    _ = _attach_row_evidence(
        row,
        metric_paths=("coding", "harness", "mystery"),
        derived_paths={"mystery": ("coding / 2", ("$.coding",))},
    )
    assert row["coding"] == 80
    assert row["harness"] == 71
    assert row["raw_fields"] == {"futureMetric": 123}
    assert row["unknowns"] == {"sourceFlag": "x"}
    metric_evidence = cast("dict[str, dict[str, object]]", row["metric_evidence"])
    assert metric_evidence["coding"]["normalized"] == 80
    assert metric_evidence["harness"]["normalized"] == 71
    assert metric_evidence["mystery"]["status"] == "derived"


def test_legacy_scalar_helpers_reject_boolean_and_nonfinite_values() -> None:
    assert _harness_score({"agentic_index": 80, "coding_index": 60}) == 70.0
    assert _harness_score({"agentic_index": True, "coding_index": 60}) is None
    assert _harness_score({"agentic_index": float("inf"), "coding_index": 60}) is None
