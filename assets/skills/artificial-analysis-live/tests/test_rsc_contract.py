"""RSC and official API contract tests."""

# ruff: noqa: CPY001, D101, D102, E501, INP001, PLR2004, S101, SLF001
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import _path  # noqa: F401
import pytest
from artificial_analysis import cli
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
        frames = [
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
        frames = [
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
        frames = [
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
        assert first["model"]["model_creator_id"] == "creator-a"
        assert first["host"]["website_url"] == "https://provider-one.example"
        assert first["context_window_tokens"] == 128000
        assert first["supports_function_calling"] is True
        assert first["price_1m_input_tokens"] == 0.25
        assert first["price_1m_output_tokens"] == 1.25
        assert first["price_1m_blended_3_to_1"] == 0.5
        assert first["timescaleData"]["median_output_speed"] == 82.4
        assert first["timescaleData"]["median_time_to_first_chunk"] == 0.37
        assert first["end_to_end_response_time_metrics"]["total_time"] == 2.8

        assert hosts_models[1]["slug"] == "provider-two_model-b"
        assert hosts_models[1]["model"]["model_creator_id"] == "creator-b"

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
        frames = [
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
            extract_evaluation_rows([("0", {"rows": [{"value": 1}]})])

    def test_snapshot_slugs_accepts_aliases(self) -> None:
        snapshot = {
            "endpoints": [
                {"slug": "provider-1_model-1", "host_id": "h1", "model_id": "m1"},
                {"slug": "provider-1_model-2", "host_id": "h1", "model_id": "m2"},
            ],
        }
        slugs = snapshot_slugs(snapshot)
        assert slugs == ["provider-1_model-1", "provider-1_model-2"]

    def _coding_payload(
        self,
        frames: list[tuple[str, object]],
        **options: object,
    ) -> dict[str, object]:
        with tempfile.TemporaryDirectory() as temp_dir:
            options = {
                "output_json": str(Path(temp_dir) / "coding.json"),
                **options,
            }
            args = cli._coding_namespace(options)
            result = SimpleNamespace(
                body="ignored",
                fetched_at="2026-07-13T00:00:00+00:00",
                status_code=200,
            )
            with (
                patch.object(cli, "fetch_rsc", return_value=result),
                patch.object(cli, "parse_json_frames", return_value=frames),
            ):
                return cli._coding_payload(args)

    @staticmethod
    def _current_row(
        slug: str,
        score: float,
        creator: str,
        *,
        with_metrics: bool = True,
    ) -> dict[str, object]:
        row: dict[str, object] = {
            "slug": slug,
            "headlineValue": score,
            "modelCreator": {
                "name": creator,
                "slug": creator.lower().replace(" ", "-"),
            },
            "shortName": slug.replace("-", " ").title(),
            "isReasoning": True,
            "releaseDate": "2026-07-01",
            "isOpenWeights": False,
        }
        if with_metrics:
            row.update(
                {
                    "outputTokensPerTask": {
                        "output": 300,
                        "answer": 200,
                        "reasoning": 100,
                    },
                    "costPerTask": {
                        "total": 1.25,
                        "input": 0.10,
                        "nonCacheInput": 0.08,
                        "cacheRead": 0.01,
                        "cacheWrite": 0.01,
                        "output": 0.75,
                        "reasoning": 0.25,
                        "answer": 0.50,
                    },
                    "timePerTaskSeconds": 12.5,
                },
            )
        return row

    def test_coding_payload_normalizes_legacy_default_data(self) -> None:
        frames = [
            (
                "legacy",
                {
                    "defaultData": [
                        {
                            "slug": "legacy-alpha",
                            "name": "Legacy Alpha",
                            "coding_index": 81.2,
                            "tokenCounts": {
                                "inputTokens": 500,
                                "answerTokens": 200,
                                "reasoningTokens": 100,
                                "outputTokens": 300,
                            },
                            "evalCost": {
                                "totalCost": 1.25,
                                "inputCost": 0.10,
                                "answerCost": 0.50,
                                "reasoningCost": 0.25,
                            },
                        },
                        {
                            "slug": "legacy-beta",
                            "name": "Legacy Beta",
                            "coding_index": 72.4,
                            "tokenCounts": {
                                "inputTokens": 400,
                                "answerTokens": 150,
                                "reasoningTokens": 50,
                                "outputTokens": 200,
                            },
                            "evalCost": {
                                "totalCost": 0.80,
                                "inputCost": 0.08,
                                "answerCost": 0.30,
                                "reasoningCost": 0.12,
                            },
                        },
                    ],
                },
            ),
        ]

        payload = self._coding_payload(frames)

        assert payload["counts"]["matched_models"] == 2
        row = payload["rows"][0]
        assert row["model_slug"] == "legacy-alpha"
        assert row["coding"] == 81.2
        assert row["coding_token_counts"]["input_tokens"] == 500
        assert row["coding_token_counts"]["output_tokens"] == 300
        assert row["coding_eval_cost"]["total_cost"] == 1.25
        assert row["coding_eval_cost"]["answer_cost"] == 0.5

    def test_coding_payload_normalizes_current_models_task_metrics(self) -> None:
        frames = [
            (
                "current",
                {
                    "models": [
                        self._current_row("current-alpha", 88.4, "OpenAI"),
                        self._current_row("current-beta", 79.1, "OpenAI"),
                    ],
                },
            ),
        ]

        payload = self._coding_payload(frames)

        assert payload["counts"]["matched_models"] == 2
        row = payload["rows"][0]
        assert row["model_slug"] == "current-alpha"
        assert row["short_name"] == "Current Alpha"
        assert row["creator"] == "OpenAI"
        assert row["coding"] == 88.4
        assert row["is_reasoning"]
        assert row["release_date"] == "2026-07-01"
        assert row["coding_task_metrics"]["output_tokens_per_task"] == {
            "output_tokens": 300,
            "answer_tokens": 200,
            "reasoning_tokens": 100,
        }
        assert row["coding_task_metrics"]["cost_per_task_usd"] == {
            "total_cost": 1.25,
            "input_cost": 0.1,
            "non_cache_input_cost": 0.08,
            "cache_read_cost": 0.01,
            "cache_write_cost": 0.01,
            "output_cost": 0.75,
            "reasoning_cost": 0.25,
            "answer_cost": 0.5,
        }
        assert row["coding_task_metrics"]["time_per_task_seconds"] == 12.5

    def test_coding_payload_retains_current_score_without_task_metrics(self) -> None:
        frames = [
            (
                "current",
                {
                    "models": [
                        self._current_row(
                            "score-only",
                            77.7,
                            "OpenAI",
                            with_metrics=False,
                        ),
                        self._current_row(
                            "score-only-peer",
                            70.0,
                            "OpenAI",
                            with_metrics=False,
                        ),
                    ],
                },
            ),
        ]

        payload = self._coding_payload(frames)
        assert payload["counts"]["matched_models"] == 2

        row = payload["rows"][0]
        assert row["model_slug"] == "score-only"
        assert row["coding"] == 77.7
        metrics = row["coding_task_metrics"]
        assert metrics["output_tokens_per_task"] == {
            "output_tokens": None,
            "answer_tokens": None,
            "reasoning_tokens": None,
        }
        assert metrics["cost_per_task_usd"] == {
            "total_cost": None,
            "input_cost": None,
            "non_cache_input_cost": None,
            "cache_read_cost": None,
            "cache_write_cost": None,
            "output_cost": None,
            "reasoning_cost": None,
            "answer_cost": None,
        }
        assert metrics["time_per_task_seconds"] is None

    def test_coding_payload_rejects_unrelated_provider_snapshot(self) -> None:
        frames = [
            (
                "providers",
                {
                    "models": [
                        {
                            "slug": "provider-one_model-a",
                            "name": "Provider One / Model A",
                            "price1mInputTokens": 0.25,
                        },
                        {
                            "slug": "provider-two_model-b",
                            "name": "Provider Two / Model B",
                            "price1mInputTokens": 0.10,
                        },
                    ],
                },
            ),
        ]

        with pytest.raises(cli.ExtractionError):
            self._coding_payload(frames)

    def test_coding_payload_filters_and_sorts_current_rows_deterministically(
        self,
    ) -> None:
        frames = [
            (
                "current",
                {
                    "models": [
                        self._current_row("lab-alpha", 75.0, "Target Lab"),
                        self._current_row("lab-beta", 91.0, "Target Lab"),
                        self._current_row("other", 99.0, "Other Lab"),
                    ],
                },
            ),
        ]

        payload = self._coding_payload(
            frames,
            creator="target lab",
            sort_by="coding",
            order="desc",
            limit=10,
        )

        assert [row["model_slug"] for row in payload["rows"]] == [
            "lab-beta",
            "lab-alpha",
        ]

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
        models = {model["slug"]: model for model in payload["models"]}
        assert set(payload) == {"meta", "models", "hosts", "hosts_models"}
        assert payload["meta"]["schema_version"] == 2
        assert payload["hosts"] == [{"slug": "host", "name": "Host"}]
        assert set(models) == {"api-only", "shared"}
        assert models["shared"]["name"] == "API name"
        assert models["shared"]["coding_index"] == 42
        assert models["shared"]["intelligence_index"] == 11
        assert models["shared"]["pricing"]["price_1m_blended_3_to_1"] == 3
        endpoint = payload["hosts_models"][0]
        assert endpoint["model_slug"] == "shared"
        assert endpoint["price_1m_blended_7_to_2_to_1"] == 4
        assert "model" not in endpoint
        assert (
            payload["meta"]["sources"]["official_api"]["unmatched_rsc_model_slugs"]
            == []
        )
        assert payload["meta"]["sources"]["rsc"]["unmatched_api_model_slugs"] == [
            "api-only"
        ]

    def test_official_model_envelope_validation_rejects_malformed_rows(self) -> None:
        with pytest.raises(ExtractionError, match="requires integer status"):
            normalize_official_models('{"status":"200","prompt_options":{},"data":[]}')
        with pytest.raises(ExtractionError, match="require non-empty slug"):
            normalize_official_models(
                '{"status":200,"prompt_options":{},"data":[{"slug":"","name":"x","model_creator":{},"evaluations":{},"pricing":{}}]}',
            )

    def test_unknown_source_fields_collisions_and_structured_identity(self) -> None:
        diagnostics: list[object] = []
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
        assert models[0]["raw_fields"]["newField"] == 1
        assert models[0]["raw_fields"]["new_field"] == 1
        assert models[0]["identity"]["model_slug"] == "model-a"
        assert models[0]["raw_metadata"]["source_path"] == "api.data.data[0]"
        assert any(
            getattr(item, "code", None) == "DUPLICATE_SOURCE_FIELD"
            for item in diagnostics
        )


if __name__ == "__main__":
    unittest.main()
