# Copyright 2026 Vals-live contributors.
"""Vals identity, release, duplicate and comparability validation."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

from .diagnostics import make

MIN_DUPLICATE_ROWS = 2


def _record_key(row: Mapping[str, object]) -> tuple[object, ...]:
    return (
        row.get("model_variant_id"),
        row.get("benchmark_id"),
        row.get("benchmark_version"),
        row.get("release"),
    )


def _metric_signature(row: Mapping[str, object]) -> str:
    def stable(value: object) -> object:
        if isinstance(value, Mapping):
            return {
                str(key): stable(item)
                for key, item in value.items()
                if str(key)
                not in {
                    "source_evidence",
                    "source_path",
                    "artifact_id",
                    "fetched_at",
                    "observed_at",
                }
            }
        if isinstance(value, list):
            return [stable(item) for item in value]
        return value

    return json.dumps(
        stable(row.get("metrics", {})),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def validate_records(
    rows: list[dict[str, Any]], *, expected_release: str | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, object]], set[int]]:
    """Validate release, identity, and duplicate-row invariants."""
    diagnostics: list[dict[str, object]] = []
    duplicate_excluded: set[int] = set()
    releases = {
        str(row.get("release")) for row in rows if row.get("release") not in (None, "")
    }
    versions = {
        str(row.get("benchmark_version"))
        for row in rows
        if row.get("benchmark_version") not in (None, "")
    }
    if expected_release:
        releases.add(str(expected_release))
    if len(releases) > 1 or len(versions) > 1:
        diagnostics.append(
            make(
                "MIXED_RELEASE",
                "Rows do not share one exact Vals release/version identity.",
                severity="error",
                stage="validate",
                details={"releases": sorted(releases), "versions": sorted(versions)},
            )
        )
    groups: dict[tuple[object, ...], list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        key = _record_key(row)
        if key[0] is None or key[1] is None:
            diagnostics.append(
                make(
                    "MISSING_REQUIRED_IDENTITY",
                    "A row lacks benchmark or model-variant identity.",
                    severity="error",
                    stage="validate",
                    source_path=str(row.get("source_path")),
                )
            )
            duplicate_excluded.add(index)
        groups[key].append(index)
    for key, indexes in groups.items():
        if len(indexes) < MIN_DUPLICATE_ROWS:
            continue
        signatures = {_metric_signature(rows[index]) for index in indexes}
        same = len(signatures) == 1
        diagnostics.append(
            make(
                "DUPLICATE_MODEL_VARIANT",
                (
                    "Duplicate model-variant identity was observed; duplicates remain "
                    "visible and are collapsed only for ranking."
                )
                if same
                else (
                    "Conflicting duplicate model-variant rows are excluded "
                    "from ranking."
                ),
                severity="warning" if same else "blocker",
                stage="validate",
                details={
                    "identity": list(key),
                    "rows": indexes,
                    "byte_identical": same,
                },
            )
        )
        if not same:
            duplicate_excluded.update(indexes)
        else:
            duplicate_excluded.update(indexes[1:])
    usable = [
        row
        for index, row in enumerate(rows)
        if index not in duplicate_excluded and row.get("value_status") != "unparsed"
    ]
    if (
        rows
        and not usable
        and any(item.get("severity") in {"error", "blocker"} for item in diagnostics)
    ):
        diagnostics.append(
            make(
                "MISSING_REQUIRED_IDENTITY",
                "No usable rows remain after identity/release validation.",
                severity="error",
                stage="validate",
            )
        )
    return rows, diagnostics, duplicate_excluded


def _metric_value(row: Mapping[str, object], field: str) -> Mapping[str, object] | None:
    metrics = row.get("metrics")
    if not isinstance(metrics, Mapping):
        return None
    item = metrics.get(field)
    if not isinstance(item, Mapping):
        return None
    value = item.get("value")
    return value if isinstance(value, Mapping) else None


def comparison_gate(rows: Iterable[Mapping[str, object]], field: str) -> dict[str, Any]:
    """Evaluate whether rows are comparable for one metric field."""
    rows_list = list(rows)
    values = [_metric_value(row, field) for row in rows_list]
    blocked: list[str] = []
    if not rows_list:
        blocked.append("NO_ROWS")
    if any(value is None for value in values):
        blocked.append("MISSING_METRIC")
    known = [value for value in values if value is not None]
    if any(value.get("metric_semantics_status") != "known" for value in known):
        blocked.append("UNKNOWN_SCORE_SEMANTICS")
    units = {value.get("unit") for value in known}
    if len(units) > 1:
        blocked.append("UNIT_MISMATCH")
    releases = {row.get("release") or row.get("benchmark_version") for row in rows_list}
    if len(releases) > 1:
        blocked.append("MIXED_RELEASE")
    values_numeric = [value.get("normalized_value") for value in known]
    if any(not isinstance(number, (int, float)) for number in values_numeric):
        blocked.append("NON_NUMERIC")
    definitions = {
        str(row.get("benchmark_id")) + "|" + str(row.get("benchmark_version"))
        for row in rows_list
    }
    if len(definitions) > 1:
        blocked.append("BENCHMARK_MISMATCH")
    fallbacks = {str(row.get("fallback_inclusion") or "unknown") for row in rows_list}
    if "unknown" in fallbacks or len(fallbacks) > 1:
        blocked.append("FALLBACK_STATE_UNKNOWN_OR_MISMATCH")
    status = "eligible" if not blocked else "blocked"
    return {
        "metric": field,
        "status": status,
        "comparison_key": {
            "source": "vals",
            "benchmark_id": rows_list[0].get("benchmark_id") if rows_list else None,
            "release_id": rows_list[0].get("release")
            or rows_list[0].get("benchmark_version")
            if rows_list
            else None,
            "metric_family": field,
            "definition_hash": None,
            "unit": next(iter(units), None),
            "scope": "benchmark",
            "task_set": rows_list[0].get("task_count") if rows_list else None,
            "fallback_inclusion": rows_list[0].get("fallback_inclusion", "unknown")
            if rows_list
            else "unknown",
            "harness": rows_list[0].get("harness") if rows_list else None,
        },
        "blocked_reasons": sorted(set(blocked)),
    }


def rank_rows(
    rows: list[dict[str, Any]], *, field: str, excluded: set[int] | None = None
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Rank eligible rows while preserving blocked rows and reasons."""
    excluded = excluded or set()
    eligible_rows = [row for index, row in enumerate(rows) if index not in excluded]
    gate = comparison_gate(eligible_rows, field)
    for row in rows:
        rank = row.setdefault("rankings", {})
        rank[field] = None
    if gate["status"] != "eligible":
        return rows, gate
    ordered = sorted(
        enumerate(eligible_rows),
        key=lambda item: float(
            (_metric_value(item[1], field) or {}).get("normalized_value", 0.0)
        ),
        reverse=True,
    )
    for rank_number, (_, row) in enumerate(ordered, start=1):
        row.setdefault("rankings", {})[field] = rank_number
    return rows, gate


def overlap_metadata() -> tuple[list[dict[str, object]], str]:
    """Return declared dependencies and the composite independence class."""
    dependencies = [
        {
            "source": "artificial-analysis",
            "index_name": "Coding Agent Index",
            "benchmark": "DeepSWE",
            "canonical_benchmark_id": "deepswe:source-defined",
            "relationship": "direct_component",
            "population": None,
            "release": None,
            "certainty": "requirements_claim",
            "evidence": {"source_url": None, "source_path": None},
        },
        {
            "source": "artificial-analysis",
            "index_name": "Coding Agent Index",
            "benchmark": "Terminal-Bench v2",
            "canonical_benchmark_id": "terminal-bench:v2",
            "relationship": "direct_component",
            "population": None,
            "release": None,
            "certainty": "requirements_claim",
            "evidence": {"source_url": None, "source_path": None},
        },
        {
            "source": "artificial-analysis",
            "index_name": "Coding Agent Index",
            "benchmark": "SWE-Atlas-QnA",
            "canonical_benchmark_id": "swe-atlas-qna:source-defined",
            "relationship": "direct_component",
            "population": None,
            "release": None,
            "certainty": "requirements_claim",
            "evidence": {"source_url": None, "source_path": None},
        },
        {
            "source": "vals",
            "index_name": "Vals Index",
            "benchmark": "SWE-bench",
            "canonical_benchmark_id": "vals:swe-bench",
            "relationship": "possible_component",
            "population": None,
            "release": None,
            "certainty": "requirements_claim",
            "evidence": {"source_url": None, "source_path": None},
        },
        {
            "source": "vals",
            "index_name": "Vals Index",
            "benchmark": "Terminal-Bench",
            "canonical_benchmark_id": "vals:terminal-bench",
            "relationship": "possible_component",
            "population": None,
            "release": None,
            "certainty": "requirements_claim",
            "evidence": {"source_url": None, "source_path": None},
        },
    ]
    return dependencies, "derived_composite"
