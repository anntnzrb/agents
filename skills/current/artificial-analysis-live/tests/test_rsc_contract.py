"""RSC and official API contract tests."""

# ruff: noqa: E501
from __future__ import annotations

import unittest
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from artificial_analysis.diagnostics import Diagnostic

import pytest

from artificial_analysis.rsc import (
    ExtractionError,
    FetchResult,
    build_snapshot_payload,
    extract_evaluation_rows,
    extract_lists,
    normalize_official_models,
    parse_next_payload,
    snapshot_slugs,
)


class TestRscExtraction(unittest.TestCase):
    def test_extract_lists_uses_alias_keys(self) -> None:
        frames: list[tuple[str, object]] = [
            (
                "x",
                {
                    "model_rows": [
                        {"slug": "m1", "name": "M1", "model_creator_id": "c1"},
                    ],
                    "providers": [
                        {
                            "slug": "p1",
                            "name": "Provider 1",
                            "website_url": "https://x",
                        },
                    ],
                    "host_models": [
                        {"slug": "p1_model-1", "host_id": "h1", "model_id": "m1"},
                        {"slug": "p1_model-2", "host_id": "h1", "model_id": "m2"},
                    ],
                },
            ),
        ]

        models, hosts, hosts_models = extract_lists(frames)

        assert len(models) == 1
        assert len(hosts) == 1
        assert len(hosts_models) == 2

    def test_extract_lists_uses_structural_heuristics(self) -> None:
        frames: list[tuple[str, object]] = [
            (
                "x",
                {
                    "bucketA": [
                        {"slug": "m1", "name": "Model 1", "intelligence_index": 10.0},
                        {"slug": "m2", "name": "Model 2", "intelligence_index": 11.0},
                    ],
                    "bucketB": [
                        {
                            "slug": "provider-1",
                            "name": "Provider 1",
                            "openai_compatible": True,
                        },
                        {
                            "slug": "provider-2",
                            "name": "Provider 2",
                            "openai_compatible": False,
                        },
                    ],
                    "bucketC": [
                        {
                            "slug": "provider-1_model-1",
                            "host_id": "h1",
                            "model_id": "m1",
                        },
                        {
                            "slug": "provider-2_model-2",
                            "host_id": "h2",
                            "model_id": "m2",
                        },
                    ],
                },
            ),
        ]

        models, hosts, hosts_models = extract_lists(frames)

        assert len(models) == 2
        assert len(hosts) == 2
        assert len(hosts_models) == 2

    def test_extract_lists_normalizes_current_rows_schema(self) -> None:
        frames: list[tuple[str, object]] = [
            (
                "x",
                {
                    "models": [
                        {"slug": "model-a", "name": "Model A"},
                        {"slug": "model-b", "name": "Model B"},
                    ],
                    "hosts": [
                        {"slug": "provider-one", "name": "Provider One"},
                        {"slug": "provider-two", "name": "Provider Two"},
                    ],
                    "rows": [
                        {
                            "label": "Provider One / Model A",
                            "hostApiId": "provider-one-api",
                            "host": {
                                "slug": "provider-one",
                                "name": "Provider One",
                                "websiteUrl": "https://provider-one.example",
                            },
                            "model": {
                                "slug": "model-a",
                                "name": "Model A",
                                "modelCreatorId": "creator-a",
                            },
                            "features": {
                                "contextWindowTokens": 128000,
                                "supportsFunctionCalling": True,
                            },
                            "pricing": {
                                "price1mInputTokens": 0.25,
                                "price1mOutputTokens": 1.25,
                                "price1mBlended3To1": 0.50,
                            },
                            "performance": {
                                "medianOutputTokensPerSecond": 82.4,
                                "medianTimeToFirstTokenSeconds": 0.37,
                                "medianEndToEndResponseTimeSeconds": 2.8,
                            },
                        },
                        {
                            "label": "Provider Two / Model B",
                            "hostApiId": "provider-two-api",
                            "host": {"slug": "provider-two", "name": "Provider Two"},
                            "model": {
                                "slug": "model-b",
                                "name": "Model B",
                                "modelCreatorId": "creator-b",
                            },
                            "features": {"contextWindowTokens": 64000},
                            "pricing": {
                                "price1mInputTokens": 0.10,
                                "price1mOutputTokens": 0.40,
                                "price1mBlended3To1": 0.175,
                            },
                            "performance": {
                                "medianOutputTokensPerSecond": 145.0,
                                "medianTimeToFirstTokenSeconds": 0.21,
                                "medianEndToEndResponseTimeSeconds": 1.9,
                            },
                        },
                        {
                            "label": "Malformed row",
                            "host": {"slug": "provider-one", "name": "Provider One"},
                            "model": {"name": "Missing Slug"},
                            "features": {"contextWindowTokens": 32000},
                            "pricing": {"price1mBlended3To1": 9.99},
                            "performance": {
                                "medianOutputTokensPerSecond": 1.0,
                                "medianTimeToFirstTokenSeconds": 9.0,
                                "medianEndToEndResponseTimeSeconds": 10.0,
                            },
                        },
                    ],
                },
            ),
        ]
        models, hosts, hosts_models = extract_lists(frames)

        assert len(models) == 2
        assert len(hosts) == 2
        assert len(hosts_models) == 2

        first = hosts_models[0]
        assert first["slug"] == "provider-one_model-a"
        assert first["name"] == "Provider One / Model A"
        assert first["host_api_id"] == "provider-one-api"
        first_model = cast("dict[str, object]", first["model"])
        assert first_model["model_creator_id"] == "creator-a"
        first_host = cast("dict[str, object]", first["host"])
        assert first_host["website_url"] == "https://provider-one.example"
        assert first["context_window_tokens"] == 128000
        assert first["supports_function_calling"] is True
        assert first["price_1m_input_tokens"] == 0.25
        assert first["price_1m_output_tokens"] == 1.25
        assert first["price_1m_blended_3_to_1"] == 0.5
        timescale = cast("dict[str, object]", first["timescaleData"])
        assert timescale["median_output_speed"] == 82.4
        assert timescale["median_time_to_first_chunk"] == 0.37
        e2e = cast("dict[str, object]", first["end_to_end_response_time_metrics"])
        assert e2e["total_time"] == 2.8

        second = hosts_models[1]
        assert second["slug"] == "provider-two_model-b"
        second_model = cast("dict[str, object]", second["model"])
        assert second_model["model_creator_id"] == "creator-b"

    def test_parse_next_payload_extracts_embedded_flight_frames(self) -> None:
        document = (
            "<script>self.__next_f.push([1,"
            '"0:{\\"rows\\":[{\\"name\\":\\"Model A\\",\\"score\\":72.5}]}'
            '"])</script>'
        )
        frames = parse_next_payload(document)
        rows = extract_evaluation_rows(frames)
        assert rows == [{"name": "Model A", "score": 72.5}]

    def test_extract_evaluation_rows_selects_largest_recognizable_list(self) -> None:
        frames: list[tuple[str, object]] = [
            (
                "0",
                {
                    "small": [{"name": "A", "score": 1}],
                    "large": [
                        {"name": "A", "score": 1},
                        {"name": "B", "score": 2},
                    ],
                },
            ),
        ]
        assert extract_evaluation_rows(frames) == [
            {"name": "A", "score": 1},
            {"name": "B", "score": 2},
        ]

    def test_extract_evaluation_rows_rejects_unrelated_lists(self) -> None:
        with pytest.raises(ExtractionError, match="recognizable model rows"):
            _ = extract_evaluation_rows(
                cast("list[tuple[str, object]]", [("0", {"rows": [{"value": 1}]})])
            )

    def test_snapshot_slugs_accepts_aliases(self) -> None:
        snapshot: dict[str, object] = {
            "endpoints": [
                {"slug": "provider-1_model-1", "host_id": "h1", "model_id": "m1"},
                {"slug": "provider-1_model-2", "host_id": "h1", "model_id": "m2"},
            ],
        }
        slugs = snapshot_slugs(snapshot)
        assert slugs == ["provider-1_model-1", "provider-1_model-2"]

    def test_official_models_merge_into_unique_slim_schema_v2_snapshot(self) -> None:
        rsc_model = {
            "slug": "shared",
            "name": "RSC name",
            "agentic_index": 77,
            "coding_index": 12,
            "intelligence_index": 11,
            "model_creators": {"name": "RSC"},
        }
        api = normalize_official_models(
            '{"status":200,"prompt_options":{},"data":[{"id":"api-id","slug":"shared","name":"API name","release_date":"2026-01-01","model_creator":{"name":"API"},"evaluations":{"artificial_analysis_coding_index":42,"artificial_analysis_intelligence_index":null},"pricing":{"price_1m_blended_3_to_1":3},"median_output_tokens_per_second":9,"median_time_to_first_token_seconds":1,"median_time_to_first_answer_token":2},{"id":"api-only","slug":"api-only","name":"API only","model_creator":{},"evaluations":{},"pricing":{}}]}',
        )
        rsc_result = FetchResult("", 200, {"etag": "rsc"}, "2026-01-01T00:00:00+00:00")
        api_result = FetchResult("", 200, {}, "2026-01-01T00:00:01+00:00")
        payload = build_snapshot_payload(
            models=[rsc_model],
            hosts=[{"slug": "host", "name": "Host"}],
            hosts_models=[
                {
                    "slug": "host_shared",
                    "host": {"slug": "host"},
                    "model": rsc_model,
                    "price_1m_blended_7_to_2_to_1": 4,
                },
            ],
            frame_count=1,
            rsc_result=rsc_result,
            rsc_etag="rsc",
            rsc_reused_cached_payload=False,
            official_result=api_result,
            official_models=api,
        )
        models: dict[str, dict[str, object]] = {
            str(model["slug"]): model
            for model in cast("list[dict[str, object]]", payload["models"])
        }
        assert set(payload) == {"meta", "models", "hosts", "hosts_models"}
        meta = cast("dict[str, object]", payload["meta"])
        assert meta["schema_version"] == 2
        assert payload["hosts"] == [{"slug": "host", "name": "Host"}]
        assert set(models) == {"api-only", "shared"}
        assert models["shared"]["name"] == "API name"
        assert models["shared"]["coding_index"] == 42
        assert models["shared"]["intelligence_index"] == 11
        pricing = cast("dict[str, object]", models["shared"]["pricing"])
        assert pricing["price_1m_blended_3_to_1"] == 3
        hosts_models_list = cast("list[dict[str, object]]", payload["hosts_models"])
        endpoint = hosts_models_list[0]
        assert endpoint["model_slug"] == "shared"
        assert endpoint["price_1m_blended_7_to_2_to_1"] == 4
        assert "model" not in endpoint
        sources = cast("dict[str, dict[str, object]]", meta["sources"])
        assert sources["official_api"]["unmatched_rsc_model_slugs"] == []
        assert sources["rsc"]["unmatched_api_model_slugs"] == ["api-only"]

    def test_official_model_envelope_validation_rejects_malformed_rows(self) -> None:
        with pytest.raises(ExtractionError, match="requires integer status"):
            _ = normalize_official_models(
                '{"status":"200","prompt_options":{},"data":[]}'
            )
        with pytest.raises(ExtractionError, match="require non-empty slug"):
            _ = normalize_official_models(
                '{"status":200,"prompt_options":{},"data":[{"slug":"","name":"x","model_creator":{},"evaluations":{},"pricing":{}}]}',
            )

    def test_unknown_source_fields_collisions_and_structured_identity(self) -> None:
        diagnostics: list[Diagnostic] = []
        models = normalize_official_models(
            (
                '{"status":200,"prompt_options":{},"data":['
                '{"slug":"model-a","name":"Model A","model_creator":{},'
                '"evaluations":{},"pricing":{},"newField":1,"new_field":1}'
                "]}"
            ),
            source_path="api.data",
            diagnostics=diagnostics,
        )
        raw_fields = cast("dict[str, object]", models[0]["raw_fields"])
        assert raw_fields["newField"] == 1
        assert raw_fields["new_field"] == 1
        identity = cast("dict[str, object]", models[0]["identity"])
        assert identity["model_slug"] == "model-a"
        raw_metadata = cast("dict[str, object]", models[0]["raw_metadata"])
        assert raw_metadata["source_path"] == "api.data.data[0]"
        assert any(item.code == "DUPLICATE_SOURCE_FIELD" for item in diagnostics)


if __name__ == "__main__":
    _ = unittest.main()
