# Copyright (c) 2026
"""Comparability gates for release-pinned LiveBench rows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence


def comparison_gate(
    rows: Sequence[Mapping[str, object]], *, metric: str = "overall"
) -> dict[str, object]:
    """Comparison gate for the LiveBench adapter."""
    blocked: list[str] = []
    releases = {
        str(row.get("release", {}).get("id"))
        for row in rows
        if isinstance(row.get("release"), Mapping)
    }
    if len(releases) != 1:
        blocked.append("release_identity_mismatch")
    values: list[float] = []
    for row in rows:
        value = row.get(metric)
        if not isinstance(value, Mapping):
            blocked.append(f"missing_{metric}")
            continue
        normalized = value.get("normalized_value")
        if not isinstance(normalized, (int, float)) or isinstance(normalized, bool):
            blocked.append(f"unparsed_{metric}")
            continue
        if (
            value.get("metric_semantics_status") not in {"known", None}
            or value.get("comparison_eligibility") == "blocked"
        ):
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
        key=lambda row: -float(row[metric]["normalized_value"]),  # type: ignore[index]
    )
    for index, row in enumerate(ordered, 1):
        row["rank"] = index
        row["rank_status"] = "eligible"
    return gate
