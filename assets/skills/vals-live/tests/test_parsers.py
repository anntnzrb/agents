# Copyright 2026 Vals-live contributors.
# ruff: noqa: D102,S101,INP001
"""Exercise layered source extraction precedence."""

import unittest

import pytest
from _path import FIXTURES
from vals_live.contracts import RawArtifact
from vals_live.extraction import ExtractionError, extract_document


class ExtractionTests(unittest.TestCase):
    """Verify layered JSON, RSC, island, and table extraction."""

    def artifact(self, name: str, content_type: str = "text/html") -> RawArtifact:
        path = FIXTURES / "pages" / name
        return RawArtifact(
            f"fixture://vals/{name}",
            "fixture://vals",
            path.read_bytes(),
            content_type=content_type,
            fetched_at="2026-08-09T00:00:00Z",
        )

    def test_embedded_json(self) -> None:
        document = extract_document(self.artifact("embedded-json.html"))
        assert document.extraction_method == "embedded_json"
        assert document.root["rows"][0]["model"] == "Embedded Model"

    def test_rsc_frames(self) -> None:
        document = extract_document(self.artifact("rsc-next-frames.html"))
        assert document.extraction_method == "rsc"
        assert document.root["frames"]

    def test_table_fallback(self) -> None:
        document = extract_document(self.artifact("table-fallback.html"))
        assert document.extraction_method == "html_table"
        assert document.root[0]["model"] == "Table Model"

    def test_js_shell_is_structured_failure(self) -> None:
        with pytest.raises(ExtractionError) as context:
            extract_document(self.artifact("js-required.html"))
        assert context.value.code == "REQUIRES_RENDERED_SOURCE"

    def test_malformed_top_level_json_falls_through_to_html(self) -> None:
        body = (
            b'{"rows":[{"model":"JSON Model","score":"72.4%"}]}'
            b"<table><tr><th>model</th><th>score</th></tr>"
            b"<tr><td>HTML</td><td>1%</td></tr></table>"
        )
        document = extract_document(
            RawArtifact(
                "fixture://precedence",
                "fixture://vals",
                body,
                content_type="application/json",
            )
        )
        assert document.extraction_method == "html_table"
        assert document.root[0]["model"] == "HTML"
        assert document.unknown_fields["malformed_candidates"][0]["path"] == "$"
        assert document.diagnostics[0]["code"] == "MALFORMED_PAYLOAD"

    def test_astro_wrappers_decode(self) -> None:
        body = (
            b'<astro-island props="'
            b"{&quot;benchmarkView&quot;:[0,{&quot;metadata&quot;:[0,"
            b"{&quot;benchmark_id&quot;:[0,&quot;astro&quot;]}]}]}"
            b'"></astro-island>'
        )
        document = extract_document(
            RawArtifact(
                "fixture://astro", "fixture://vals", body, content_type="text/html"
            )
        )
        assert document.extraction_method == "embedded_json"
        assert document.root["benchmarkView"]["metadata"]["benchmark_id"] == "astro"


if __name__ == "__main__":
    unittest.main()
