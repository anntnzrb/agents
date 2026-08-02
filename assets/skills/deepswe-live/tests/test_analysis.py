"""Pure, fixture-only analysis contract tests."""
# ruff: noqa: CPY001, E501, INP001, S101

from __future__ import annotations

from typing import Any

import _path  # noqa: F401
import pytest
from deepswe.analysis import (
    build_report,
    derive_efficiency,
    filter_trials,
    pareto_rows,
    rank_rows,
)

TASK_COUNT = 4
ROW_COUNT = 5
VALID_COST_PER_ATTEMPT = 0.5
FILTERED_COUNT = 4
MIN_ATTEMPTED = 2
HIGH_PASS_RATE = 0.95


def metric_row(  # noqa: PLR0913
    config: str,
    *,
    pass_at_1: float | None,
    output_tokens: float | None,
    cost: float | None,
    steps: float | None,
    attempted: int = 10,
    effort: str = "high",
    harness: str = "fixture-harness",
) -> dict[str, Any]:
    """Build one representative published leaderboard row."""
    return {
        "model": "same-model",
        "reasoning_effort": effort,
        "harness": harness,
        "config": config,
        "source": "deep-swe",
        "pass_rate": pass_at_1,
        "pass_at_1": pass_at_1,
        "n_passed": int(pass_at_1 * attempted) if pass_at_1 is not None else None,
        "n_attempted": attempted,
        "n_tasks_attempted": TASK_COUNT,
        "ci_lo": 0.4 if pass_at_1 is not None else None,
        "ci_hi": 0.6 if pass_at_1 is not None else None,
        "ci_half": 0.1 if pass_at_1 is not None else None,
        "mean_output_tokens": output_tokens,
        "mean_cost_usd": cost,
        "mean_agent_steps": steps,
    }


ROWS = [
    metric_row("config-a", pass_at_1=0.60, output_tokens=100, cost=1.0, steps=5),
    metric_row(
        "config-b", pass_at_1=0.70, output_tokens=110, cost=1.2, steps=6, effort="low"
    ),
    metric_row("config-c", pass_at_1=0.50, output_tokens=120, cost=2.0, steps=7),
    metric_row("config-null", pass_at_1=0.80, output_tokens=90, cost=None, steps=4),
    metric_row(
        "config-low-n",
        pass_at_1=HIGH_PASS_RATE,
        output_tokens=200,
        cost=3.0,
        steps=10,
        attempted=1,
    ),
]


def test_rank_preserves_identity_counts_and_published_fields_with_derived_ci_width() -> (
    None
):
    """Ensure ranking preserves published identity and scopes derived fields."""
    result = rank_rows(ROWS, "pass_at_1", "descending", limit=None)
    assert result["value_status"] == "derived"
    assert result["count"] == len(ROWS)
    assert result["filters_applied"] == {
        "min_pass_at_1": None,
        "min_attempted": None,
        "min_tasks": None,
        "limit": None,
    }

    ranked = result["rows"]
    assert isinstance(ranked, list)
    assert [row["config"] for row in ranked] == [
        "config-low-n",
        "config-null",
        "config-b",
        "config-a",
        "config-c",
    ]
    assert ranked[0]["model"] == "same-model"
    assert ranked[0]["reasoning_effort"] == "high"
    assert ranked[2]["reasoning_effort"] == "low"
    assert ranked[0]["n_attempted"] == 1
    assert ranked[0]["n_tasks_attempted"] == TASK_COUNT
    assert ranked[0]["pass_at_1"] == HIGH_PASS_RATE
    published_fields = (
        "pass_rate",
        "pass_at_1",
        "n_passed",
        "n_attempted",
        "n_tasks_attempted",
        "ci_lo",
        "ci_hi",
        "ci_half",
    )
    assert ranked[0]["value_status"] == "published"
    assert ranked[0]["derived"]["value_status"] == "derived"
    assert {field: ranked[0][field] for field in published_fields} == {
        field: ROWS[4][field] for field in published_fields
    }
    assert ranked[0]["derived"]["ci_width"] == pytest.approx(0.2)
    assert "ci_width" not in ranked[0]
    identity_rows = [
        metric_row(
            "same-config",
            pass_at_1=0.4,
            output_tokens=100,
            cost=1,
            steps=3,
            harness="harness-a",
        ),
        metric_row(
            "same-config",
            pass_at_1=0.4,
            output_tokens=100,
            cost=1,
            steps=3,
            harness="harness-b",
        ),
    ]
    identity_result = rank_rows(identity_rows, "pass_at_1", "desc", limit=None)
    assert {row["harness"] for row in identity_result["rows"]} == {
        "harness-a",
        "harness-b",
    }


def test_report_separates_raw_extrema_recommendations_and_pareto_nulls() -> None:
    """Ensure reports distinguish raw extrema, recommendations, and Pareto rows."""
    payload = {
        "scope": {
            "benchmark": "DeepSWE",
            "benchmark_version": "v1.1",
            "value_status": "published",
        },
        "provenance": {
            "url": "fixture://leaderboard",
            "fetched_at": "2026-07-25T00:00:00Z",
        },
        "rows": ROWS,
    }
    report = build_report(payload, limit=None)
    assert report["value_status"] == "derived"
    assert report["recommendations"]["value_status"] == "derived"

    assert report["counts"] == {
        "input": 5,
        "eligible": 5,
        "recommendations": 5,
        "pareto": 3,
    }
    assert report["filters_applied"]["min_attempted"] is None
    assert report["raw_extrema"]["pass_at_1"]["max"]["config"] == "config-low-n"
    extrema_max = report["raw_extrema"]["pass_at_1"]["max"]
    assert extrema_max["value_status"] == "published"
    assert extrema_max["derived"]["value_status"] == "derived"
    assert report["raw_extrema"]["mean_cost_usd"]["min"]["config"] == "config-a"
    pareto_configs = {row["config"] for row in report["pareto"]}
    assert "config-null" not in pareto_configs
    assert "config-c" not in pareto_configs
    assert {"config-a", "config-b", "config-low-n"} == pareto_configs
    assert all(row["value_status"] == "published" for row in report["pareto"])
    assert all(row["derived"]["value_status"] == "derived" for row in report["pareto"])
    assert report["scope"]["benchmark_version"] == "v1.1"
    assert report["scope"]["value_status"] == "derived"
    assert report["provenance"]["url"] == "fixture://leaderboard"


def test_quality_thresholds_are_opt_in_and_visible() -> None:
    """Ensure quality thresholds alter eligibility only when explicitly supplied."""
    unfiltered = build_report(ROWS, min_attempted=None, limit=None)
    filtered = build_report(ROWS, min_attempted=MIN_ATTEMPTED, limit=None)
    assert unfiltered["counts"]["eligible"] == ROW_COUNT
    assert filtered["counts"]["eligible"] == FILTERED_COUNT
    filtered_configs = {row["config"] for row in filtered["recommendations"]["rows"]}
    assert "config-low-n" not in filtered_configs
    assert filtered["filters_applied"]["min_attempted"] == MIN_ATTEMPTED


def test_custom_pareto_axes_preserve_null_exclusion_and_identity() -> None:
    """Ensure custom Pareto axes preserve null exclusion and identity."""
    frontier = pareto_rows(
        [
            {"config": "quality", "pass_at_1": 0.9, "mean_cost_usd": 2.0},
            {"config": "cheap", "pass_at_1": 0.8, "mean_cost_usd": 1.0},
            {"config": "dominated", "pass_at_1": 0.7, "mean_cost_usd": 3.0},
            {"config": "missing", "pass_at_1": 0.9, "mean_cost_usd": None},
        ],
        ["pass_at_1:max", "mean_cost_usd:min"],
    )
    assert {row["config"] for row in frontier} == {"quality", "cheap"}
    assert all(row["value_status"] == "published" for row in frontier)


def test_efficiency_utility_handles_zero_and_missing_denominators() -> None:
    """Ensure efficiency derivation reports valid, zero, and missing inputs."""
    result = derive_efficiency(
        [
            {"config": "valid", "mean_cost_usd": 2.0, "n_attempted": 4},
            {"config": "zero", "mean_cost_usd": 2.0, "n_attempted": 0},
            {"config": "missing", "mean_cost_usd": None, "n_attempted": 4},
        ],
        ["cost_per_attempt=mean_cost_usd/n_attempted"],
    )
    rows = {row["config"]: row for row in result["rows"]}
    assert (
        rows["valid"]["derived"]["efficiency"]["cost_per_attempt"]["value"]
        == VALID_COST_PER_ATTEMPT
    )
    assert (
        rows["zero"]["derived"]["efficiency"]["cost_per_attempt"]["reason"]
        == "zero_denominator"
    )
    assert (
        rows["missing"]["derived"]["efficiency"]["cost_per_attempt"]["reason"]
        == "missing_or_invalid_input"
    )


def test_report_adds_opt_in_analysis_sections() -> None:
    """Ensure reports include requested Pareto and efficiency sections."""
    report = build_report(
        ROWS,
        limit=None,
        pareto_axes=["pass_at_1:max", "mean_cost_usd:min"],
        efficiency_specs=["cost_per_attempt=mean_cost_usd/n_attempted"],
    )
    assert report["pareto_axes"] == [
        {"metric": "pass_at_1", "order": "desc"},
        {"metric": "mean_cost_usd", "order": "asc"},
    ]
    assert report["efficiency"]["specs"][0]["name"] == "cost_per_attempt"


@pytest.mark.parametrize(
    "threshold_name", ["min_attempted", "min_pass_at_1", "min_tasks"]
)
def test_negative_quality_thresholds_are_rejected(threshold_name: str) -> None:
    """Reject negative values for every quality threshold option."""
    with pytest.raises(ValueError, match="non-negative"):
        rank_rows(ROWS, "pass_at_1", "desc", limit=None, **{threshold_name: -1})  # type: ignore[arg-type]


def test_trial_defaults_exclude_other_scope_and_explicit_overrides_restore_visibility() -> (
    None
):
    """Ensure trial defaults exclude other scopes and explicit overrides restore rows."""
    rows = [
        {
            "id": "included",
            "source": "deep-swe",
            "eval_scope": "full",
            "included_in_score": True,
        },
        {
            "id": "excluded-source",
            "source": "other",
            "eval_scope": "full",
            "included_in_score": True,
        },
        {
            "id": "excluded-scope",
            "source": "deep-swe",
            "eval_scope": "smoke",
            "included_in_score": True,
        },
        {
            "id": "excluded-inclusion",
            "source": "deep-swe",
            "eval_scope": "full",
            "included_in_score": False,
        },
        {"id": "missing", "source": "deep-swe", "eval_scope": "full"},
    ]
    default = filter_trials(rows)
    assert [row["id"] for row in default["rows"]] == ["included"]
    assert default["filters_applied"] == {
        "source": "deep-swe",
        "eval_scope": "full",
        "included_in_score": True,
    }

    visible = filter_trials(rows, source=None, eval_scope=None, included_only=False)
    assert [row["id"] for row in visible["rows"]] == [row["id"] for row in rows]
    assert visible["filters_applied"] == {
        "source": None,
        "eval_scope": None,
        "included_in_score": None,
    }


def test_null_safe_ordering_and_invalid_analysis_inputs() -> None:
    """Ensure null metrics are omitted and invalid analysis inputs are rejected."""
    result = rank_rows(
        [{"config": "missing", "pass_at_1": None}, {"config": "ok", "pass_at_1": 0.4}],
        "pass_at_1",
        "asc",
        limit=None,
    )
    assert [row["config"] for row in result["rows"]] == ["ok"]
    assert result["rows"][0]["derived"]["ci_width"] is None

    with pytest.raises(TypeError, match="thresholds"):
        rank_rows(ROWS, "pass_at_1", "desc", min_attempted="ten")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="non-negative"):
        rank_rows(ROWS, "pass_at_1", "desc", limit=-1)
    with pytest.raises(TypeError, match="included_only"):
        filter_trials([], included_only=1)  # type: ignore[arg-type]


if __name__ == "__main__":
    pytest.main([__file__])
