# Copyright 2026 Vals-live contributors.
"""Exercise every numbered deterministic fixture case."""

import json
import unittest
from typing import cast

import pytest

from _path import FIXTURES
from vals_live.catalog_diff import diff
from vals_live.contracts import ParsedDocument, RawArtifact
from vals_live.discovery import discover
from vals_live.extraction import ExtractionError, extract_document
from vals_live.normalization import normalize_document_records
from vals_live.parsing import parse
from vals_live.validation import validate_records


def _root(document: ParsedDocument) -> dict[str, object]:
    """Return the root object of a parsed fixture document."""
    return cast("dict[str, object]", document.root)


def _metric_value(row: dict[str, object], metric: str) -> dict[str, object]:
    """Return the value object of one metric field."""
    metrics = cast("dict[str, object]", row["metrics"])
    field = cast("dict[str, object]", metrics[metric])
    return cast("dict[str, object]", field["value"])


class NumberedFixtureCases(unittest.TestCase):
    """Keep all numbered fixture contracts material."""

    def json_doc(self, path: str) -> ParsedDocument:
        file = FIXTURES / path
        body = file.read_bytes()
        return extract_document(
            RawArtifact(
                f"fixture://vals/{path}",
                "fixture://vals",
                body,
                content_type="application/json",
                release="fixture-v1",
            )
        )

    def test_01_current_catalog(self) -> None:
        catalog = discover(self.json_doc("catalog/current.json"))
        assert catalog.entries

    def test_02_new_benchmark(self) -> None:
        catalog = discover(self.json_doc("catalog/new-benchmark.json"))
        assert "Novel Eval 9" in {entry["display_name"] for entry in catalog.entries}

    def test_03_new_category(self) -> None:
        document = self.json_doc("catalog/new-category.json")
        assert "categories" in _root(document)
        assert "Novel Category" in cast("list[object]", _root(document)["categories"])

    def test_04_new_score_column(self) -> None:
        rows, _ = normalize_document_records(
            self.json_doc("tables/new-score-column.json")
        )
        assert "new_score" in cast("dict[str, object]", rows[0]["raw_fields"])

    def test_05_reordered_columns(self) -> None:
        rows, _ = normalize_document_records(
            self.json_doc("tables/reordered-columns.json")
        )
        assert rows[0]["model"] == "Table Model"

    def test_06_variant(self) -> None:
        catalog, rows, _diagnostics, _metadata = parse(
            self.json_doc("models/new-variant.json")
        )
        assert len({row["model_variant_id"] for row in rows}) >= 2
        assert len(catalog.models) >= 2

    def test_07_rename(self) -> None:
        left = cast(
            "object",
            json.loads(
                (FIXTURES / "catalog/renamed-before.json").read_text(encoding="utf-8")
            ),
        )
        right = cast(
            "object",
            json.loads(
                (FIXTURES / "catalog/renamed-after.json").read_text(encoding="utf-8")
            ),
        )
        assert diff(left, right)["renamed"]

    def test_08_archive(self) -> None:
        catalog = discover(self.json_doc("catalog/archived.json"))
        assert catalog.entries[0]["status"] == "archived"

    def test_09_optional_missing(self) -> None:
        rows, _ = normalize_document_records(
            self.json_doc("records/missing-optional.json")
        )
        assert "cost_per_test" not in cast("dict[str, object]", rows[0]["metrics"])

    def test_10_placeholder_zero(self) -> None:
        rows, diagnostics = normalize_document_records(
            self.json_doc("values/placeholder-zero.json")
        )
        assert _metric_value(rows[0], "accuracy")["value_status"] == "missing"
        assert "PLACEHOLDER_VALUE" in {item["code"] for item in diagnostics}

    def test_11_sentinels(self) -> None:
        rows, diagnostics = normalize_document_records(
            self.json_doc("values/placeholder-sentinels.json")
        )
        assert all(
            _metric_value(row, "accuracy")["value_status"] == "missing" for row in rows
        )
        assert (
            len([item for item in diagnostics if item["code"] == "PLACEHOLDER_VALUE"])
            == 4
        )

    def test_12_percent(self) -> None:
        rows, _ = normalize_document_records(
            self.json_doc("values/percentage-string.json")
        )
        value = _metric_value(rows[0], "accuracy")["normalized_value"]
        assert value == 72.4

    def test_13_ratio_ambiguity(self) -> None:
        rows, diagnostics = normalize_document_records(
            self.json_doc("values/decimal-ratio.json")
        )
        assert _metric_value(rows[0], "score")["unit"] == "ratio"
        assert "NUMERIC_AMBIGUITY" in {item["code"] for item in diagnostics}

    def test_14_malformed(self) -> None:
        rows, diagnostics = normalize_document_records(
            self.json_doc("values/malformed-numeric.json")
        )
        assert _metric_value(rows[1], "score")["value_status"] == "unparsed"
        assert "MALFORMED_PAYLOAD" in {item["code"] for item in diagnostics}

    def test_15_duplicate(self) -> None:
        _catalog, rows, _diagnostics, _metadata = parse(
            self.json_doc("rows/duplicate-model-variant.json")
        )
        _rows, diagnostics, excluded = validate_records(rows)
        assert "DUPLICATE_MODEL_VARIANT" in {item["code"] for item in diagnostics}
        assert excluded

    def test_16_mixed_release(self) -> None:
        _catalog, rows, _diagnostics, _metadata = parse(
            self.json_doc("releases/mixed.json")
        )
        _rows, diagnostics, _excluded = validate_records(rows)
        assert "MIXED_RELEASE" in {item["code"] for item in diagnostics}

    def test_17_etag_fixture_metadata(self) -> None:
        payload = cast(
            "dict[str, object]",
            json.loads(
                (FIXTURES / "transport/etag-200.json").read_text(encoding="utf-8")
            ),
        )
        assert "etag" in payload
        assert "last_modified" in payload

    def test_18_404_fixture(self) -> None:
        payload = cast(
            "dict[str, object]",
            json.loads(
                (FIXTURES / "transport/release-404.json").read_text(encoding="utf-8")
            ),
        )
        assert payload["http_status"] == 404

    def test_19_embedded(self) -> None:
        artifact = RawArtifact(
            "fixture://embedded",
            "fixture://vals",
            (FIXTURES / "pages/embedded-json.html").read_bytes(),
            content_type="text/html",
        )
        assert extract_document(artifact).extraction_method == "embedded_json"

    def test_20_rsc(self) -> None:
        artifact = RawArtifact(
            "fixture://rsc",
            "fixture://vals",
            (FIXTURES / "pages/rsc-next-frames.html").read_bytes(),
            content_type="text/html",
        )
        assert extract_document(artifact).extraction_method == "rsc"

    def test_21_table(self) -> None:
        artifact = RawArtifact(
            "fixture://table",
            "fixture://vals",
            (FIXTURES / "pages/table-fallback.html").read_bytes(),
            content_type="text/html",
        )
        assert extract_document(artifact).extraction_method == "html_table"

    def test_22_unknown_score(self) -> None:
        _catalog, rows, diagnostics, _metadata = parse(
            self.json_doc("pages/unknown-score.json")
        )
        assert rows[0]["raw_fields"]
        assert "UNKNOWN_SCORE_SEMANTICS" in {item["code"] for item in diagnostics}

    def test_23_unknown_category(self) -> None:
        document = self.json_doc("pages/unknown-category.json")
        assert "Unmapped Future Category" in cast(
            "list[object]", _root(document)["categories"]
        )

    def test_24_js_required(self) -> None:
        artifact = RawArtifact(
            "fixture://js",
            "fixture://vals",
            (FIXTURES / "pages/js-required.html").read_bytes(),
            content_type="text/html",
        )
        with pytest.raises(ExtractionError) as context:
            _ = extract_document(artifact)
        assert context.value.code == "REQUIRES_RENDERED_SOURCE"

    def test_25_partial(self) -> None:
        artifact = RawArtifact(
            "fixture://partial",
            "fixture://vals",
            (FIXTURES / "pages/partial.html").read_bytes(),
            content_type="text/html",
        )
        document = extract_document(artifact)
        _catalog, rows, diagnostics, _metadata = parse(document)
        assert rows
        assert any(
            item["code"] in {"PLACEHOLDER_VALUE", "PARTIAL_EXTRACTION"}
            for item in diagnostics
        )


if __name__ == "__main__":
    _ = unittest.main()
