"""Explicitly gated smoke tests for public provider endpoints."""

from __future__ import annotations

import os
import unittest

from game_deals.http import HttpClient
from game_deals.providers import (
    CheapSharkProvider,
    FrankfurterProvider,
    GGDealsProvider,
    SteamProvider,
)

LIVE = os.environ.get("GAME_DEALS_LIVE_TESTS") == "1"


@unittest.skipUnless(LIVE, "set GAME_DEALS_LIVE_TESTS=1 to call live providers")
class LiveProviderTests(unittest.TestCase):
    """Minimal network contract probes; never run in the deterministic suite."""

    def setUp(self) -> None:
        self.client = HttpClient(timeout=20, max_retries=0)

    def test_steam_search(self) -> None:
        response = SteamProvider(self.client).search("Half-Life 2", country="US")
        self.assertIsInstance(response.data, dict)
        self.assertTrue(response.data.get("items"))

    def test_cheapshark_stores(self) -> None:
        response = CheapSharkProvider(self.client).stores()
        self.assertIsInstance(response.data, list)
        self.assertTrue(response.data)

    def test_frankfurter_rate(self) -> None:
        response = FrankfurterProvider(self.client).rate("USD", "EUR")
        self.assertIsInstance(response.data, list)
        self.assertTrue(response.data)

    @unittest.skipUnless(os.environ.get("GG_DEALS_API_KEY"), "GG_DEALS_API_KEY is not set")
    def test_gg_prices(self) -> None:
        provider = GGDealsProvider(self.client, os.environ["GG_DEALS_API_KEY"])
        responses = list(
            provider.fetch(
                steam_type="app",
                ids=["220"],
                region="us",
                prices=True,
                bundles=False,
            ),
        )
        self.assertEqual(responses[0][0], "prices")
        self.assertIsInstance(responses[0][1].data, dict)


if __name__ == "__main__":
    unittest.main()
