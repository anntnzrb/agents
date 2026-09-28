# Copyright (c) 2026
"""Comparability gates for release-pinned LiveBench rows."""

from typing import TYPE_CHECKING

from .contracts import is_mapping

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


def comparison_gate(
    rows: Sequence[Mapping[str, object]], *, metric: str = "overall"
) -> dict[str, object]:
    """Evaluate release comparability for ranking."""
    blocked: list[str] = []
    releases: set[str] = set()
    for row in rows:
        release = row.get("release")
        if is_mapping(release):
            releases.add(str(release.get("id")))
    if len(releases) != 1:
        blocked.append("release_identity_mismatch")
    values: list[float] = []
    for row in rows:
        value = row.get(metric)
        if not is_mapping(value):
            blocked.append(f"missing_{metric}")
            continue
        normalized = value.get("normalized_value")
        if not isinstance(normalized, (int, float)) or isinstance(normalized, bool):
            blocked.append(f"unparsed_{metric}")
            continue
        status = value.get("metric_semantics_status")
        eligibility = value.get("comparison_eligibility")
        if status not in {"known", None} or eligibility == "blocked":
            blocked.append(f"unknown_{metric}_semantics")
            continue
        values.append(float(normalized))
    status = "eligible" if not blocked and values else "blocked"
    return {
        "metric": metric,
        "status": status,
        "comparison_key": {
            "source": "livebench",
            "release_id": next(iter(releases), None),
            "metric_family": metric,
            "definition_hash": None,
            "unit": "source-defined",
            "scope": "release",
            "task_set": None,
            "denominator": None,
        },
        "blocked_reasons": sorted(set(blocked)),
    }


def _metric_sort_value(row: Mapping[str, object], metric: str) -> float:
    value = row.get(metric)
    if is_mapping(value):
        normalized = value.get("normalized_value")
        if isinstance(normalized, (int, float)) and not isinstance(normalized, bool):
            return -float(normalized)
    return 0.0


def rank(
    rows: list[dict[str, object]], *, metric: str = "overall"
) -> dict[str, object]:
    """Rank for the LiveBench adapter."""
    gate = comparison_gate(rows, metric=metric)
    if gate["status"] != "eligible":
        for row in rows:
            row["rank"] = None
            row["rank_status"] = "blocked"
        return gate
    ordered = sorted(
        rows,
        key=lambda row: _metric_sort_value(row, metric),
    )
    for index, row in enumerate(ordered, 1):
        row["rank"] = index
        row["rank_status"] = "eligible"
    return gate
