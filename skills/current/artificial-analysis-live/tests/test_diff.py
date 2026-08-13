"""Schema-aware Artificial Analysis diff tests."""

# ruff: noqa: CPY001, INP001, S101, SLF001, D103, TC003
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import _path  # noqa: F401
from artificial_analysis import cli
from artificial_analysis.diff import schema_aware_diff


def _snapshot(
    *, model_slug: str, model_name: str, score: int, duplicate: bool = False
) -> dict[str, object]:
    model = {"slug": model_slug, "name": model_name, "intelligence_index": score}
    models: list[dict[str, object]] = [model]
    if duplicate:
        models.append({**model, "intelligence_index": score + 1})
    return {
        "meta": {
            "schema_version": 2,
            "parser": "fixture-parser",
            "parser_version": "1",
            "freshness": {"mode": "fresh", "stale": False},
        },
        "models": models,
        "hosts": [],
        "hosts_models": [],
    }


def test_schema_aware_diff_is_opt_in_and_preserves_legacy_keys(tmp_path: Path) -> None:
    old = tmp_path / "old.json"
    new = tmp_path / "new.json"
    old.write_text(
        json.dumps(_snapshot(model_slug="model-a", model_name="Model A", score=70))
    )
    new.write_text(
        json.dumps(_snapshot(model_slug="model-a", model_name="Model A", score=72))
    )

    legacy = cli._diff_payload(SimpleNamespace(old_snapshot=old, new_snapshot=new))
    aware = cli._diff_payload(
        SimpleNamespace(old_snapshot=old, new_snapshot=new, schema_aware=True),
    )

    assert "schema_diff" not in legacy
    assert aware["added_endpoint_slugs"] == legacy["added_endpoint_slugs"]
    assert aware["removed_endpoint_slugs"] == legacy["removed_endpoint_slugs"]
    assert aware["provider_deltas"] == legacy["provider_deltas"]
    assert (
        aware["schema_diff"]["metrics"]["changed"][0]["metric"] == "intelligence_index"
    )


def test_schema_diff_keeps_stable_ids_and_reports_possible_rename_without_merge() -> (
    None
):
    old = _snapshot(model_slug="old-slug", model_name="Alpha Model", score=1)
    new = _snapshot(model_slug="new-slug", model_name="Alpha Model", score=1)

    result = schema_aware_diff(old, new)

    assert result["model_identities"]["removed"] == ["model:old-slug"]
    assert result["model_identities"]["added"] == ["model:new-slug"]
    rename = result["possible_renames"][0]
    assert rename["merge"] is False
    assert rename["before_id"] == "model:old-slug"
    assert rename["after_id"] == "model:new-slug"


def test_schema_diff_reports_conflicting_duplicates_deterministically() -> None:
    result = schema_aware_diff(
        _snapshot(model_slug="model-a", model_name="Model A", score=1, duplicate=True),
        _snapshot(model_slug="model-a", model_name="Model A", score=1),
    )

    assert result["duplicates"]["before"][0]["id"] == "model:model-a"
    assert result["duplicates"]["before"][0]["conflict"] is True
    assert result["duplicates"]["removed"][0]["id"] == "model:model-a"
