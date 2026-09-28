"""Deterministic Phase 6 fixture-backed contract checks."""

from pathlib import Path

from artificial_analysis.contracts import as_dict, as_list, parse_json
from artificial_analysis.diff import schema_aware_diff
from artificial_analysis.values import (
    PlaceholderKind,
    classify_placeholder,
    parse_numeric,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _load(relative_path: str) -> dict[str, object]:
    path = FIXTURES / relative_path
    return as_dict(parse_json(path.read_text(encoding="utf-8")))


def test_stale_fixture_exposes_explicit_freshness_mode() -> None:
    snapshot = _load("snapshots/stale.json")
    meta = as_dict(snapshot["meta"])
    freshness = meta["freshness"]
    assert freshness == {
        "mode": "stale-last-good",
        "stale": True,
        "historical": False,
        "fallback": True,
    }


def test_schema_diff_fixture_preserves_fields_metrics_and_possible_rename() -> None:
    result = schema_aware_diff(_load("diff/old.json"), _load("diff/new.json"))

    assert as_dict(result["schema"])["changed"] is False
    parser_info = as_dict(result["parser"])
    assert as_dict(parser_info["version"])["changed"] is True
    assert as_dict(result["freshness"])["changed"] is True
    assert as_dict(result["metrics"])["changed"]
    assert as_dict(result["fields"])["changed"]
    assert as_dict(result["diagnostics"])["added"]
    possible_renames = as_list(result["possible_renames"])
    assert possible_renames
    assert all(as_dict(item)["merge"] is False for item in possible_renames)


def test_duplicate_fixture_is_visible_as_conflict_without_merging() -> None:
    snapshot = _load("snapshots/duplicates.json")
    result = schema_aware_diff(snapshot, snapshot)

    duplicates_dict = as_dict(result["duplicates"])
    duplicates = as_list(duplicates_dict["before"])
    assert len(duplicates) == 1
    dup0 = as_dict(duplicates[0])
    assert dup0["kind"] == "model"
    assert dup0["conflict"] is True


def test_placeholder_fixture_keeps_values_and_source_markers_safe() -> None:
    values = _load("values/placeholders.json")

    assert (
        classify_placeholder(values["not_available"]) is PlaceholderKind.NOT_AVAILABLE
    )
    assert classify_placeholder(values["dash"]) is PlaceholderKind.DASH
    marker = as_dict(values["source_marked_zero"])
    assert (
        classify_placeholder(marker["value"], source_marker=marker)
        is PlaceholderKind.SOURCE_MARKED_CHART_ZERO
    )
    assert parse_numeric(values["literal_zero"]).normalized_value == 0
