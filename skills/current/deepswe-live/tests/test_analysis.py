"""Pure, fixture-only analysis contract tests."""
# ruff: noqa: E501

from typing import TYPE_CHECKING

import pytest

from deepswe.analysis import (
    build_report,
    derive_efficiency,
    filter_trials,
    pareto_rows,
    rank_rows,
)
from deepswe.contracts import as_dict, as_dict_list, as_list

if TYPE_CHECKING:
    from collections.abc import Callable

TASK_COUNT = 4
ROW_COUNT = 5
VALID_COST_PER_ATTEMPT = 0.5
FILTERED_COUNT = 4
MIN_ATTEMPTED = 2
HIGH_PASS_RATE = 0.95


def metric_row(
    config: str,
    *,
    pass_at_1: float | None,
    output_tokens: float | None,
    cost: float | None,
    steps: float | None,
    attempted: int = 10,
    effort: str = "high",
    harness: str = "fixture-harness",
) -> dict[str, object]:
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

    ranked = as_dict_list(result["rows"])
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
    ranked0_derived = as_dict(ranked[0]["derived"])
    assert ranked0_derived["value_status"] == "derived"
    assert {field: ranked[0][field] for field in published_fields} == {
        field: ROWS[4][field] for field in published_fields
    }
    assert ranked0_derived["ci_width"] == pytest.approx(0.2)
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
    identity_rows_ranked = as_dict_list(identity_result["rows"])
    assert {row["harness"] for row in identity_rows_ranked} == {
        "harness-a",
        "harness-b",
    }


def test_rank_strict_duplicates_keep_raw_rows_but_block_conflicts() -> None:
    """Strict ranking leaves conflicting source rows visible without ranks."""
    rows = [
        metric_row("same-config", pass_at_1=0.2, output_tokens=100, cost=1, steps=3),
        metric_row("same-config", pass_at_1=0.3, output_tokens=100, cost=1, steps=3),
    ]
    result = rank_rows(
        rows,
        "pass_at_1",
        "desc",
        limit=None,
        strict_duplicates=True,
    )
    assert result["strict_duplicates"] is True
    assert result["eligible_count"] == 0
    ranked = as_dict_list(result["rows"])
    assert isinstance(ranked, list)
    assert [row["config"] for row in ranked] == ["same-config", "same-config"]
    assert all(as_dict(row["derived"])["rank"] is None for row in ranked)
    assert all(
        "DUPLICATE_CONFLICT" in as_list(as_dict(row["derived"])["blocked_reasons"])
        for row in ranked
    )
    dup_report = as_dict(result["duplicate_report"])
    assert as_dict_list(dup_report["conflicting"])[0]["count"] == 2


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
    recs = as_dict(report["recommendations"])
    assert recs["value_status"] == "derived"

    assert report["counts"] == {
        "input": 5,
        "eligible": 5,
        "recommendations": 5,
        "pareto": 3,
    }
    filters_applied = as_dict(report["filters_applied"])
    assert filters_applied["min_attempted"] is None
    raw_extrema = as_dict(report["raw_extrema"])
    pass_extrema = as_dict(raw_extrema["pass_at_1"])
    extrema_max = as_dict(pass_extrema["max"])
    assert extrema_max["config"] == "config-low-n"
    assert extrema_max["value_status"] == "published"
    extrema_max_derived = as_dict(extrema_max["derived"])
    assert extrema_max_derived["value_status"] == "derived"
    cost_extrema = as_dict(raw_extrema["mean_cost_usd"])
    assert as_dict(cost_extrema["min"])["config"] == "config-a"
    pareto = as_dict_list(report["pareto"])
    pareto_configs = {row["config"] for row in pareto}
    assert "config-null" not in pareto_configs
    assert "config-c" not in pareto_configs
    assert {"config-a", "config-b", "config-low-n"} == pareto_configs
    assert all(row["value_status"] == "published" for row in pareto)
    assert all(as_dict(row["derived"])["value_status"] == "derived" for row in pareto)
    scope = as_dict(report["scope"])
    assert scope["benchmark_version"] == "v1.1"
    assert scope["value_status"] == "derived"
    provenance = as_dict(report["provenance"])
    assert provenance["url"] == "fixture://leaderboard"


def test_quality_thresholds_are_opt_in_and_visible() -> None:
    """Ensure quality thresholds alter eligibility only when explicitly supplied."""
    unfiltered = build_report(ROWS, min_attempted=None, limit=None)
    filtered = build_report(
        ROWS,
        min_attempted=MIN_ATTEMPTED,
        limit=None,
    )
    unfiltered_counts = as_dict(unfiltered["counts"])
    assert unfiltered_counts["eligible"] == ROW_COUNT
    filtered_counts = as_dict(filtered["counts"])
    assert filtered_counts["eligible"] == FILTERED_COUNT
    filtered_recs = as_dict(filtered["recommendations"])
    filtered_configs = {row["config"] for row in as_dict_list(filtered_recs["rows"])}
    assert "config-low-n" not in filtered_configs
    filtered_filters = as_dict(filtered["filters_applied"])
    assert filtered_filters["min_attempted"] == MIN_ATTEMPTED


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
    result_rows = as_dict_list(result["rows"])
    rows = {str(row["config"]): row for row in result_rows}
    valid_eff = as_dict(as_dict(rows["valid"]["derived"])["efficiency"])
    assert as_dict(valid_eff["cost_per_attempt"])["value"] == VALID_COST_PER_ATTEMPT
    zero_eff = as_dict(as_dict(rows["zero"]["derived"])["efficiency"])
    assert as_dict(zero_eff["cost_per_attempt"])["reason"] == "zero_denominator"
    missing_eff = as_dict(as_dict(rows["missing"]["derived"])["efficiency"])
    assert (
        as_dict(missing_eff["cost_per_attempt"])["reason"] == "missing_or_invalid_input"
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
    eff = as_dict(report["efficiency"])
    assert as_dict_list(eff["specs"])[0]["name"] == "cost_per_attempt"


@pytest.mark.parametrize(
    "threshold_name", ["min_attempted", "min_pass_at_1", "min_tasks"]
)
def test_negative_quality_thresholds_are_rejected(threshold_name: str) -> None:
    """Reject negative values for every quality threshold option."""
    fns: list[Callable[..., object]] = [rank_rows]
    with pytest.raises(ValueError, match="non-negative"):
        _ = fns[0](
            ROWS,
            "pass_at_1",
            "desc",
            limit=None,
            **{threshold_name: -1},
        )


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
    default_rows = as_dict_list(default["rows"])
    assert [row["id"] for row in default_rows] == ["included"]
    assert default["filters_applied"] == {
        "source": "deep-swe",
        "eval_scope": "full",
        "included_in_score": True,
    }

    visible = filter_trials(rows, source=None, eval_scope=None, included_only=False)
    visible_rows = as_dict_list(visible["rows"])
    assert [row["id"] for row in visible_rows] == [row["id"] for row in rows]
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
    result_rows = as_dict_list(result["rows"])
    assert [row["config"] for row in result_rows] == ["ok"]
    row0_derived = as_dict(result_rows[0]["derived"])
    assert row0_derived["ci_width"] is None

    fns: list[Callable[..., object]] = [rank_rows, filter_trials]
    with pytest.raises(TypeError, match="thresholds"):
        _ = fns[0](
            ROWS,
            "pass_at_1",
            "desc",
            min_attempted="ten",
        )
    with pytest.raises(ValueError, match="non-negative"):
        _ = rank_rows(ROWS, "pass_at_1", "desc", limit=-1)
    with pytest.raises(TypeError, match="included_only"):
        _ = fns[1]([], included_only=1)


if __name__ == "__main__":
    _ = pytest.main([__file__])
