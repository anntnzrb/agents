"""Schema and LLM projection tests."""

from __future__ import annotations

import unittest

from game_deals.schema import (
    ACQUISITION_TYPES,
    EVIDENCE_STATUSES,
    OUTPUT_SCHEMA,
    llm_projection,
)


class SchemaTests(unittest.TestCase):
    def test_contract_enums_and_rankings_exist(self) -> None:
        self.assertIn("gift", ACQUISITION_TYPES)
        self.assertIn("direct_ownership", ACQUISITION_TYPES)
        self.assertEqual(
            EVIDENCE_STATUSES,
            ["verified", "estimated", "headline", "blocked", "unknown"],
        )
        required = OUTPUT_SCHEMA["properties"]["rankings"]["required"]
        self.assertIn("absolute_cheapest", required)
        self.assertIn("cheapest_ownership", required)
        self.assertIn("cheapest_verified", required)

    def test_llm_projection_removes_only_raw_snapshot_data(self) -> None:
        payload = {
            "provider_snapshots": [
                {"provider": "x", "data": {"large": True}, "status": "ok"},
            ],
            "offers": [{"evidence": [{"source": "x"}]}],
        }
        projected = llm_projection(payload)
        self.assertNotIn("data", projected["provider_snapshots"][0])
        self.assertEqual(projected["offers"][0]["evidence"][0]["source"], "x")
        self.assertIn("data", payload["provider_snapshots"][0])


if __name__ == "__main__":
    unittest.main()
