# Copyright 2026 Vals-live contributors.
# ruff: noqa: D102,S101,INP001
"""Exercise metric identity and conservative normalization."""

import json
import unittest

from _path import FIXTURES
from vals_live.contracts import ParsedDocument, RawArtifact
from vals_live.extraction import extract_document
from vals_live.normalization import (
    normalize_numeric,
)
from vals_live.parsing import parse


class NormalizationTests(unittest.TestCase):
    """Verify numeric and variant normalization gates."""

    def artifact(self, relative: str) -> RawArtifact:
        path = FIXTURES / relative
        content_type = "text/html" if path.suffix == ".html" else "application/json"
        return RawArtifact(
            f"fixture://vals/{relative}",
            "fixture://vals",
            path.read_bytes(),
            content_type=content_type,
            fetched_at="2026-08-09T00:00:00Z",
            release="fixture-v1",
        )

    def document(self, relative: str) -> ParsedDocument:
        return extract_document(self.artifact(relative))

    def test_percent_preserves_raw_and_provenance(self) -> None:
        artifact = self.artifact("values/percentage-string.json")
        result, diagnostics = normalize_numeric(
            "72.4%",
            source_path="$.score",
            field="score",
            artifact=artifact,
            extraction_method="official_json",
            definition="percent",
        )
        assert result["raw_value"] == "72.4%"
        assert result["normalized_value"] == 72.4  # noqa: PLR2004
        assert result["unit"] == "percent"
        assert result["normalization"] == "removed_percent_sign"
        assert result["source_evidence"]["source_path"] == "$.score"
        assert not diagnostics

    def test_ambiguous_bare_number_is_blocked(self) -> None:
        artifact = self.artifact("values/decimal-ratio.json")
        result, diagnostics = normalize_numeric(
            "0.724",
            source_path="$.score",
            field="score",
            artifact=artifact,
            extraction_method="official_json",
        )
        assert result["normalized_value"] is None
        assert result["metric_semantics_status"] == "ambiguous"
        assert "NUMERIC_AMBIGUITY" in result["blocked_reasons"]
        assert diagnostics[0]["code"] == "NUMERIC_AMBIGUITY"

    def test_placeholder_and_out_of_range(self) -> None:
        artifact = self.artifact("values/placeholder-zero.json")
        placeholder, pdiag = normalize_numeric(
            "0.0%",
            unit="percent",
            source_path="$.score",
            field="score",
            artifact=artifact,
            extraction_method="official_json",
        )
        assert placeholder["value_status"] == "missing"
        assert pdiag[0]["code"] == "PLACEHOLDER_VALUE"
        invalid, idiag = normalize_numeric(
            "101%",
            unit="percent",
            source_path="$.score",
            field="score",
            artifact=artifact,
            extraction_method="official_json",
        )
        assert invalid["normalized_value"] is None
        assert idiag[0]["code"] == "OUT_OF_RANGE"

    def test_malformed_is_unparsed(self) -> None:
        artifact = self.artifact("values/malformed-numeric.json")
        result, diagnostics = normalize_numeric(
            "not-a-number",
            unit="percent",
            source_path="$.score",
            field="score",
            artifact=artifact,
            extraction_method="official_json",
        )
        assert result["value_status"] == "unparsed"
        assert diagnostics[0]["code"] == "MALFORMED_PAYLOAD"

    def test_unknown_field_round_trip(self) -> None:
        document = self.document("pages/unknown-score.json")
        _catalog, rows, diagnostics, _metadata = parse(document)
        assert rows[0]["raw_fields"]["novel_quality_index"] == {
            "value": "17",
            "unit": "count",
        }
        assert any(item["code"] == "UNKNOWN_SCORE_SEMANTICS" for item in diagnostics)

    def test_variant_identity(self) -> None:
        document = self.document("models/new-variant.json")
        _catalog, rows, _diagnostics, _metadata = parse(document)
        assert len({row["model_variant_id"] for row in rows}) == 2  # noqa: PLR2004

    def test_all_numbered_json_cases_are_loadable(self) -> None:
        for path in (FIXTURES / "values").glob("*.json"):
            json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
