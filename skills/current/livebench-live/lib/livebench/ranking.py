# Copyright (c) 2026
"""Comparability gates for release-pinned LiveBench rows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast


def comparison_gate(
    rows: Sequence[Mapping[str, object]], *, metric: str = "overall"
) -> dict[str, object]:
    """Evaluate release comparability for ranking."""
    blocked: list[str] = []
    releases: set[str] = set()
    for row in rows:
        release = row.get("release")
        if isinstance(release, Mapping):
            mapping = cast("Mapping[str, object]", release)
            releases.add(str(mapping.get("id")))
    if len(releases) != 1:
        blocked.append("release_identity_mismatch")
    values: list[float] = []
    for row in rows:
        value = row.get(metric)
        if not isinstance(value, Mapping):
            blocked.append(f"missing_{metric}")
            continue
        normalized = cast("Mapping[str, object]", value).get("normalized_value")
        if not isinstance(normalized, (int, float)) or isinstance(normalized, bool):
            blocked.append(f"unparsed_{metric}")
            continue
        status = cast("Mapping[str, object]", value).get("metric_semantics_status")
        eligibility = cast("Mapping[str, object]", value).get("comparison_eligibility")
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
        key=lambda row: (
            -float(
                cast(
                    "int | float",
                    cast("Mapping[str, object]", row[metric])["normalized_value"],
                )
            )
        ),
    )
    for index, row in enumerate(ordered, 1):
        row["rank"] = index
        row["rank_status"] = "eligible"
    return gate
