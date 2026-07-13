from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import _path  # noqa: F401
from artificial_analysis import cli
from artificial_analysis.rsc import extract_lists, snapshot_slugs


class TestRscExtraction(unittest.TestCase):
    def test_extract_lists_uses_alias_keys(self) -> None:
        frames = [
            (
                "x",
                {
                    "model_rows": [
                        {"slug": "m1", "name": "M1", "model_creator_id": "c1"}
                    ],
                    "providers": [
                        {"slug": "p1", "name": "Provider 1", "website_url": "https://x"}
                    ],
                    "host_models": [
                        {"slug": "p1_model-1", "host_id": "h1", "model_id": "m1"},
                        {"slug": "p1_model-2", "host_id": "h1", "model_id": "m2"},
                    ],
                },
            )
        ]

        models, hosts, hosts_models = extract_lists(frames)

        self.assertEqual(len(models), 1)
        self.assertEqual(len(hosts), 1)
        self.assertEqual(len(hosts_models), 2)

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
            )
        ]

        models, hosts, hosts_models = extract_lists(frames)

        self.assertEqual(len(models), 2)
        self.assertEqual(len(hosts), 2)
        self.assertEqual(len(hosts_models), 2)

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
            )
        ]

        models, hosts, hosts_models = extract_lists(frames)

        self.assertEqual(len(models), 2)
        self.assertEqual(len(hosts), 2)
        self.assertEqual(len(hosts_models), 2)

        first = hosts_models[0]
        self.assertEqual(first["slug"], "provider-one_model-a")
        self.assertEqual(first["name"], "Provider One / Model A")
        self.assertEqual(first["host_api_id"], "provider-one-api")
        self.assertEqual(first["model"]["model_creator_id"], "creator-a")
        self.assertEqual(first["host"]["website_url"], "https://provider-one.example")
        self.assertEqual(first["context_window_tokens"], 128000)
        self.assertIs(first["supports_function_calling"], True)
        self.assertEqual(first["price_1m_input_tokens"], 0.25)
        self.assertEqual(first["price_1m_output_tokens"], 1.25)
        self.assertEqual(first["price_1m_blended_3_to_1"], 0.50)
        self.assertEqual(first["timescaleData"]["median_output_speed"], 82.4)
        self.assertEqual(first["timescaleData"]["median_time_to_first_chunk"], 0.37)
        self.assertEqual(
            first["end_to_end_response_time_metrics"]["total_time"],
            2.8,
        )

        self.assertEqual(hosts_models[1]["slug"], "provider-two_model-b")
        self.assertEqual(hosts_models[1]["model"]["model_creator_id"], "creator-b")

    def test_snapshot_slugs_accepts_aliases(self) -> None:
        snapshot = {
            "endpoints": [
                {"slug": "provider-1_model-1", "host_id": "h1", "model_id": "m1"},
                {"slug": "provider-1_model-2", "host_id": "h1", "model_id": "m2"},
            ]
        }
        slugs = snapshot_slugs(snapshot)
        self.assertEqual(slugs, ["provider-1_model-1", "provider-1_model-2"])

    def _coding_payload(
        self, frames: list[tuple[str, object]], **options: object
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
            "modelCreator": {"name": creator, "slug": creator.lower().replace(" ", "-")},
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
                }
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
                    ]
                },
            )
        ]

        payload = self._coding_payload(frames)

        self.assertEqual(payload["counts"]["matched_models"], 2)
        row = payload["rows"][0]
        self.assertEqual(row["model_slug"], "legacy-alpha")
        self.assertEqual(row["coding"], 81.2)
        self.assertEqual(row["coding_token_counts"]["input_tokens"], 500)
        self.assertEqual(row["coding_token_counts"]["output_tokens"], 300)
        self.assertEqual(row["coding_eval_cost"]["total_cost"], 1.25)
        self.assertEqual(row["coding_eval_cost"]["answer_cost"], 0.50)

    def test_coding_payload_normalizes_current_models_task_metrics(self) -> None:
        frames = [
            (
                "current",
                {
                    "models": [
                        self._current_row("current-alpha", 88.4, "OpenAI"),
                        self._current_row("current-beta", 79.1, "OpenAI"),
                    ]
                },
            )
        ]

        payload = self._coding_payload(frames)

        self.assertEqual(payload["counts"]["matched_models"], 2)
        row = payload["rows"][0]
        self.assertEqual(row["model_slug"], "current-alpha")
        self.assertEqual(row["short_name"], "Current Alpha")
        self.assertEqual(row["creator"], "OpenAI")
        self.assertEqual(row["coding"], 88.4)
        self.assertEqual(row["is_reasoning"], True)
        self.assertEqual(row["release_date"], "2026-07-01")
        self.assertEqual(
            row["coding_task_metrics"]["output_tokens_per_task"],
            {"output_tokens": 300, "answer_tokens": 200, "reasoning_tokens": 100},
        )
        self.assertEqual(
            row["coding_task_metrics"]["cost_per_task_usd"],
            {
                "total_cost": 1.25,
                "input_cost": 0.10,
                "non_cache_input_cost": 0.08,
                "cache_read_cost": 0.01,
                "cache_write_cost": 0.01,
                "output_cost": 0.75,
                "reasoning_cost": 0.25,
                "answer_cost": 0.50,
            },
        )
        self.assertEqual(
            row["coding_task_metrics"]["time_per_task_seconds"], 12.5
        )

    def test_coding_payload_retains_current_score_without_task_metrics(self) -> None:
        frames = [
            (
                "current",
                {
                    "models": [
                        self._current_row(
                            "score-only", 77.7, "OpenAI", with_metrics=False
                        ),
                        self._current_row(
                            "score-only-peer", 70.0, "OpenAI", with_metrics=False
                        ),
                    ]
                },
            )
        ]

        payload = self._coding_payload(frames)
        self.assertEqual(payload["counts"]["matched_models"], 2)

        row = payload["rows"][0]
        self.assertEqual(row["model_slug"], "score-only")
        self.assertEqual(row["coding"], 77.7)
        metrics = row["coding_task_metrics"]
        self.assertEqual(
            metrics["output_tokens_per_task"],
            {
                "output_tokens": None,
                "answer_tokens": None,
                "reasoning_tokens": None,
            },
        )
        self.assertEqual(
            metrics["cost_per_task_usd"],
            {
                "total_cost": None,
                "input_cost": None,
                "non_cache_input_cost": None,
                "cache_read_cost": None,
                "cache_write_cost": None,
                "output_cost": None,
                "reasoning_cost": None,
                "answer_cost": None,
            },
        )
        self.assertIsNone(metrics["time_per_task_seconds"])

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
                    ]
                },
            )
        ]

        with self.assertRaises(cli.ExtractionError):
            self._coding_payload(frames)

    def test_coding_payload_filters_and_sorts_current_rows_deterministically(self) -> None:
        frames = [
            (
                "current",
                {
                    "models": [
                        self._current_row("lab-alpha", 75.0, "Target Lab"),
                        self._current_row("lab-beta", 91.0, "Target Lab"),
                        self._current_row("other", 99.0, "Other Lab"),
                    ]
                },
            )
        ]

        payload = self._coding_payload(
            frames,
            creator="target lab",
            sort_by="coding",
            order="desc",
            limit=10,
        )

        self.assertEqual(
            [row["model_slug"] for row in payload["rows"]],
            ["lab-beta", "lab-alpha"],
        )


if __name__ == "__main__":
    unittest.main()
