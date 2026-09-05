# Copyright (c) 2026
from __future__ import annotations

from tests._path import SKILL_DIR

from livebench.catalog_diff import diff_catalog, load_snapshot_catalog

FIXTURES = SKILL_DIR / "tests" / "fixtures" / "catalog"


def test_diff_reports_add_remove_rename_schema() -> None:
    left, _ = load_snapshot_catalog(str(FIXTURES / "baseline.json"))
    right, _ = load_snapshot_catalog(str(FIXTURES / "changed.json"))
    diff = diff_catalog(left, right)
    assert diff["added"]
    assert diff["removed"]
    assert diff["renamed"]
    assert diff["schema_changes"]


def test_diff_is_order_independent() -> None:
    left = {"categories": {"b": {"category_id": "b"}, "a": {"category_id": "a"}}}
    right = {"categories": {"a": {"category_id": "a"}, "b": {"category_id": "b"}}}
    assert diff_catalog(left, right)["added"] == []
    assert diff_catalog(left, right)["removed"] == []
