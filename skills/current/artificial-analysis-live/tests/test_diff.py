"""Schema-aware Artificial Analysis diff tests."""

import argparse
import json
from pathlib import Path

from artificial_analysis import cli
from artificial_analysis.contracts import as_dict, as_list
from artificial_analysis.diff import schema_aware_diff


def _snapshot(
    *, model_slug: str, model_name: str, score: int, duplicate: bool = False
) -> dict[str, object]:
    model: dict[str, object] = {
        "slug": model_slug,
        "name": model_name,
        "intelligence_index": score,
    }
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
    _ = old.write_text(
        json.dumps(_snapshot(model_slug="model-a", model_name="Model A", score=70))
    )
    _ = new.write_text(
        json.dumps(_snapshot(model_slug="model-a", model_name="Model A", score=72))
    )

    legacy = cli._diff_payload(
        argparse.Namespace(old_snapshot=old, new_snapshot=new, schema_aware=False)
    )
    aware = cli._diff_payload(
        argparse.Namespace(old_snapshot=old, new_snapshot=new, schema_aware=True),
    )

    assert "schema_diff" not in legacy
    assert aware["added_endpoint_slugs"] == legacy["added_endpoint_slugs"]
    assert aware["removed_endpoint_slugs"] == legacy["removed_endpoint_slugs"]
    assert aware["provider_deltas"] == legacy["provider_deltas"]
    schema_diff = as_dict(aware["schema_diff"])
    metrics = as_dict(schema_diff["metrics"])
    changed = as_list(metrics["changed"])
    assert as_dict(changed[0])["metric"] == "intelligence_index"


def test_schema_diff_keeps_stable_ids_and_reports_possible_rename_without_merge() -> (
    None
):
    old = _snapshot(model_slug="old-slug", model_name="Alpha Model", score=1)
    new = _snapshot(model_slug="new-slug", model_name="Alpha Model", score=1)

    result = schema_aware_diff(old, new)

    model_identities = as_dict(result["model_identities"])
    assert model_identities["removed"] == ["model:old-slug"]
    assert model_identities["added"] == ["model:new-slug"]
    possible_renames = as_list(result["possible_renames"])
    rename = as_dict(possible_renames[0])
    assert rename["merge"] is False
    assert rename["before_id"] == "model:old-slug"
    assert rename["after_id"] == "model:new-slug"


def test_schema_diff_reports_conflicting_duplicates_deterministically() -> None:
    result = schema_aware_diff(
        _snapshot(model_slug="model-a", model_name="Model A", score=1, duplicate=True),
        _snapshot(model_slug="model-a", model_name="Model A", score=1),
    )

    duplicates = as_dict(result["duplicates"])
    before = as_list(duplicates["before"])
    removed = as_list(duplicates["removed"])
    assert as_dict(before[0])["id"] == "model:model-a"
    assert as_dict(before[0])["conflict"] is True
    assert as_dict(removed[0])["id"] == "model:model-a"
