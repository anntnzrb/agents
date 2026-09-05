# Copyright (c) 2026
from __future__ import annotations

import json
import tempfile
import unittest
from hashlib import sha256
from io import StringIO
from pathlib import Path
from typing import TYPE_CHECKING, cast
from urllib.error import URLError

import pytest
from tests._path import SKILL_DIR
from tests.fakes.transport import QueueOpener, Response

from livebench import discovery
from livebench.cache import CacheStore
from livebench.catalog_diff import diff_catalog, load_snapshot_catalog
from livebench.cli import main
from livebench.commands import load_context
from livebench.contracts import RawArtifact, SkillError, SourceTarget
from livebench.extraction import extract_artifact
from livebench.normalization import numeric_value
from livebench.transport import FetchError, fetch_target

if TYPE_CHECKING:
    from urllib.request import Request

FIXTURES = SKILL_DIR / "tests" / "fixtures"


def fixture(name: str) -> Path:
    return FIXTURES / name


def _load_json(content: str | bytes) -> object:
    return cast("object", json.loads(content))


def _as_dict(value: object) -> dict[str, object]:
    return cast("dict[str, object]", value)


def _as_dict_list(value: object) -> list[dict[str, object]]:
    return cast("list[dict[str, object]]", value)


def transport_response(name: str) -> Response:
    payload = _as_dict(
        _load_json(fixture(f"transport/{name}.json").read_text(encoding="utf-8"))
    )
    raw_headers = cast("dict[object, object]", payload.get("headers", {}))
    return Response(
        str(payload.get("body", "")),
        status=int(cast("int | str", payload.get("status", 200))),
        headers={str(key): str(value) for key, value in raw_headers.items()},
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
        assert context.release.release_id == "fixture-release-1"
        categories = _as_dict(context.catalog["categories"])
        assert "coding" in categories
        assert context.catalog["models"]
        assert context.parsed.artifacts["score_table"].sha256

    def test_02_new_catalog_entry_without_registry_branch(self) -> None:
        context = load_context(
            release_selector="latest",
            snapshot=fixture("catalog/new-benchmark.json"),
            cache_dir=None,
            allow_stale=False,
            timeout=1,
        )
        categories = _as_dict(context.catalog["categories"])
        assert "new-benchmark-category" in categories
        columns = _as_dict(context.catalog["columns"])
        score_table = _as_dict(columns["score_table"])
        assert "novel_task" in score_table

    def test_03_dynamic_category_normalization(self) -> None:
        context = load_context(
            release_selector="latest",
            snapshot=fixture("catalog/new-category.json"),
            cache_dir=None,
            allow_stale=False,
            timeout=1,
        )
        categories = _as_dict(context.catalog["categories"])
        assert "arbitrary-unicode-category-v2" in categories
        cat_info = _as_dict(categories["arbitrary-unicode-category-v2"])
        assert cat_info["raw_label"] == "Arbitrary Unicode Category / v2"

    def test_04_extra_score_column_preserved(self) -> None:
        context = load_context(
            release_selector="latest",
            snapshot=fixture("tables/new-score-column.json"),
            cache_dir=None,
            allow_stale=False,
            timeout=1,
        )
        row = context.rows[0]
        raw_fields = _as_dict(row["raw_fields"])
        assert "new_unknown_metric" in raw_fields
        subtasks = _as_dict_list(row["subtasks"])
        assert any(item["raw_label"] == "new_unknown_metric" for item in subtasks)

    def test_05_reordered_columns_use_headers(self) -> None:
        path = fixture("tables/reordered-columns.json")
        payload = _as_dict(_load_json(path.read_text(encoding="utf-8")))
        score_rows = _as_dict_list(payload["score_rows"])
        assert score_rows[0]["task_two"] == "20"
        assert score_rows[0]["task_one"] == "10"

    def test_06_variants_not_merged(self) -> None:
        context = load_context(
            release_selector="latest",
            snapshot=fixture("records/coding-compare.json"),
            cache_dir=None,
            allow_stale=False,
            timeout=1,
        )
        identities = {row["model_variant_id"] for row in context.rows}
        assert len(identities) == 3
        assert all(row["provider"] for row in context.rows)

    def test_07_catalog_diff_reports_rename(self) -> None:
        left, _ = load_snapshot_catalog(str(fixture("catalog/renamed-before.json")))
        right, _ = load_snapshot_catalog(str(fixture("catalog/renamed-after.json")))
        result = diff_catalog(left, right)
        assert result["renamed"]

    def test_08_archived_release_remains_visible(self) -> None:
        payload = _as_dict(
            _load_json(fixture("catalog/archived.json").read_text(encoding="utf-8"))
        )
        assert payload["status"] == "archived"
        context = load_context(
            release_selector="latest",
            snapshot=fixture("catalog/archived.json"),
            cache_dir=None,
            allow_stale=False,
            timeout=1,
        )
        assert context.release.release_id == "fixture-release-archived"

    def test_09_missing_optional_fields_explicit(self) -> None:
        context = load_context(
            release_selector="latest",
            snapshot=fixture("records/missing-optional.json"),
            cache_dir=None,
            allow_stale=False,
            timeout=1,
        )
        cost = _as_dict(context.rows[0]["cost"])
        assert cost["status"] == "absent"
        subtasks = _as_dict_list(context.rows[0]["subtasks"])
        missing = next(item for item in subtasks if item["raw_label"] == "task_missing")
        score = _as_dict(missing["score"])
        assert score["value_status"] == "missing"

    def test_10_placeholder_zero_missing(self) -> None:
        context = load_context(
            release_selector="latest",
            snapshot=fixture("values/placeholder-zero.json"),
            cache_dir=None,
            allow_stale=False,
            timeout=1,
        )
        subtasks = _as_dict_list(context.rows[0]["subtasks"])
        score = _as_dict(subtasks[0]["score"])
        assert score["normalized_value"] is None
        assert "PLACEHOLDER_VALUE" in {item.code for item in context.diagnostics}

    def test_11_placeholder_sentinels_missing(self) -> None:
        context = load_context(
            release_selector="latest",
            snapshot=fixture("values/placeholder-sentinels.json"),
            cache_dir=None,
            allow_stale=False,
            timeout=1,
        )
        subtasks = _as_dict_list(context.rows[0]["subtasks"])
        assert all(
            _as_dict(item["score"])["value_status"] == "missing" for item in subtasks
        )

    def test_12_percent_string_provenance(self) -> None:
        context = load_context(
            release_selector="latest",
            snapshot=fixture("values/percentage-string.json"),
            cache_dir=None,
            allow_stale=False,
            timeout=1,
        )
        subtasks = _as_dict_list(context.rows[0]["subtasks"])
        score = _as_dict(subtasks[0]["score"])
        assert score["raw_value"] == "72.4%"
        assert score["normalized_value"] == 72.4
        assert score["unit"] == "percent"

    def test_13_bare_numeric_ambiguity(self) -> None:
        artifact = _artifact(
            "fixture-release-values", "score_table", b"model,task\nmodel,0.724\n"
        )
        value, diagnostics = numeric_value(
            "0.724", path="csv[row=0,column=task]", artifact=artifact, semantics="known"
        )
        assert value.metric_semantics_status == "ambiguous"
        assert any(item.code == "NUMERIC_AMBIGUITY" for item in diagnostics)

    def test_14_malformed_numeric_unparsed(self) -> None:
        context = load_context(
            release_selector="latest",
            snapshot=fixture("values/malformed-numeric.json"),
            cache_dir=None,
            allow_stale=False,
            timeout=1,
        )
        subtasks = _as_dict_list(context.rows[0]["subtasks"])
        score_obj = next(
            item["score"] for item in subtasks if item["raw_label"] == "bad_task"
        )
        score = _as_dict(score_obj)
        assert score["value_status"] == "unparsed"

    def test_15_duplicate_identity_diagnostic(self) -> None:
        context = load_context(
            release_selector="latest",
            snapshot=fixture("rows/duplicate-model-variant.json"),
            cache_dir=None,
            allow_stale=False,
            timeout=1,
        )
        assert "DUPLICATE_MODEL_VARIANT" in {item.code for item in context.diagnostics}
        assert any(item.get("_duplicate_conflict") for item in context.rows)

    def test_16_mixed_release_rejected(self) -> None:
        with pytest.raises(SkillError) as raised:
            _ = load_context(
                release_selector="latest",
                snapshot=fixture("releases/mixed.json"),
                cache_dir=None,
                allow_stale=False,
                timeout=1,
            )
        assert raised.value.code == "MIXED_RELEASE"

    def test_17_etag_and_304_reuse_exact_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first_payload = _as_dict(
                _load_json(
                    fixture("transport/etag-200.json").read_text(encoding="utf-8")
                )
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
            assert first.body == second.body
            assert second.cache_reused
            request = cast("Request", opener.requests[1])
            assert request.headers.get("If-none-match") == '"fixture-etag-1"'
            assert (
                request.headers.get("If-modified-since")
                == "Sun, 09 Aug 2026 00:00:00 GMT"
            )

    def test_18_404_is_visible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = _as_dict(
                _load_json(
                    fixture("transport/release-404.json").read_text(encoding="utf-8")
                )
            )
            target = SourceTarget(
                str(payload["release"]),
                "score_table",
                str(payload["url"]),
                "https://livebench.ai/",
            )
            with pytest.raises(FetchError) as raised:
                _ = fetch_target(
                    target,
                    CacheStore(Path(directory)),
                    opener=QueueOpener(transport_response("release-404")),
                )
            assert raised.value.code == "SOURCE_UNAVAILABLE"
            assert raised.value.details["http_status"] == 404

    def test_19_embedded_json_extraction(self) -> None:
        artifact = _artifact(
            "fixture-release-html",
            "catalog",
            fixture("pages/embedded-json.html").read_bytes(),
            content_type="text/html",
        )
        parsed, diagnostics = extract_artifact(artifact)
        assert parsed is not None
        assert parsed.extraction_method == "embedded_json"
        assert not diagnostics

    def test_20_rsc_frame_extraction(self) -> None:
        artifact = _artifact(
            "fixture-release-rsc",
            "catalog",
            fixture("pages/rsc-next-frames.html").read_bytes(),
            content_type="text/html",
        )
        parsed, _ = extract_artifact(artifact)
        assert parsed is not None
        assert parsed.extraction_method == "rsc_frame"

    def test_21_semantic_html_table_fallback(self) -> None:
        artifact = _artifact(
            "fixture-release-html",
            "catalog",
            fixture("pages/table-fallback.html").read_bytes(),
            content_type="text/html",
        )
        parsed, _ = extract_artifact(artifact)
        assert parsed is not None
        assert parsed.extraction_method == "html_table"
        root = _as_dict_list(parsed.root)
        assert root[0]["model"] == "table-model"

    def test_22_unknown_score_semantics_preserved(self) -> None:
        context = load_context(
            release_selector="latest",
            snapshot=fixture("pages/unknown-score.json"),
            cache_dir=None,
            allow_stale=False,
            timeout=1,
        )
        subtasks = _as_dict_list(context.rows[0]["subtasks"])
        unknown = next(
            item for item in subtasks if item["raw_label"] == "mystery_metric"
        )
        score = _as_dict(unknown["score"])
        assert score["metric_semantics_status"] == "unknown"
        assert score["value_status"] == "published"

    def test_23_unknown_category_dynamic(self) -> None:
        context = load_context(
            release_selector="latest",
            snapshot=fixture("pages/unknown-category.json"),
            cache_dir=None,
            allow_stale=False,
            timeout=1,
        )
        categories = _as_dict(context.catalog["categories"])
        assert "arbitrary-future-category" in categories

    def test_24_js_shell_requires_rendered_source(self) -> None:
        artifact = _artifact(
            "fixture-release-shell",
            "application",
            fixture("pages/js-required.html").read_bytes(),
            content_type="text/html",
        )
        parsed, diagnostics = extract_artifact(artifact)
        assert parsed is None
        assert diagnostics[0].code == "REQUIRES_RENDERED_SOURCE"

    def test_25_partial_extraction_has_warning(self) -> None:
        artifact = _artifact(
            "fixture-release-partial",
            "catalog",
            fixture("pages/partial.html").read_bytes(),
            content_type="text/html",
        )
        parsed, _ = extract_artifact(artifact)
        assert parsed is not None
        assert parsed.extraction_method == "html_table"
        root = _as_dict_list(parsed.root)
        assert root[0]["broken"] == "N/A"

    def test_cli_emits_one_compact_success_object(self) -> None:
        stdout = StringIO()
        status = main(
            ["leaderboard", "--snapshot", str(fixture("records/coding-compare.json"))],
            stdout=stdout,
            stderr=StringIO(),
        )
        assert status == 0
        assert len(stdout.getvalue().splitlines()) == 1
        payload = _as_dict(_load_json(stdout.getvalue()))
        assert payload["schema_version"] == "1"
        data = _as_dict(payload["data"])
        assert data["provenance"]

    def test_26_release_discovery_uses_last_advertised_entry(self) -> None:
        releases_disc = discovery.discover_releases(
            snapshot=fixture("releases/latest.json")
        )
        assert releases_disc.latest_id == "fixture-release-2"
        assert [entry["id"] for entry in releases_disc.releases] == [
            "fixture-release-1",
            "fixture-release-2",
        ]
        assert releases_disc.releases[-1]["new_field"] == "retained"

    def test_27_dynamic_bundle_selector_and_templates_are_source_backed(self) -> None:
        bundle = (
            'const releases=["2025-01-01","2025-02-02"];'
            "const latest=releases[releases.length-1];"
            "fetch(`./table_${latest}.csv`);"
            "fetch(`./categories_${latest}.json`);"
            "fetch(`./cost_${latest}.csv`);"
            'const variants=[{date:"2025-03-03"},{date:"2025-03-03"}];'
        )
        release_ids = discovery._release_ids(  # pyright: ignore[reportPrivateUsage]
            bundle
        )
        assert release_ids == ["2025-01-01", "2025-02-02"]
        templates = discovery._asset_templates(  # pyright: ignore[reportPrivateUsage]
            bundle, "https://livebench.ai/"
        )
        assert templates == {
            "table": "https://livebench.ai/table_{release}.csv",
            "category": "https://livebench.ai/categories_{release}.json",
            "cost": "https://livebench.ai/cost_{release}.csv",
        }

    def test_27_broken_release_asset_has_no_older_release_fallback(self) -> None:
        with pytest.raises(SkillError) as raised:
            _ = load_context(
                release_selector="latest",
                snapshot=fixture("releases/broken-asset.json"),
                cache_dir=None,
                allow_stale=False,
                timeout=1,
            )
        assert raised.value.code == "SOURCE_UNAVAILABLE"
        assert "broken-release" in str(raised.value.details)

    def test_28_network_failure_requires_explicit_stale_permission(self) -> None:
        payload = _as_dict(
            _load_json(
                fixture("transport/network-failure.json").read_text(encoding="utf-8")
            )
        )
        target = SourceTarget(
            str(payload["release"]),
            "score_table",
            str(payload["url"]),
            "https://livebench.ai/",
        )
        with (
            tempfile.TemporaryDirectory() as directory,
            pytest.raises(FetchError) as raised,
        ):
            _ = fetch_target(
                target,
                CacheStore(Path(directory)),
                allow_stale=bool(payload["allow_stale"]),
                opener=QueueOpener(URLError(str(payload["error"]))),
            )
        assert raised.value.code == "SOURCE_UNAVAILABLE"

    def test_29_explicit_ratio_definition_blocks_bare_ratio(self) -> None:
        context = load_context(
            release_selector="latest",
            snapshot=fixture("values/decimal-ratio.json"),
            cache_dir=None,
            allow_stale=False,
            timeout=1,
        )
        subtasks = _as_dict_list(context.rows[0]["subtasks"])
        scores: dict[str, dict[str, object]] = {
            str(item["raw_label"]): _as_dict(item["score"]) for item in subtasks
        }
        assert scores["explicit_ratio"]["unit"] == "ratio"
        assert scores["explicit_ratio"]["normalized_value"] == 0.724
        assert scores["bare_ratio"]["metric_semantics_status"] == "ambiguous"
        assert scores["bare_ratio"]["comparison_eligibility"] == "blocked"
        assert scores["bare_percent"]["metric_semantics_status"] == "ambiguous"

    def test_30_new_model_variants_keep_structured_identity(self) -> None:
        context = load_context(
            release_selector="latest",
            snapshot=fixture("models/new-variant.json"),
            cache_dir=None,
            allow_stale=False,
            timeout=1,
        )
        assert len({row["model_variant_id"] for row in context.rows}) == 3
        assert {row["provider"] for row in context.rows} == {
            "Provider A",
            "Provider B",
        }

    def test_31_subtask_breakdown_preserves_cost_and_categories(self) -> None:
        context = load_context(
            release_selector="latest",
            snapshot=fixture("records/subtask-breakdown.json"),
            cache_dir=None,
            allow_stale=False,
            timeout=1,
        )
        row = context.rows[0]
        subtasks = _as_dict_list(row["subtasks"])
        assert {item["raw_label"] for item in subtasks} == {
            "task_one",
            "task_two",
            "task_three",
        }
        cost = _as_dict(row["cost"])
        published = _as_dict(cost["published"])
        cost_per_task = _as_dict(published["cost_per_successful_task"])
        assert cost_per_task["raw_value"] == "0.02"
        overall = _as_dict(row["overall"])
        assert overall["metric_id"] != "pass_at_1"

    def test_32_code_quality_metric_remains_separate_raw_field(self) -> None:
        context = load_context(
            release_selector="latest",
            snapshot=fixture("records/code-quality.json"),
            cache_dir=None,
            allow_stale=False,
            timeout=1,
        )
        raw_fields = _as_dict(context.rows[0]["raw_fields"])
        assert raw_fields["code_quality"] == "0.91"
        categories = _as_dict(context.rows[0]["categories"])
        assert "code_quality" not in categories

    def test_33_manifests_validate_and_reject_invalid_catalogs(self) -> None:
        catalog, provenance = load_snapshot_catalog(
            str(fixture("manifests/current.json"))
        )
        assert catalog["categories"] == {}
        prov_freshness = _as_dict(provenance["freshness"])
        assert prov_freshness["mode"] == "snapshot"
        with pytest.raises(SkillError) as raised:
            _ = load_snapshot_catalog(str(fixture("manifests/invalid.json")))
        assert raised.value.code == "SNAPSHOT_INVALID"


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
        raw_bytes_ref=None,
        freshness_mode="snapshot",
        stale=False,
        historical=True,
        cache_reused=False,
        generated_at=None,
    )


if __name__ == "__main__":
    _ = unittest.main()
