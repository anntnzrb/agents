# Copyright (c) 2026
"""Source-published formulas and comparison semantics for LiveBench."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

OVERALL_FORMULA = "mean_of_category_averages"
CATEGORY_FORMULA = "mean_available_subtask_values"
COST_FORMULA = "(sum cost / sum questions / selected score) * 100"
OVERALL_DEFINITION = "Overall — mean of category averages"

# This registry is keyed by semantic signals, never by today's
# release/category/model names.
METRIC_REGISTRY: dict[str, dict[str, object]] = {
    "subtask_score": {
        "unit": "source-defined",
        "scope": "subtask",
        "comparator": "maximize",
    },
    "category_score": {
        "unit": "source-defined",
        "scope": "category",
        "comparator": "maximize",
    },
    "overall": {"unit": "source-defined", "scope": "release", "comparator": "maximize"},
    "cost_per_question": {
        "unit": "per_question",
        "scope": "question",
        "comparator": "minimize",
    },
    "cost_per_successful_task": {
        "unit": "per_successful_task",
        "scope": "successful_task",
        "comparator": "minimize",
    },
    "input_tokens": {"unit": "tokens", "scope": "model", "comparator": "unknown"},
    "output_tokens": {"unit": "tokens", "scope": "model", "comparator": "unknown"},
}


def metric_semantics(field: str, *, mapped: bool = False) -> dict[str, object]:
    """Metric semantics for the LiveBench adapter."""
    if field in {"overall", "category_score"}:
        return {"metric_semantics_status": "known", **METRIC_REGISTRY[field]}
    if field in METRIC_REGISTRY:
        return {"metric_semantics_status": "known", **METRIC_REGISTRY[field]}
    if mapped:
        return {"metric_semantics_status": "known", **METRIC_REGISTRY["subtask_score"]}
    return {
        "metric_semantics_status": "unknown",
        "unit": None,
        "scope": "source-defined",
        "comparator": "unknown",
    }


def mean_available(values: Iterable[object]) -> float | None:
    """Mean available for the LiveBench adapter."""
    numbers = [
        float(value)
        for value in values
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    ]
    return sum(numbers) / len(numbers) if numbers else None


def derive_mean(
    values: Sequence[tuple[str, Mapping[str, object]]],
    *,
    formula: str,
    definition_source_path: str | None,
) -> dict[str, object]:
    """Derive mean for the LiveBench adapter."""
    usable = [
        (path, value)
        for path, value in values
        if value.get("normalized_value") is not None
    ]
    normalized = mean_available(value["normalized_value"] for _, value in usable)
    return {
        "raw_value": normalized,
        "normalized_value": normalized,
        "unit": "source-defined",
        "normalization": None,
        "source_path": None,
        "value_status": "derived",
        "metric_semantics_status": "known",
        "aggregation": formula,
        "definition": OVERALL_DEFINITION if formula == OVERALL_FORMULA else None,
        "derived": {
            "formula": formula,
            "input_paths": [path for path, _ in usable],
            "definition_source_path": definition_source_path,
        },
        "comparison_eligibility": "eligible" if normalized is not None else "blocked",
    }


def derive_selected_cost(
    cost_row: Mapping[str, object],
    task_keys: Sequence[str],
    selected_score: float | None,
    *,
    source_path_prefix: str,
) -> dict[str, object]:
    """Reproduce the app's selected-scope formula without touching published values."""
    costs: list[tuple[str, Decimal, Decimal]] = []
    for task in task_keys:
        cost_raw = cost_row.get(task)
        questions_raw = cost_row.get(f"nq_{task}")
        if cost_raw is None or questions_raw is None:
            continue
        try:
            cost = Decimal(str(cost_raw))
            questions = Decimal(str(questions_raw))
        except (InvalidOperation, TypeError, ValueError):
            continue
        if not cost.is_finite() or not questions.is_finite() or questions <= 0:
            continue
        costs.append((task, cost, questions))
    score = Decimal(str(selected_score)) if selected_score is not None else Decimal(0)
    total_questions = sum((questions for _, _, questions in costs), Decimal(0))
    if not costs or score <= 0 or total_questions <= 0:
        return {
            "raw_value": None,
            "normalized_value": None,
            "unit": "per_successful_task",
            "value_status": "missing",
            "missing_reason": "INSUFFICIENT_COST_SCOPE_INPUTS",
            "formula": COST_FORMULA,
            "input_paths": [f"{source_path_prefix}[{task}]" for task, _, _ in costs],
            "scope_identity": {
                "task_keys": list(task_keys),
                "denominator": "sum_questions",
                "score": selected_score,
            },
        }
    weighted_cost = sum((cost * questions for _, cost, questions in costs), Decimal(0))
    result = (weighted_cost / total_questions / score) * Decimal(100)
    return {
        "raw_value": str(result),
        "normalized_value": float(result),
        "unit": "per_successful_task",
        "value_status": "derived",
        "formula": COST_FORMULA,
        "input_paths": [f"{source_path_prefix}[{task}]" for task, _, _ in costs]
        + [f"{source_path_prefix}[nq_{task}]" for task, _, _ in costs],
        "scope_identity": {
            "task_keys": list(task_keys),
            "denominator": "sum_questions",
            "score": selected_score,
        },
    }
