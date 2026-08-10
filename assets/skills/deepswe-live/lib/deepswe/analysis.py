"""Pure transformations for published DeepSWE leaderboard and trial data.

The functions in this module deliberately do not fetch, aggregate, or otherwise
reinterpret benchmark data.  Leaderboard rows are copied and selected for
ranking; values calculated by this module are kept in ``derived``.
"""
# ruff: noqa: CPY001, EM101, EM102, TRY003

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from math import isfinite
from numbers import Real
from typing import TypeAlias

from .diagnostics import merge_diagnostics
from .identity import classify_duplicates
from .normalization import normalize_rows

JsonValue: TypeAlias = object
JsonRow: TypeAlias = dict[str, JsonValue]
RowsLike: TypeAlias = Sequence[Mapping[str, JsonValue]] | Mapping[str, JsonValue] | None

_IDENTITY_FIELDS: tuple[str, ...] = (
    "model",
    "reasoning_effort",
    "harness",
    "config",
)
_SCORE_FIELDS: tuple[str, ...] = (
    "pass_rate",
    "pass_at_1",
    "pass_at_4",
    "n_passed",
    "n_attempted",
    "n_tasks_attempted",
    "n_tasks_passed_any",
    "ci_passed",
    "ci_attempted",
    "ci_lo",
    "ci_hi",
    "ci_half",
)
_EFFICIENCY_FIELDS: tuple[str, ...] = (
    "mean_output_tokens",
    "mean_cost_usd",
    "mean_agent_steps",
)
_PARETO_METRICS: tuple[str, ...] = (
    "pass_at_1",
    "mean_output_tokens",
    "mean_cost_usd",
    "mean_agent_steps",
)


DEFAULT_PARETO_AXES: tuple[tuple[str, str], ...] = (
    ("pass_at_1", "desc"),
    ("mean_output_tokens", "asc"),
    ("mean_cost_usd", "asc"),
    ("mean_agent_steps", "asc"),
)
EXPECTED_PAIR_LENGTH = 2
IDENTITY_COMPONENT_COUNT = 4
LEGACY_IDENTITY_COMPONENT_COUNT = 3


def _rows(value: object, *, normalize: bool = True) -> list[JsonRow]:
    """Return shallow row copies from either rows or a common artifact wrapper."""
    if isinstance(value, Mapping):
        if "rows" in value:
            value = value.get("rows")
        else:
            for key in ("leaderboard", "trials", "payload", "data"):
                nested = value.get(key)
                if isinstance(nested, Mapping) and "rows" in nested:
                    value = nested.get("rows")
                    break
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []

    rows = [dict(row) for row in value if isinstance(row, Mapping)]
    if not normalize:
        return rows
    return normalize_rows(rows, source_path="$.rows")


def _evidence(
    row: Mapping[str, JsonValue], metric: str
) -> Mapping[str, JsonValue] | None:
    metrics = row.get("metrics")
    if not isinstance(metrics, Mapping):
        return None
    value = metrics.get(metric)
    return value if isinstance(value, Mapping) else None


def _metric_value(
    row: Mapping[str, JsonValue], metric: str, *, strict_semantics: bool = False
) -> Real | None:
    evidence = _evidence(row, metric)
    if strict_semantics:
        if evidence is None or evidence.get("comparison_eligibility") != "eligible":
            return None
        return _number(evidence.get("normalized_value"))
    return _number(row.get(metric))


def _metric_blockers(row: Mapping[str, JsonValue], metric: str) -> list[JsonValue]:
    evidence = _evidence(row, metric)
    if evidence is None:
        return ["MISSING_REQUIRED_INPUT"]
    reasons = evidence.get("blocked_reasons")
    if isinstance(reasons, Sequence) and not isinstance(
        reasons, (str, bytes, bytearray)
    ):
        return list(reasons)
    reason = evidence.get("comparison_eligibility")
    return [reason or "COMPARISON_INCOMPARABLE"]


def _number(value: object) -> Real | None:
    """Return finite JSON-like numbers, treating null and booleans as unavailable."""
    if not isinstance(value, Real) or isinstance(value, bool):
        return None
    try:
        if not isfinite(float(value)):
            return None
    except (OverflowError, ValueError):
        return None
    return value


def _threshold(value: object) -> Real | None:
    """Validate an optional numeric threshold without coercing caller values."""
    if value is None:
        return None
    numeric = _number(value)
    if numeric is None:
        message = "analysis thresholds must be finite numbers or null"
        raise TypeError(message)
    if numeric < 0:
        message = "analysis thresholds must be non-negative"
        raise ValueError(message)
    return numeric


def _limit(value: object) -> int | None:
    """Validate a result limit; zero is a valid request for no rows."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        message = "limit must be an integer or null"
        raise TypeError(message)
    if value < 0:
        message = "limit must be non-negative"
        raise ValueError(message)
    return value


def _order(value: str) -> str:
    """Normalize the explicit ascending/descending order accepted by rankings."""
    if not isinstance(value, str):
        message = "order must be a string"
        raise TypeError(message)
    normalized = value.strip().lower()
    if normalized in {"asc", "ascending", "increasing", "min", "minimize"}:
        return "asc"
    if normalized in {"desc", "descending", "decreasing", "max", "maximize"}:
        return "desc"
    message = "order must be ascending or descending"
    raise ValueError(message)


def _metric_name(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        message = "metric must be a non-empty string"
        raise ValueError(message)
    return value.strip()


def _normalize_pareto_axes(
    axes: Sequence[str | Mapping[str, object]] | None,
) -> list[tuple[str, str]]:
    values = DEFAULT_PARETO_AXES if axes is None else axes
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise TypeError("pareto_axes must be a sequence")
    normalized: list[tuple[str, str]] = []
    for value in values:
        if isinstance(value, str):
            parts = value.split(":", 1)
            if len(parts) != EXPECTED_PAIR_LENGTH:
                message = "Pareto axes must use metric:order"
                raise ValueError(message)
            metric, order = parts
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            if len(value) != EXPECTED_PAIR_LENGTH:
                message = "Pareto axis sequences require metric and order"
                raise ValueError(message)
            metric, order = value
        elif isinstance(value, Mapping):
            metric = value.get("metric")
            order = value.get("order")
        else:
            raise TypeError("Pareto axes must be strings, pairs, or mappings")
        if not isinstance(metric, str) or not isinstance(order, str):
            raise TypeError("Pareto axes require metric and order strings")
        normalized.append((_metric_name(metric), _order(order)))
    if not normalized:
        raise ValueError("pareto_axes must not be empty")
    return normalized


def _axis_metadata(axes: Sequence[tuple[str, str]]) -> list[JsonRow]:
    return [{"metric": metric, "order": order} for metric, order in axes]


def _value_at_path(row: Mapping[str, JsonValue], path: str) -> object:
    current: object = row
    for part in path.split("."):
        if not isinstance(current, Mapping):
            return None
        current = current.get(part)
    return current


def _normalize_efficiency_specs(
    specs: Sequence[str | Mapping[str, object]],
) -> list[tuple[str, str, str]]:
    if isinstance(specs, (str, bytes)):
        raise TypeError("efficiency_specs must be a sequence")
    normalized: list[tuple[str, str, str]] = []
    names: set[str] = set()
    for spec in specs:
        if isinstance(spec, str):
            name_and_formula = spec.split("=", 1)
            if len(name_and_formula) != EXPECTED_PAIR_LENGTH:
                message = "efficiency specs must use name=numerator/denominator"
                raise ValueError(message)
            name, formula = name_and_formula
            operands = formula.split("/", 1)
            if len(operands) != EXPECTED_PAIR_LENGTH:
                message = "efficiency specs must use name=numerator/denominator"
                raise ValueError(message)
            numerator, denominator = operands
        elif isinstance(spec, Mapping):
            name = spec.get("name")
            numerator = spec.get("numerator")
            denominator = spec.get("denominator")
        else:
            raise TypeError("efficiency specs must be strings or mappings")
        if not all(isinstance(value, str) for value in (name, numerator, denominator)):
            raise TypeError("efficiency specs require name, numerator, and denominator")
        clean_name = _metric_name(name)
        if clean_name in names:
            raise ValueError(f"duplicate efficiency name: {clean_name}")
        names.add(clean_name)
        normalized.append(
            (clean_name, _metric_name(numerator), _metric_name(denominator))
        )
    return normalized


def _ci_width(
    row: Mapping[str, JsonValue], *, strict_semantics: bool = False
) -> Real | None:
    lo = (
        _metric_value(row, "ci_lo", strict_semantics=strict_semantics)
        if strict_semantics
        else _number(row.get("ci_lo"))
    )
    hi = (
        _metric_value(row, "ci_hi", strict_semantics=strict_semantics)
        if strict_semantics
        else _number(row.get("ci_hi"))
    )
    if lo is None or hi is None:
        return None
    return hi - lo


def _decorate(
    row: Mapping[str, JsonValue],
    *,
    rank: int | None = None,
    strict_semantics: bool = False,
    blocked_reasons: Sequence[JsonValue] | None = None,
) -> JsonRow:
    """Copy a published row and append only module-derived fields under ``derived``."""
    item = dict(row)
    existing = item.get("derived")
    derived: JsonRow = dict(existing) if isinstance(existing, Mapping) else {}
    derived["value_status"] = "derived"
    derived["ci_width"] = _ci_width(row, strict_semantics=strict_semantics)
    if rank is not None or strict_semantics:
        derived["rank"] = rank
    if blocked_reasons:
        derived["comparison_eligibility"] = "blocked"
        derived["blocked_reasons"] = list(blocked_reasons)
    item["derived"] = derived
    item["value_status"] = "published"
    return item


def _passes_thresholds(
    row: Mapping[str, JsonValue],
    *,
    min_pass_at_1: Real | None,
    min_attempted: Real | None,
    min_tasks: Real | None,
    strict_semantics: bool = False,
) -> bool:
    checks = (
        ("pass_at_1", min_pass_at_1),
        ("n_attempted", min_attempted),
        ("n_tasks_attempted", min_tasks),
    )
    for field, threshold in checks:
        if threshold is None:
            continue
        value = _metric_value(row, field, strict_semantics=strict_semantics)
        if value is None or value < threshold:
            return False
    return True


def _filters(
    *,
    min_pass_at_1: Real | None,
    min_attempted: Real | None,
    min_tasks: Real | None,
    limit: int | None,
) -> dict[str, JsonValue]:
    return {
        "min_pass_at_1": min_pass_at_1,
        "min_attempted": min_attempted,
        "min_tasks": min_tasks,
        "limit": limit,
    }


def _safe_duplicate_identity(value: object) -> str:
    """Keep duplicate diagnostics metrics-only when anonymous rows are used."""
    if not isinstance(value, str):
        return "<anonymous>"
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return "<anonymous>"
    if isinstance(parsed, list) and len(parsed) == IDENTITY_COMPONENT_COUNT:
        return json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
    if (
        isinstance(parsed, list)
        and len(parsed) == LEGACY_IDENTITY_COMPONENT_COUNT
        and parsed[:2] != ["published_id", "row"]
    ):
        return json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
    return "<anonymous>"


def _duplicate_facts(
    rows: Sequence[Mapping[str, JsonValue]],
) -> tuple[set[int], list[dict[str, JsonValue]], list[dict[str, object]]]:
    """Classify duplicate identities without exposing row bodies."""
    report = classify_duplicates(rows)
    conflicting_indexes: set[int] = set()
    diagnostics: list[dict[str, object]] = []
    for bucket in ("identical", "conflicting"):
        groups = report.get(bucket, [])
        if not isinstance(groups, Sequence):
            continue
        for group in groups:
            if not isinstance(group, Mapping):
                continue
            indexes = group.get("row_indexes")
            row_indexes = (
                sorted(int(index) for index in indexes)
                if isinstance(indexes, Sequence)
                and not isinstance(indexes, (str, bytes, bytearray))
                else []
            )
            if bucket == "conflicting":
                conflicting_indexes.update(row_indexes)
            diagnostics.append(
                {
                    "code": (
                        "DUPLICATE_CONFLICT"
                        if bucket == "conflicting"
                        else "DUPLICATE_IDENTITY"
                    ),
                    "severity": "error" if bucket == "conflicting" else "warning",
                    "stage": "rank",
                    "message": (
                        "Conflicting rows share a configuration identity."
                        if bucket == "conflicting"
                        else "Identical rows share a configuration identity."
                    ),
                    "details": {
                        "identity": _safe_duplicate_identity(group.get("identity")),
                        "row_indexes": row_indexes,
                        "count": len(row_indexes),
                    },
                }
            )
    return conflicting_indexes, report, merge_diagnostics(diagnostics)


def rank_rows(  # noqa: C901, PLR0912, PLR0913
    rows: RowsLike,
    metric: str,
    order: str,
    *,
    min_pass_at_1: Real | None = None,
    min_attempted: Real | None = None,
    min_tasks: Real | None = None,
    limit: int | None = 10,
    strict_semantics: bool = False,
    strict_duplicates: bool = False,
) -> dict[str, JsonValue]:
    """Rank published rows, optionally requiring semantic eligibility."""
    metric_name = _metric_name(metric)
    normalized_order = _order(order)
    pass_threshold = _threshold(min_pass_at_1)
    attempted_threshold = _threshold(min_attempted)
    tasks_threshold = _threshold(min_tasks)
    result_limit = _limit(limit)
    if not isinstance(strict_semantics, bool):
        raise TypeError("strict_semantics must be a boolean")
    if not isinstance(strict_duplicates, bool):
        raise TypeError("strict_duplicates must be a boolean")
    strict_mode = strict_semantics or strict_duplicates
    source_rows = _rows(rows)
    conflicting_indexes, duplicate_report, duplicate_diagnostics = _duplicate_facts(
        source_rows
    )

    eligible: list[JsonRow] = []
    blocked: list[tuple[JsonRow, list[JsonValue]]] = []
    for index, row in enumerate(source_rows):
        if strict_mode and index in conflicting_indexes:
            blocked.append((row, ["DUPLICATE_CONFLICT"]))
            continue
        if not _passes_thresholds(
            row,
            min_pass_at_1=pass_threshold,
            min_attempted=attempted_threshold,
            min_tasks=tasks_threshold,
            strict_semantics=strict_semantics,
        ):
            if strict_mode:
                blocked.append((row, ["QUALITY_THRESHOLD"]))
            continue
        value = _metric_value(row, metric_name, strict_semantics=strict_semantics)
        if value is None:
            if strict_mode:
                blocked.append((row, _metric_blockers(row, metric_name)))
            continue
        eligible.append(row)

    reverse = normalized_order == "desc"
    eligible.sort(
        key=lambda row: (
            _metric_value(row, metric_name, strict_semantics=strict_semantics) or 0
        ),
        reverse=reverse,
    )
    eligible_count = len(eligible)
    if result_limit is not None:
        eligible = eligible[:result_limit]

    ranked = [
        _decorate(
            row,
            rank=index,
            strict_semantics=strict_semantics,
        )
        for index, row in enumerate(eligible, start=1)
    ]
    if strict_mode:
        ranked.extend(
            _decorate(
                row,
                rank=None,
                strict_semantics=True,
                blocked_reasons=reasons,
            )
            for row, reasons in blocked
        )
    result: dict[str, JsonValue] = {
        "value_status": "derived",
        "metric": metric_name,
        "order": normalized_order,
        "filters_applied": _filters(
            min_pass_at_1=pass_threshold,
            min_attempted=attempted_threshold,
            min_tasks=tasks_threshold,
            limit=result_limit,
        ),
        "rows": ranked,
        "count": len(ranked),
        "input_count": len(source_rows),
        "eligible_count": eligible_count,
    }
    if duplicate_diagnostics:
        result["diagnostics"] = duplicate_diagnostics
        result["duplicate_report"] = {
            bucket: [
                {
                    "identity": _safe_duplicate_identity(group.get("identity")),
                    "row_indexes": list(group.get("row_indexes", [])),
                    "count": len(group.get("row_indexes", [])),
                }
                for group in groups
                if isinstance(group, Mapping)
            ]
            for bucket, groups in duplicate_report.items()
            if bucket in {"identical", "conflicting"}
        }
    if strict_semantics:
        result["strict_semantics"] = True
    if strict_duplicates:
        result["strict_duplicates"] = True
    return result


def filter_trials(
    rows: RowsLike,
    *,
    source: str | None = "deep-swe",
    eval_scope: str | None = "full",
    included_only: bool = True,
    limit: int | None = None,
) -> dict[str, JsonValue]:
    """Apply the explicit, null-safe default trial inclusion filter.

    ``None`` for ``source`` or ``eval_scope`` explicitly disables that
    predicate.  ``included_only=False`` widens visibility instead of selecting
    rows whose ``included_in_score`` value is false.  Missing fields therefore
    never pass an enabled predicate.
    """
    if source is not None and not isinstance(source, str):
        message = "source must be a string or null"
        raise TypeError(message)
    if eval_scope is not None and not isinstance(eval_scope, str):
        message = "eval_scope must be a string or null"
        raise TypeError(message)
    if not isinstance(included_only, bool):
        message = "included_only must be a boolean"
        raise TypeError(message)
    result_limit = _limit(limit)
    source_rows = _rows(rows, normalize=False)

    selected: list[JsonRow] = []
    for row in source_rows:
        if source is not None and row.get("source") != source:
            continue
        if eval_scope is not None and row.get("eval_scope") != eval_scope:
            continue
        if included_only and row.get("included_in_score") is not True:
            continue
        selected.append(row)

    matched_count = len(selected)
    if result_limit is not None:
        selected = selected[:result_limit]

    filters_applied: dict[str, JsonValue] = {
        "source": source,
        "eval_scope": eval_scope,
        "included_in_score": True if included_only else None,
    }
    if result_limit is not None:
        filters_applied["limit"] = result_limit

    return {
        "rows": selected,
        "count": len(selected),
        "matched_count": matched_count,
        "input_count": len(source_rows),
        "filters_applied": filters_applied,
    }


def _eligible_rows(
    rows: Sequence[Mapping[str, JsonValue]],
    *,
    min_pass_at_1: Real | None,
    min_attempted: Real | None,
    min_tasks: Real | None,
    strict_semantics: bool = False,
) -> list[JsonRow]:
    return [
        dict(row)
        for row in rows
        if _passes_thresholds(
            row,
            min_pass_at_1=min_pass_at_1,
            min_attempted=min_attempted,
            min_tasks=min_tasks,
            strict_semantics=strict_semantics,
        )
    ]


def _raw_extrema(
    rows: Sequence[Mapping[str, JsonValue]], *, strict_semantics: bool = False
) -> dict[str, JsonValue]:
    """Select independent extrema from every published row, before filters."""
    extrema: dict[str, JsonValue] = {}
    for metric in _PARETO_METRICS:
        valued = [
            row
            for row in rows
            if _metric_value(row, metric, strict_semantics=strict_semantics) is not None
        ]
        if not valued:
            extrema[metric] = {"min": None, "max": None}
            continue
        minimum = min(
            valued,
            key=lambda row: (
                _metric_value(row, metric, strict_semantics=strict_semantics) or 0
            ),
        )
        maximum = max(
            valued,
            key=lambda row: (
                _metric_value(row, metric, strict_semantics=strict_semantics) or 0
            ),
        )
        extrema[metric] = {
            "min": _decorate(minimum, strict_semantics=strict_semantics),
            "max": _decorate(maximum, strict_semantics=strict_semantics),
        }
    return extrema


def _dominates(
    left: Mapping[str, JsonValue],
    right: Mapping[str, JsonValue],
    axes: Sequence[tuple[str, str]],
    *,
    strict_semantics: bool = False,
) -> bool:
    """Whether ``left`` is at least as good as ``right`` on every axis."""
    left_values = [
        _metric_value(left, metric, strict_semantics=strict_semantics)
        for metric, _ in axes
    ]
    right_values = [
        _metric_value(right, metric, strict_semantics=strict_semantics)
        for metric, _ in axes
    ]
    if any(value is None for value in (*left_values, *right_values)):
        return False
    comparisons = [
        left_value >= right_value if order == "desc" else left_value <= right_value
        for (left_value, right_value), (_, order) in zip(
            zip(left_values, right_values, strict=True),
            axes,
            strict=True,
        )
    ]
    strict = [
        left_value > right_value if order == "desc" else left_value < right_value
        for (left_value, right_value), (_, order) in zip(
            zip(left_values, right_values, strict=True),
            axes,
            strict=True,
        )
    ]
    return all(comparisons) and any(strict)


def pareto_rows(
    rows: RowsLike,
    axes: Sequence[str | Mapping[str, object]] | None = None,
    *,
    strict_semantics: bool = False,
) -> list[JsonRow]:
    """Return rows not dominated across explicitly configured metric axes."""
    normalized_axes = _normalize_pareto_axes(axes)
    source_rows = _rows(rows)
    candidates = [
        dict(row)
        for row in source_rows
        if all(
            _metric_value(row, metric, strict_semantics=strict_semantics) is not None
            for metric, _ in normalized_axes
        )
    ]
    frontier = [
        row
        for row in candidates
        if not any(
            other is not row
            and _dominates(
                other,
                row,
                normalized_axes,
                strict_semantics=strict_semantics,
            )
            for other in candidates
        )
    ]
    return [_decorate(row, strict_semantics=strict_semantics) for row in frontier]


def derive_efficiency(
    rows: RowsLike,
    specs: Sequence[str | Mapping[str, object]],
    *,
    strict_semantics: bool = False,
) -> dict[str, JsonValue]:
    """Add explicit numerator/denominator efficiencies under ``derived``."""
    normalized_specs = _normalize_efficiency_specs(specs)
    enriched: list[JsonRow] = []
    for row in _rows(rows):
        item = dict(row)
        existing = item.get("derived")
        derived: JsonRow = dict(existing) if isinstance(existing, Mapping) else {}
        efficiency: JsonRow = {}
        for name, numerator_field, denominator_field in normalized_specs:
            numerator = (
                _metric_value(row, numerator_field, strict_semantics=True)
                if strict_semantics and "." not in numerator_field
                else _number(_value_at_path(row, numerator_field))
            )
            denominator = (
                _metric_value(row, denominator_field, strict_semantics=True)
                if strict_semantics and "." not in denominator_field
                else _number(_value_at_path(row, denominator_field))
            )
            entry: JsonRow = {
                "value_status": "derived",
                "numerator_field": numerator_field,
                "denominator_field": denominator_field,
                "numerator": numerator,
                "denominator": denominator,
            }
            if numerator is None or denominator is None:
                entry["value"] = None
                entry["reason"] = (
                    "comparison_blocked"
                    if strict_semantics
                    else "missing_or_invalid_input"
                )
            elif denominator == 0:
                entry["value"] = None
                entry["reason"] = "zero_denominator"
            else:
                value = float(numerator) / float(denominator)
                if isfinite(value):
                    entry["value"] = value
                else:
                    entry["value"] = None
                    entry["reason"] = "non_finite_result"
            efficiency[name] = entry
        derived["efficiency"] = efficiency
        derived["value_status"] = "derived"
        item["derived"] = derived
        item["value_status"] = "published"
        enriched.append(item)
    return {
        "value_status": "derived",
        "specs": [
            {
                "name": name,
                "numerator": numerator,
                "denominator": denominator,
                "formula": f"{numerator}/{denominator}",
            }
            for name, numerator, denominator in normalized_specs
        ],
        "rows": enriched,
        "count": len(enriched),
    }


def build_report(  # noqa: PLR0913
    payload: Mapping[str, JsonValue] | Sequence[Mapping[str, JsonValue]] | None,
    *,
    min_pass_at_1: Real | None = None,
    min_attempted: Real | None = None,
    min_tasks: Real | None = None,
    limit: int | None = 10,
    pareto_axes: Sequence[str | Mapping[str, object]] | None = None,
    efficiency_specs: Sequence[str | Mapping[str, object]] | None = None,
    strict_semantics: bool = False,
) -> dict[str, JsonValue]:
    """Build a decision report without re-aggregating published rows."""
    pass_threshold = _threshold(min_pass_at_1)
    attempted_threshold = _threshold(min_attempted)
    tasks_threshold = _threshold(min_tasks)
    result_limit = _limit(limit)
    if not isinstance(strict_semantics, bool):
        raise TypeError("strict_semantics must be a boolean")
    source_rows = _rows(payload)
    normalized_axes = _normalize_pareto_axes(pareto_axes)

    recommendations = rank_rows(
        source_rows,
        "pass_at_1",
        "desc",
        min_pass_at_1=pass_threshold,
        min_attempted=attempted_threshold,
        min_tasks=tasks_threshold,
        limit=result_limit,
        strict_semantics=strict_semantics,
    )
    eligible = _eligible_rows(
        source_rows,
        min_pass_at_1=pass_threshold,
        min_attempted=attempted_threshold,
        min_tasks=tasks_threshold,
        strict_semantics=strict_semantics,
    )
    pareto = pareto_rows(
        eligible,
        normalized_axes,
        strict_semantics=strict_semantics,
    )

    report: dict[str, JsonValue] = {
        "value_status": "derived",
        "recommendations": recommendations,
        "raw_extrema": _raw_extrema(source_rows, strict_semantics=strict_semantics),
        "pareto": pareto,
        "pareto_count": len(pareto),
        "counts": {
            "input": len(source_rows),
            "eligible": len(eligible),
            "recommendations": int(recommendations["count"]),
            "pareto": len(pareto),
        },
        "filters_applied": _filters(
            min_pass_at_1=pass_threshold,
            min_attempted=attempted_threshold,
            min_tasks=tasks_threshold,
            limit=result_limit,
        ),
    }
    if strict_semantics:
        report["strict_semantics"] = True
        report["filters_applied"]["strict_semantics"] = True
    if pareto_axes is not None:
        report["pareto_axes"] = _axis_metadata(normalized_axes)
        report["filters_applied"]["pareto_axes"] = _axis_metadata(normalized_axes)
    if efficiency_specs is not None:
        report["efficiency"] = derive_efficiency(
            source_rows,
            efficiency_specs,
            strict_semantics=strict_semantics,
        )
        report["filters_applied"]["efficiency"] = list(efficiency_specs)
    if isinstance(payload, Mapping):
        for key in ("scope", "provenance", "generated_at", "raw_metadata"):
            value = payload.get(key)
            if value is not None:
                if isinstance(value, Mapping):
                    copied = dict(value)
                    if key == "scope":
                        copied["value_status"] = "derived"
                    report[key] = copied
                else:
                    report[key] = value
    return report


__all__ = [
    "DEFAULT_PARETO_AXES",
    "build_report",
    "derive_efficiency",
    "filter_trials",
    "pareto_rows",
    "rank_rows",
]
