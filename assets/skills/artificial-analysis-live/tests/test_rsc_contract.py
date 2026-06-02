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
