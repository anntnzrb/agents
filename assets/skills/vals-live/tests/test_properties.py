# Copyright 2026 Vals-live contributors.
# ruff: noqa: D102,S101,INP001
"""Exercise generated records and unknown-field properties."""

import json
import unittest

from vals_live.contracts import ParsedDocument, RawArtifact
from vals_live.discovery import discover
from vals_live.extraction import extract_document
from vals_live.normalization import normalize_document_records


class PropertyStyleTests(unittest.TestCase):
    """Verify generated-record identity invariants."""

    def document(self, root: object) -> ParsedDocument:
        raw = json.dumps(root, ensure_ascii=False).encode("utf-8")
        artifact = RawArtifact(
            "fixture://generated",
            "fixture://generated",
            raw,
            content_type="application/json",
            release="generated-v1",
        )
        return extract_document(artifact)

    def test_arbitrary_benchmark_and_unknown_fields(self) -> None:
        root = {
            "catalog": [
                {
                    "benchmark_id": "unicode-β",
                    "benchmark": "Never Before Seen",
                    "category": "new",
                }
            ],
            "rows": [
                {
                    "model": "m",
                    "model_id": "m",
                    "benchmark_id": "unicode-β",
                    "future_metric": {"value": "17", "unit": "count"},
                    "nested_unknown": {"a": [1, 2]},
                }
            ],
        }
        document = self.document(root)
        catalog = discover(document)
        assert catalog.entries[0]["source_id"] == "unicode-β"
        rows, diagnostics = normalize_document_records(document)
        assert rows[0]["raw_fields"]["future_metric"] == {
            "value": "17",
            "unit": "count",
        }
        assert "UNKNOWN_SCORE_SEMANTICS" in {item["code"] for item in diagnostics}

    def test_column_permutation_does_not_change_row_identity(self) -> None:
        first = self.document(
            {
                "rows": [
                    {
                        "model": "m",
                        "model_id": "m",
                        "benchmark_id": "b",
                        "score": {
                            "value": "72.4%",
                            "unit": "percent",
                            "definition": "score",
                        },
                        "latency": {
                            "value": "12",
                            "unit": "seconds",
                            "definition": "latency",
                        },
                    }
                ]
            }
        )
        second = self.document(
            {
                "rows": [
                    {
                        "latency": {
                            "value": "12",
                            "unit": "seconds",
                            "definition": "latency",
                        },
                        "benchmark_id": "b",
                        "score": {
                            "value": "72.4%",
                            "unit": "percent",
                            "definition": "score",
                        },
                        "model_id": "m",
                        "model": "m",
                    }
                ]
            }
        )
        first_rows, _ = normalize_document_records(first)
        second_rows, _ = normalize_document_records(second)
        assert first_rows[0]["model_variant_id"] == second_rows[0]["model_variant_id"]
        assert (
            first_rows[0]["metrics"]["score"]["value"]["normalized_value"]
            == second_rows[0]["metrics"]["score"]["value"]["normalized_value"]
        )

    def test_dynamic_category_key_survives(self) -> None:
        document = self.document(
            {
                "categories": {"A New Category!": {"tasks": ["t"]}},
                "rows": [
                    {
                        "model": "m",
                        "model_id": "m",
                        "benchmark_id": "b",
                        "category": "A New Category!",
                        "t": {"value": "1%", "unit": "percent", "definition": "t"},
                    }
                ],
            }
        )
        rows, _ = normalize_document_records(document)
        assert rows[0]["raw_fields"]["t"] == {
            "value": "1%",
            "unit": "percent",
            "definition": "t",
        }


if __name__ == "__main__":
    unittest.main()
