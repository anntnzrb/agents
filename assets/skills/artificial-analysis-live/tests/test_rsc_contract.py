from __future__ import annotations

import unittest

import _path  # noqa: F401
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


if __name__ == "__main__":
    unittest.main()
