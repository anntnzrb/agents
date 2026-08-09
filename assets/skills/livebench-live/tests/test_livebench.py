# Copyright (c) 2026
from __future__ import annotations

import json
import tempfile
import unittest
from hashlib import sha256
from io import StringIO
from pathlib import Path
from urllib.error import URLError

from _path import SKILL_DIR
from fakes.transport import QueueOpener, Response
from livebench.cache import CacheStore
from livebench.catalog_diff import diff_catalog, load_snapshot_catalog
from livebench.cli import main
from livebench.commands import load_context
from livebench.contracts import RawArtifact, SkillError, SourceTarget
from livebench.discovery import _asset_templates, _release_ids, discover_releases
from livebench.extraction import extract_artifact
from livebench.normalization import numeric_value
from livebench.transport import FetchError, fetch_target

FIXTURES = SKILL_DIR / "tests" / "fixtures"


def fixture(name: str) -> Path:
    return FIXTURES / name


def transport_response(name: str) -> Response:
    payload = json.loads(fixture(f"transport/{name}.json").read_text(encoding="utf-8"))
    return Response(
        str(payload.get("body", "")),
        status=int(payload.get("status", 200)),
        headers={
            str(key): str(value)
            for key, value in dict(payload.get("headers", {})).items()
        },
        final_url=str(payload["url"]),
    )


class LiveBenchFixtures(unittest.TestCase):
    def test_01_current_catalog_discovery(self) -> None:
        context = load_context(
            release_selector="latest",
            snapshot=fixture("catalog/current.json"),
            cache_dir=None,
            allow_stale=False,
            timeout=1,
        )
        self.assertEqual(context.release.release_id, "fixture-release-1")
        self.assertIn("coding", context.catalog["categories"])
        self.assertTrue(context.catalog["models"])
        self.assertTrue(context.parsed.artifacts["score_table"].sha256)

    def test_02_new_catalog_entry_without_registry_branch(self) -> None:
        context = load_context(
            release_selector="latest",
            snapshot=fixture("catalog/new-benchmark.json"),
            cache_dir=None,
            allow_stale=False,
            timeout=1,
        )
        self.assertIn("new-benchmark-category", context.catalog["categories"])
        self.assertIn("novel_task", context.catalog["columns"]["score_table"])

    def test_03_dynamic_category_normalization(self) -> None:
        context = load_context(
            release_selector="latest",
            snapshot=fixture("catalog/new-category.json"),
            cache_dir=None,
            allow_stale=False,
            timeout=1,
        )
        self.assertIn("arbitrary-unicode-category-v2", context.catalog["categories"])
        self.assertEqual(
            context.catalog["categories"]["arbitrary-unicode-category-v2"]["raw_label"],
            "Arbitrary Unicode Category / v2",
        )

    def test_04_extra_score_column_preserved(self) -> None:
        context = load_context(
            release_selector="latest",
            snapshot=fixture("tables/new-score-column.json"),
            cache_dir=None,
            allow_stale=False,
            timeout=1,
        )
        row = context.rows[0]
        self.assertIn("new_unknown_metric", row["raw_fields"])
        self.assertTrue(
            any(item["raw_label"] == "new_unknown_metric" for item in row["subtasks"])
        )

    def test_05_reordered_columns_use_headers(self) -> None:
        path = fixture("tables/reordered-columns.json")
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["score_rows"][0]["task_two"], "20")
        self.assertEqual(payload["score_rows"][0]["task_one"], "10")

    def test_06_variants_not_merged(self) -> None:
        context = load_context(
            release_selector="latest",
            snapshot=fixture("records/coding-compare.json"),
            cache_dir=None,
            allow_stale=False,
            timeout=1,
        )
        identities = {row["model_variant_id"] for row in context.rows}
        self.assertEqual(len(identities), 3)
        self.assertTrue(all(row["provider"] for row in context.rows))

    def test_07_catalog_diff_reports_rename(self) -> None:
        left, _ = load_snapshot_catalog(str(fixture("catalog/renamed-before.json")))
        right, _ = load_snapshot_catalog(str(fixture("catalog/renamed-after.json")))
        result = diff_catalog(left, right)
        self.assertTrue(result["renamed"])

    def test_08_archived_release_remains_visible(self) -> None:
        payload = json.loads(
            fixture("catalog/archived.json").read_text(encoding="utf-8")
        )
        self.assertEqual(payload["status"], "archived")
        context = load_context(
            release_selector="latest",
            snapshot=fixture("catalog/archived.json"),
            cache_dir=None,
            allow_stale=False,
            timeout=1,
        )
        self.assertEqual(context.release.release_id, "fixture-release-archived")

    def test_09_missing_optional_fields_explicit(self) -> None:
        context = load_context(
            release_selector="latest",
            snapshot=fixture("records/missing-optional.json"),
            cache_dir=None,
            allow_stale=False,
            timeout=1,
        )
        self.assertEqual(context.rows[0]["cost"]["status"], "absent")
        missing = next(
            item
            for item in context.rows[0]["subtasks"]
            if item["raw_label"] == "task_missing"
        )
        self.assertEqual(missing["score"]["value_status"], "missing")

    def test_10_placeholder_zero_missing(self) -> None:
        context = load_context(
            release_selector="latest",
            snapshot=fixture("values/placeholder-zero.json"),
            cache_dir=None,
            allow_stale=False,
            timeout=1,
        )
        score = context.rows[0]["subtasks"][0]["score"]
        self.assertIsNone(score["normalized_value"])
        self.assertIn("PLACEHOLDER_VALUE", {item.code for item in context.diagnostics})

    def test_11_placeholder_sentinels_missing(self) -> None:
        context = load_context(
            release_selector="latest",
            snapshot=fixture("values/placeholder-sentinels.json"),
            cache_dir=None,
            allow_stale=False,
            timeout=1,
        )
        self.assertTrue(
            all(
                item["score"]["value_status"] == "missing"
                for item in context.rows[0]["subtasks"]
            )
        )

    def test_12_percent_string_provenance(self) -> None:
        context = load_context(
            release_selector="latest",
            snapshot=fixture("values/percentage-string.json"),
            cache_dir=None,
            allow_stale=False,
            timeout=1,
        )
        score = context.rows[0]["subtasks"][0]["score"]
        self.assertEqual(score["raw_value"], "72.4%")
        self.assertEqual(score["normalized_value"], 72.4)
        self.assertEqual(score["unit"], "percent")

    def test_13_bare_numeric_ambiguity(self) -> None:
        artifact = _artifact(
            "fixture-release-values", "score_table", b"model,task\nmodel,0.724\n"
        )
        value, diagnostics = numeric_value(
            "0.724", path="csv[row=0,column=task]", artifact=artifact, semantics="known"
        )
        self.assertEqual(value.metric_semantics_status, "ambiguous")
        self.assertTrue(any(item.code == "NUMERIC_AMBIGUITY" for item in diagnostics))

    def test_14_malformed_numeric_unparsed(self) -> None:
        context = load_context(
            release_selector="latest",
            snapshot=fixture("values/malformed-numeric.json"),
            cache_dir=None,
            allow_stale=False,
            timeout=1,
        )
        score = next(
            item["score"]
            for item in context.rows[0]["subtasks"]
            if item["raw_label"] == "bad_task"
        )
        self.assertEqual(score["value_status"], "unparsed")

    def test_15_duplicate_identity_diagnostic(self) -> None:
        context = load_context(
            release_selector="latest",
            snapshot=fixture("rows/duplicate-model-variant.json"),
            cache_dir=None,
            allow_stale=False,
            timeout=1,
        )
        self.assertIn(
            "DUPLICATE_MODEL_VARIANT", {item.code for item in context.diagnostics}
        )
        self.assertTrue(any(item.get("_duplicate_conflict") for item in context.rows))

    def test_16_mixed_release_rejected(self) -> None:
        with self.assertRaises(SkillError) as raised:
            load_context(
                release_selector="latest",
                snapshot=fixture("releases/mixed.json"),
                cache_dir=None,
                allow_stale=False,
                timeout=1,
            )
        self.assertEqual(raised.exception.code, "MIXED_RELEASE")

    def test_17_etag_and_304_reuse_exact_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first_payload = json.loads(
                fixture("transport/etag-200.json").read_text(encoding="utf-8")
            )
            target = SourceTarget(
                "fixture-release-transport",
                "score_table",
                str(first_payload["url"]),
                "https://livebench.ai/",
            )
            opener = QueueOpener(
                transport_response("etag-200"), transport_response("etag-304")
            )
            first = fetch_target(target, CacheStore(Path(directory)), opener=opener)
            second = fetch_target(target, CacheStore(Path(directory)), opener=opener)
            self.assertEqual(first.body, second.body)
            self.assertTrue(second.cache_reused)
            request = opener.requests[1]
            self.assertEqual(request.headers.get("If-none-match"), '"fixture-etag-1"')
            self.assertEqual(
                request.headers.get("If-modified-since"),
                "Sun, 09 Aug 2026 00:00:00 GMT",
            )

    def test_18_404_is_visible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = json.loads(
                fixture("transport/release-404.json").read_text(encoding="utf-8")
            )
            target = SourceTarget(
                str(payload["release"]),
                "score_table",
                str(payload["url"]),
                "https://livebench.ai/",
            )
            with self.assertRaises(FetchError) as raised:
                fetch_target(
                    target,
                    CacheStore(Path(directory)),
                    opener=QueueOpener(transport_response("release-404")),
                )
            self.assertEqual(raised.exception.code, "SOURCE_UNAVAILABLE")
            self.assertEqual(raised.exception.details["http_status"], 404)

    def test_19_embedded_json_extraction(self) -> None:
        artifact = _artifact(
            "fixture-release-html",
            "catalog",
            fixture("pages/embedded-json.html").read_bytes(),
            content_type="text/html",
        )
        parsed, diagnostics = extract_artifact(artifact)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.extraction_method, "embedded_json")
        self.assertFalse(diagnostics)

    def test_20_rsc_frame_extraction(self) -> None:
        artifact = _artifact(
            "fixture-release-rsc",
            "catalog",
            fixture("pages/rsc-next-frames.html").read_bytes(),
            content_type="text/html",
        )
        parsed, _ = extract_artifact(artifact)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.extraction_method, "rsc_frame")

    def test_21_semantic_html_table_fallback(self) -> None:
        artifact = _artifact(
            "fixture-release-html",
            "catalog",
            fixture("pages/table-fallback.html").read_bytes(),
            content_type="text/html",
        )
        parsed, _ = extract_artifact(artifact)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.extraction_method, "html_table")
        self.assertEqual(parsed.root[0]["model"], "table-model")

    def test_22_unknown_score_semantics_preserved(self) -> None:
        context = load_context(
            release_selector="latest",
            snapshot=fixture("pages/unknown-score.json"),
            cache_dir=None,
            allow_stale=False,
            timeout=1,
        )
        unknown = next(
            item
            for item in context.rows[0]["subtasks"]
            if item["raw_label"] == "mystery_metric"
        )
        self.assertEqual(unknown["score"]["metric_semantics_status"], "unknown")
        self.assertEqual(unknown["score"]["value_status"], "published")

    def test_23_unknown_category_dynamic(self) -> None:
        context = load_context(
            release_selector="latest",
            snapshot=fixture("pages/unknown-category.json"),
            cache_dir=None,
            allow_stale=False,
            timeout=1,
        )
        self.assertIn("arbitrary-future-category", context.catalog["categories"])

    def test_24_js_shell_requires_rendered_source(self) -> None:
        artifact = _artifact(
            "fixture-release-shell",
            "application",
            fixture("pages/js-required.html").read_bytes(),
            content_type="text/html",
        )
        parsed, diagnostics = extract_artifact(artifact)
        self.assertIsNone(parsed)
        self.assertEqual(diagnostics[0].code, "REQUIRES_RENDERED_SOURCE")

    def test_25_partial_extraction_has_warning(self) -> None:
        artifact = _artifact(
            "fixture-release-partial",
            "catalog",
            fixture("pages/partial.html").read_bytes(),
            content_type="text/html",
        )
        parsed, _ = extract_artifact(artifact)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.extraction_method, "html_table")
        self.assertEqual(parsed.root[0]["broken"], "N/A")

    def test_cli_emits_one_compact_success_object(self) -> None:

        stdout = StringIO()
        status = main(
            ["leaderboard", "--snapshot", str(fixture("records/coding-compare.json"))],
            stdout=stdout,
            stderr=StringIO(),
        )
        self.assertEqual(status, 0)
        self.assertEqual(len(stdout.getvalue().splitlines()), 1)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["schema_version"], "1")
        self.assertTrue(payload["data"]["provenance"])

    def test_26_release_discovery_uses_last_advertised_entry(self) -> None:
        discovery = discover_releases(snapshot=fixture("releases/latest.json"))
        self.assertEqual(discovery.latest_id, "fixture-release-2")
        self.assertEqual(
            [entry["id"] for entry in discovery.releases],
            ["fixture-release-1", "fixture-release-2"],
        )
        self.assertEqual(discovery.releases[-1]["new_field"], "retained")

    def test_27_dynamic_bundle_selector_and_templates_are_source_backed(self) -> None:
        bundle = (
            'const releases=["2025-01-01","2025-02-02"];'
            "const latest=releases[releases.length-1];"
            "fetch(`./table_${latest}.csv`);"
            "fetch(`./categories_${latest}.json`);"
            "fetch(`./cost_${latest}.csv`);"
            'const variants=[{date:"2025-03-03"},{date:"2025-03-03"}];'
        )
        self.assertEqual(_release_ids(bundle), ["2025-01-01", "2025-02-02"])
        self.assertEqual(
            _asset_templates(bundle, "https://livebench.ai/"),
            {
                "table": "https://livebench.ai/table_{release}.csv",
                "category": "https://livebench.ai/categories_{release}.json",
                "cost": "https://livebench.ai/cost_{release}.csv",
            },
        )

    def test_27_broken_release_asset_has_no_older_release_fallback(self) -> None:
        with self.assertRaises(SkillError) as raised:
            load_context(
                release_selector="latest",
                snapshot=fixture("releases/broken-asset.json"),
                cache_dir=None,
                allow_stale=False,
                timeout=1,
            )
        self.assertEqual(raised.exception.code, "SOURCE_UNAVAILABLE")
        self.assertIn("broken-release", str(raised.exception.details))

    def test_28_network_failure_requires_explicit_stale_permission(self) -> None:
        payload = json.loads(
            fixture("transport/network-failure.json").read_text(encoding="utf-8")
        )
        target = SourceTarget(
            str(payload["release"]),
            "score_table",
            str(payload["url"]),
            "https://livebench.ai/",
        )
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaises(FetchError) as raised,
        ):
            fetch_target(
                target,
                CacheStore(Path(directory)),
                allow_stale=bool(payload["allow_stale"]),
                opener=QueueOpener(URLError(str(payload["error"]))),
            )
        self.assertEqual(raised.exception.code, "SOURCE_UNAVAILABLE")

    def test_29_explicit_ratio_definition_blocks_bare_ratio(self) -> None:
        context = load_context(
            release_selector="latest",
            snapshot=fixture("values/decimal-ratio.json"),
            cache_dir=None,
            allow_stale=False,
            timeout=1,
        )
        scores = {
            item["raw_label"]: item["score"] for item in context.rows[0]["subtasks"]
        }
        self.assertEqual(scores["explicit_ratio"]["unit"], "ratio")
        self.assertEqual(scores["explicit_ratio"]["normalized_value"], 0.724)
        self.assertEqual(scores["bare_ratio"]["metric_semantics_status"], "ambiguous")
        self.assertEqual(scores["bare_ratio"]["comparison_eligibility"], "blocked")
        self.assertEqual(scores["bare_percent"]["metric_semantics_status"], "ambiguous")

    def test_30_new_model_variants_keep_structured_identity(self) -> None:
        context = load_context(
            release_selector="latest",
            snapshot=fixture("models/new-variant.json"),
            cache_dir=None,
            allow_stale=False,
            timeout=1,
        )
        self.assertEqual(len({row["model_variant_id"] for row in context.rows}), 3)
        self.assertEqual(
            {row["provider"] for row in context.rows}, {"Provider A", "Provider B"}
        )

    def test_31_subtask_breakdown_preserves_cost_and_categories(self) -> None:
        context = load_context(
            release_selector="latest",
            snapshot=fixture("records/subtask-breakdown.json"),
            cache_dir=None,
            allow_stale=False,
            timeout=1,
        )
        row = context.rows[0]
        self.assertEqual(
            {item["raw_label"] for item in row["subtasks"]},
            {"task_one", "task_two", "task_three"},
        )
        self.assertEqual(
            row["cost"]["published"]["cost_per_successful_task"]["raw_value"], "0.02"
        )
        self.assertNotEqual(row["overall"]["metric_id"], "pass_at_1")

    def test_32_code_quality_metric_remains_separate_raw_field(self) -> None:
        context = load_context(
            release_selector="latest",
            snapshot=fixture("records/code-quality.json"),
            cache_dir=None,
            allow_stale=False,
            timeout=1,
        )
        self.assertEqual(context.rows[0]["raw_fields"]["code_quality"], "0.91")
        self.assertNotIn("code_quality", context.rows[0]["categories"])

    def test_33_manifests_validate_and_reject_invalid_catalogs(self) -> None:
        catalog, provenance = load_snapshot_catalog(
            str(fixture("manifests/current.json"))
        )
        self.assertEqual(catalog["categories"], {})
        self.assertEqual(provenance["freshness"]["mode"], "snapshot")
        with self.assertRaises(SkillError) as raised:
            load_snapshot_catalog(str(fixture("manifests/invalid.json")))
        self.assertEqual(raised.exception.code, "SNAPSHOT_INVALID")


def _artifact(
    release: str, kind: str, body: bytes, *, content_type: str = "application/json"
) -> RawArtifact:

    digest = sha256(body).hexdigest()
    return RawArtifact(
        f"fixture:{release}:{kind}:{digest}",
        "livebench",
        release,
        kind,
        f"fixture://{kind}",
        "fixture://source",
        body,
        200,
        content_type,
        {},
        "2026-08-09T00:00:00Z",
        "2026-08-09T00:00:00Z",
        digest,
        len(body),
        None,
        "snapshot",
        False,
        True,
        False,
        None,
    )


if __name__ == "__main__":
    unittest.main()
