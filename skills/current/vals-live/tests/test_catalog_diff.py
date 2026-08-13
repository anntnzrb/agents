# Copyright 2026 Vals-live contributors.
# ruff: noqa: D102,S101,INP001
"""Exercise deterministic catalog change classification."""

import json
import unittest

from _path import FIXTURES
from vals_live.catalog_diff import diff


class CatalogDiffTests(unittest.TestCase):
    """Verify conservative added/removed/renamed classifications."""

    def load(self, name: str) -> object:
        return json.loads((FIXTURES / "catalog" / name).read_text(encoding="utf-8"))

    def test_add_remove_rename_metadata_schema(self) -> None:
        result = diff(self.load("baseline.json"), self.load("changed.json"))
        assert result["added"]
        assert result["removed"]
        assert result["renamed"]
        assert result["changed_metadata"]
        assert result["schema_changes"]

    def test_order_is_irrelevant(self) -> None:
        left = {
            "catalog": [
                {"benchmark_id": "a", "display_name": "A"},
                {"benchmark_id": "b", "display_name": "B"},
            ]
        }
        right = {
            "catalog": [
                {"benchmark_id": "b", "display_name": "B"},
                {"benchmark_id": "a", "display_name": "A"},
            ]
        }
        result = diff(left, right)
        assert result["added"] == []
        assert result["removed"] == []
        assert result["changed_metadata"] == []


if __name__ == "__main__":
    unittest.main()
