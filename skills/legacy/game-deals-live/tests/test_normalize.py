"""Fixture-backed normalization, FX, acquisition, and ranking tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from game_deals.normalize import (
    apply_fx,
    classify_acquisition,
    extract_fx_rate,
    finalize_offers,
    normalize_cheapshark_game,
    normalize_gg_bundle_history,
    normalize_gg_prices,
    normalize_itad_prices,
    normalize_steam_app,
    rank_offers,
)

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> object:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class NormalizationTests(unittest.TestCase):
    def test_provider_fixtures_normalize_to_contract(self) -> None:
        steam = normalize_steam_app(
            fixture("steam_appdetails.json"),
            "220",
            observed_at="now",
        )
        cheap = normalize_cheapshark_game(
            fixture("cheapshark_game.json"),
            stores={"1": "Steam"},
            title="Half-Life 2",
            observed_at="now",
        )
        gg = normalize_gg_prices(fixture("gg_prices.json"), observed_at="now")
        itad = normalize_itad_prices(
            fixture("itad_prices.json"),
            title="Half-Life 2",
            observed_at="now",
        )
        self.assertEqual(steam[0]["evidence_status"], "estimated")
        self.assertEqual(steam[0]["acquisition_type"], "direct_ownership")
        self.assertEqual(cheap[0]["acquisition_type"], "direct_ownership")
        self.assertEqual(cheap[0]["drm"], ["Steam"])
        self.assertEqual(gg[0]["evidence_status"], "headline")
        self.assertEqual(itad[0]["acquisition_type"], "direct_ownership")
        self.assertEqual(itad[0]["coupon"], "SAVE10")
        finalize_offers(steam + cheap + gg + itad)
        for offer in steam + cheap + gg + itad:
            self.assertIn("seller", offer)
            self.assertIn("original_price", offer)
            self.assertIn("mandatory_fees", offer)
            self.assertIn("preselected_extras", offer)

    def test_gg_bundle_tiers_are_history_not_offers(self) -> None:
        history = normalize_gg_bundle_history(
            fixture("gg_bundles.json"),
            observed_at="now",
        )
        self.assertEqual(history[0]["tiers"][0]["games_count"], 2)
        self.assertEqual(
            history[0]["tiers"][0]["price"],
            {"amount": 5.0, "currency": "USD"},
        )
        self.assertNotIn("acquisition_type", history[0])

    def test_fx_conversion_uses_v2_rate_fixture(self) -> None:
        rate, as_of = extract_fx_rate(fixture("frankfurter_rates.json"), "USD", "EUR")
        offer = {"price": {"amount": 10.0, "currency": "USD"}}
        apply_fx(offer, target="EUR", rate=rate, as_of=as_of)
        self.assertEqual(offer["price"]["amount"], 8.5)
        self.assertEqual(offer["price"]["converted_from"]["currency"], "USD")

    def test_acquisition_classifies_gifts_accounts_and_subscriptions(self) -> None:
        self.assertEqual(classify_acquisition("Steam Gift"), "gift")
        self.assertEqual(classify_acquisition("shared account"), "account")
        self.assertEqual(
            classify_acquisition("Game Pass subscription"),
            "subscription_access",
        )

    def test_cheapest_price_cannot_be_reordered_by_risk(self) -> None:
        offers = [
            {
                "price": {"amount": 1.0, "currency": "USD"},
                "official": False,
                "acquisition_type": "account",
                "evidence_status": "unknown",
            },
            {
                "price": {"amount": 2.0, "currency": "USD"},
                "official": True,
                "acquisition_type": "direct_ownership",
                "evidence_status": "verified",
            },
        ]
        rankings = rank_offers(offers, top=5)
        self.assertEqual(rankings["overall"][0]["offer_index"], 0)
        self.assertEqual(rankings["absolute_cheapest"]["offer_index"], 0)
        self.assertEqual(rankings["cheapest_ownership"]["offer_index"], 1)
        self.assertEqual(rankings["cheapest_verified"]["offer_index"], 1)

    def test_incomparable_currency_and_bare_bundle_are_not_ownership_winners(self) -> None:
        offers = [
            {
                "price": {"amount": 1.0, "currency": "EUR"},
                "price_comparable": False,
                "acquisition_type": "direct_ownership",
                "evidence_status": "blocked",
            },
            {
                "price": {"amount": 2.0, "currency": "USD"},
                "acquisition_type": "bundle",
                "evidence_status": "estimated",
            },
            {
                "price": {"amount": 3.0, "currency": "USD"},
                "acquisition_type": "ownership_key",
                "evidence_status": "estimated",
            },
        ]
        rankings = rank_offers(offers, top=5)
        self.assertEqual(rankings["absolute_cheapest"]["offer_index"], 1)
        self.assertEqual(rankings["cheapest_ownership"]["offer_index"], 2)


if __name__ == "__main__":
    unittest.main()
