"""Deterministic Phase 6 fixture-backed contract checks."""

# ruff: noqa: CPY001, INP001, S101, D103
from __future__ import annotations

import json
from pathlib import Path

import _path  # noqa: F401
from artificial_analysis.diff import schema_aware_diff
from artificial_analysis.values import (
    PlaceholderKind,
    classify_placeholder,
    parse_numeric,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _load(relative_path: str) -> dict[str, object]:
    path = FIXTURES / relative_path
    return json.loads(path.read_text(encoding="utf-8"))


def test_stale_fixture_exposes_explicit_freshness_mode() -> None:
    snapshot = _load("snapshots/stale.json")
    meta = snapshot["meta"]
    assert isinstance(meta, dict)
    freshness = meta["freshness"]
    assert freshness == {
        "mode": "stale-last-good",
        "stale": True,
        "historical": False,
        "fallback": True,
    }


def test_schema_diff_fixture_preserves_fields_metrics_and_possible_rename() -> None:
    result = schema_aware_diff(_load("diff/old.json"), _load("diff/new.json"))

    assert result["schema"]["changed"] is False
    assert result["parser"]["version"]["changed"] is True
    assert result["freshness"]["changed"] is True
    assert result["metrics"]["changed"]
    assert result["fields"]["changed"]
    assert result["diagnostics"]["added"]
    assert result["possible_renames"]
    assert all(item["merge"] is False for item in result["possible_renames"])


def test_duplicate_fixture_is_visible_as_conflict_without_merging() -> None:
    snapshot = _load("snapshots/duplicates.json")
    result = schema_aware_diff(snapshot, snapshot)

    duplicates = result["duplicates"]["before"]
    assert len(duplicates) == 1
    assert duplicates[0]["kind"] == "model"
    assert duplicates[0]["conflict"] is True


def test_placeholder_fixture_keeps_values_and_source_markers_safe() -> None:
    values = _load("values/placeholders.json")

    assert (
        classify_placeholder(values["not_available"]) is PlaceholderKind.NOT_AVAILABLE
    )
    assert classify_placeholder(values["dash"]) is PlaceholderKind.DASH
    marker = values["source_marked_zero"]
    assert isinstance(marker, dict)
    assert (
        classify_placeholder(marker["value"], source_marker=marker)
        is PlaceholderKind.SOURCE_MARKED_CHART_ZERO
    )
    assert parse_numeric(values["literal_zero"]).normalized_value == 0
