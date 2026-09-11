"""Tests for market-hunter (port of test/market-hunter.test.ts)."""

from __future__ import annotations

import json
import math
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, cast

import engine
import pytest
from adapters import (
    FunPayAdapter,
    G2aAdapter,
    KinguinAdapter,
    PlatiAdapter,
    Z2uAdapter,
    register_builtin_adapters,
)
from adapters.common import (
    detect_delivery_format,
    normalize_raw_items,
    parse_price,
    parse_rating,
    parse_sales,
)
from models import (
    AdapterError,
    EngineError,
    js_number_to_str,
    js_round,
    js_string,
    js_to_fixed2,
    js_to_locale_string,
)
from registry import (
    clear_registry,
    get_available_adapters,
    register_adapter,
    resolve_adapters,
    unregister_adapter,
)
from scoring import (
    compute_format_score,
    compute_price_sanity,
    compute_seller_score,
    compute_warranty_score,
    estimate_msrp,
    score_listing,
)

from scripts.cli import emit_human_report, emit_json
from scripts.cli import main as cli_main

if TYPE_CHECKING:
    from models import RawMarketListing, ScanResultData


@pytest.fixture(autouse=True)
def _registry_isolation():
    """Snapshot and restore the adapter registry around each test."""
    snapshot = get_available_adapters()
    yield
    clear_registry()
    for adapter in snapshot:
        register_adapter(adapter)


class TestDynamicRegistry:
    """Market Hunter - Dynamic Registry."""

    def test_registers_and_resolves_builtin_adapters(self):
        clear_registry()
        assert len(get_available_adapters()) == 0

        register_builtin_adapters()
        adapters = get_available_adapters()
        assert len(adapters) >= 5

        ids = [a.id for a in adapters]
        assert "g2a" in ids
        assert "kinguin" in ids
        assert "plati" in ids
        assert "z2u" in ids
        assert "funpay" in ids

    def test_filters_adapters_by_marketplace_name(self):
        register_builtin_adapters()
        filtered = resolve_adapters(["g2a", "plati"])
        assert len(filtered) == 2
        assert [a.id for a in filtered] == ["g2a", "plati"]

    def test_allows_dynamic_registration_and_unregistration(self):
        custom_adapter = G2aAdapter()
        register_adapter(custom_adapter)
        assert any(a.id == "g2a" for a in get_available_adapters())

        unregister_adapter("g2a")
        assert not any(a.id == "g2a" for a in get_available_adapters())


class TestScoringEngine:
    """Market Hunter - Scoring Engine."""

    def test_estimates_msrp_correctly_based_on_title_keywords(self):
        assert estimate_msrp("ChatGPT Plus 1 Month Account") == 20
        assert estimate_msrp("Claude Pro Dedicated Account") == 20
        assert estimate_msrp("Google Gemini Pro 6 Months Activation Link") == 120
        assert estimate_msrp("Perplexity Pro 1 Year Key") == 200
        assert estimate_msrp("GitHub Copilot 1 Year Student Pack") == 100

    def test_evaluates_price_sanity_curves(self):
        # $6 on a $20 service is in the sweet spot (30% ratio)
        assert compute_price_sanity(6, 20) == 100

        # $0.50 on a $20 service is a suspicious dump (2.5% ratio)
        assert compute_price_sanity(0.5, 20) == 20

        # $18 on a $20 service is low arbitrage (90% ratio)
        assert compute_price_sanity(18, 20) == 50

    def test_computes_bayesian_smoothed_seller_reliability(self):
        # Top seller with 10,000 sales and 99.8% rating
        top_score = compute_seller_score(99.8, 10000)
        assert top_score >= 90

        # Brand new seller with 1 review at 100%
        new_score = compute_seller_score(100, 1)
        assert new_score < 70

    def test_scores_delivery_formats_appropriately(self):
        assert compute_format_score("DEDICATED_ACCOUNT") == 95
        assert compute_format_score("PROMO_LINK_OR_CODE") == 85
        assert compute_format_score("SHARED_POOL") == 30
        assert compute_format_score("SESSION_COOKIE") == 0

    def test_scores_warranties_appropriately(self):
        assert compute_warranty_score(30) == 100
        assert compute_warranty_score(14) == 85
        assert compute_warranty_score(0) == 30

    def test_identifies_high_value_legitimate_deals_as_strong_buy(self):
        listing: RawMarketListing = {
            "id": "plati-12345",
            "marketplace": "plati",
            "title": "ChatGPT Plus Dedicated Personal Account",
            "url": "https://plati.market/itm/12345",
            "priceUsd": 8.5,
            "seller": {
                "name": "EliteSeller",
                "positiveFeedbackPercent": 99.5,
                "totalSalesCount": 15000,
            },
            "deliveryFormat": "DEDICATED_ACCOUNT",
            "isStockAvailable": True,
            "isAutoDelivery": True,
            "isGlobal": True,
            "warrantyDays": 30,
        }

        scored = score_listing(listing)
        assert scored["trustScore"] >= 85
        assert scored["trustTier"] == "STRONG_BUY"
        assert scored["isCircuitBreakerTripped"] is False
        assert scored["discountVsMsrpPercent"] >= 57

    def test_trips_circuit_breakers_on_session_cookie_injection(self):
        listing: RawMarketListing = {
            "id": "scam-1",
            "marketplace": "plati",
            "title": "ChatGPT Plus Cookie Session Token Injector",
            "url": "https://plati.market/itm/scam-1",
            "priceUsd": 1.0,
            "seller": {
                "name": "ShadyVendor",
                "positiveFeedbackPercent": 88.0,
                "totalSalesCount": 5,
            },
            "deliveryFormat": "SESSION_COOKIE",
            "isStockAvailable": True,
            "isAutoDelivery": True,
            "isGlobal": True,
        }

        scored = score_listing(listing)
        assert scored["isCircuitBreakerTripped"] is True
        assert scored["trustTier"] == "CONFIRMED_SCAM"
        assert scored["trustScore"] <= 5

    def test_penalizes_shared_multi_user_pool_accounts(self):
        listing: RawMarketListing = {
            "id": "shared-1",
            "marketplace": "z2u",
            "title": "ChatGPT Plus Shared Account 5 Devices Pool",
            "url": "https://z2u.com/shared-1",
            "priceUsd": 3.5,
            "seller": {
                "name": "PoolSeller",
                "positiveFeedbackPercent": 92.0,
                "totalSalesCount": 200,
            },
            "deliveryFormat": "SHARED_POOL",
            "isStockAvailable": True,
            "isAutoDelivery": True,
            "isGlobal": True,
        }

        scored = score_listing(listing)
        assert "Shared Multi-User Pool" in scored["detectedRedFlags"]
        assert scored["trustScore"] < 70


class TestPlatformAdapters:
    """Market Hunter - Platform Adapters."""

    def test_builds_correct_search_targets_for_each_marketplace(self):
        g2a = G2aAdapter()
        assert (
            "g2a.com/search?query=ChatGPT%20Plus"
            in g2a.build_search_target("ChatGPT Plus")["url"]
        )

        kinguin = KinguinAdapter()
        assert (
            "kinguin.net/listing?phrase=Gemini%20Pro"
            in kinguin.build_search_target("Gemini Pro")["url"]
        )

        plati = PlatiAdapter()
        assert (
            "plati.io/api/search.ashx?query=GitHub%20Copilot"
            in plati.build_search_target("GitHub Copilot")["url"]
        )

        z2u = Z2uAdapter()
        assert (
            "z2u.com/search?q=Claude%20Pro"
            in z2u.build_search_target("Claude Pro")["url"]
        )

        funpay = FunPayAdapter()
        assert (
            "funpay.com/en/lots/1355/"
            in funpay.build_search_target("ChatGPT Plus")["url"]
        )

    def test_parses_listings_from_mock_api_response(self):
        plati = PlatiAdapter()
        mock_api_response = {
            "items": [
                {
                    "id": 123456,
                    "name_eng": "ChatGPT Plus Dedicated Personal Account",
                    "price_usd": 8.99,
                    "rating": 99.5,
                    "sales_count": 5000,
                },
            ],
        }

        parsed = plati.parse_listings(mock_api_response)
        assert len(parsed) == 1
        item = parsed[0]
        assert item["id"] == "123456"
        assert item["priceUsd"] == 8.99
        assert item["marketplace"] == "plati"
        assert item["deliveryFormat"] == "DEDICATED_ACCOUNT"


class _FakeHttpResponse:
    def __init__(
        self, body: bytes, status: int = 200, content_type: str = "application/json"
    ):
        self.status = status
        self.headers = {"content-type": content_type}
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class TestEngine:
    """Market Hunter - engine fetch and scrape plumbing."""

    def test_js_number_to_str_matches_js_scalar_formatting(self):
        assert js_number_to_str(value=True) == "true"
        assert js_number_to_str(value=False) == "false"
        assert js_number_to_str(200.0) == "200"
        assert js_number_to_str(8.5) == "8.5"

    def test_request_timeout_resolution(self):
        assert engine._request_timeout({"query": "q"}) == 30.0
        assert engine._request_timeout({"query": "q", "timeoutSeconds": 5}) == 5.0
        assert engine._request_timeout({"query": "q", "timeoutSeconds": 0}) == 30.0
        assert (
            engine._request_timeout({"query": "q", "timeoutSeconds": cast("Any", "x")})
            == 30.0
        )

    def test_fetch_api_target_uses_request_timeout(self, monkeypatch):
        captured = {}

        def fake_urlopen(request, timeout=None):
            captured["timeout"] = timeout
            return _FakeHttpResponse(b'{"items": []}')

        monkeypatch.setattr(engine.urllib.request, "urlopen", fake_urlopen)
        result = engine._fetch_api_target(
            {"marketplace": "plati", "url": "https://plati.io/x", "format": "api"},
            7.5,
        )
        assert result == {"items": []}
        assert captured["timeout"] == 7.5

    def test_fetch_api_target_returns_none_on_error(self, monkeypatch):
        def fake_urlopen(request, timeout=None):
            raise OSError("connection refused")

        monkeypatch.setattr(engine.urllib.request, "urlopen", fake_urlopen)
        assert (
            engine._fetch_api_target(
                {"marketplace": "plati", "url": "https://plati.io/x", "format": "api"},
                5,
            )
            is None
        )

    def test_scrape_with_cli_prefers_installed_firecrawl(self, monkeypatch):
        calls = {}
        monkeypatch.setattr(
            engine.shutil,
            "which",
            lambda name: "/usr/bin/firecrawl" if name == "firecrawl" else None,
        )

        def fake_run(command, **kwargs):
            calls["command"] = command

            class _Proc:
                stdout = b"scraped text"

            return _Proc()

        monkeypatch.setattr(engine.subprocess, "run", fake_run)
        assert engine._scrape_with_cli("https://example.com", 5) == "scraped text"
        assert calls["command"][:2] == ["/usr/bin/firecrawl", "scrape"]

    def test_scrape_with_cli_falls_back_to_bun(self, monkeypatch):
        calls = {}
        monkeypatch.setattr(
            engine.shutil,
            "which",
            {"bun": "/usr/bin/bun"}.get,
        )

        def fake_run(command, **kwargs):
            calls["command"] = command

            class _Proc:
                stdout = b"scraped via bun"

            return _Proc()

        monkeypatch.setattr(engine.subprocess, "run", fake_run)
        assert engine._scrape_with_cli("https://example.com", 5) == "scraped via bun"
        assert calls["command"][:4] == [
            "/usr/bin/bun",
            "x",
            "firecrawl-cli@latest",
            "scrape",
        ]

    def test_scrape_with_cli_returns_none_without_binaries(self, monkeypatch):
        monkeypatch.setattr(engine.shutil, "which", lambda name: None)

        def fail_run(*args, **kwargs):
            raise AssertionError("subprocess must not run")

        monkeypatch.setattr(engine.subprocess, "run", fail_run)
        assert engine._scrape_with_cli("https://example.com", 5) is None

    def test_parse_failure_degrades_adapter_to_empty(self, monkeypatch):
        monkeypatch.setattr(
            engine.urllib.request,
            "urlopen",
            lambda request, timeout=None: _FakeHttpResponse(b'{"items": []}'),
        )

        class BrokenAdapter:
            id = "broken"
            display_name = "Broken"
            is_enabled_by_default = False

            def build_search_target(self, query):
                return {
                    "marketplace": "broken",
                    "url": "https://example.com",
                    "format": "api",
                }

            def parse_listings(self, raw):
                raise RuntimeError("unexpected adapter defect")

        assert (
            engine.fetch_adapter_listings(
                cast("Any", BrokenAdapter()), "q", timeout_seconds=5
            )
            == []
        )


class TestJsCompatHelpers:
    """Market Hunter - JavaScript semantics helpers."""

    def test_js_round_half_toward_positive_infinity(self):
        assert js_round(2.5) == 3
        assert js_round(-2.5) == -2
        assert js_round(-2.6) == -3

    def test_js_to_fixed2_half_up_and_edges(self):
        assert js_to_fixed2(8.0) == "8.00"
        assert js_to_fixed2(0.125) == "0.13"
        assert js_to_fixed2(-1.005) == "-1.00"
        assert js_to_fixed2(math.nan) == "NaN"
        assert js_to_fixed2(math.inf) == "Infinity"
        assert js_to_fixed2(-math.inf) == "-Infinity"

    def test_js_to_locale_string_grouping(self):
        assert js_to_locale_string(1234567) == "1,234,567"
        assert js_to_locale_string(1500.5) == "1,500.5"

    def test_js_string_matches_js_scalars(self):
        assert js_string(None) == "null"
        assert js_string(value=True) == "true"
        assert js_string(value=False) == "false"
        assert js_string(5.0) == "5"
        assert js_string("x") == "x"

    def test_error_classes_store_fields(self):
        adapter_err = AdapterError("g2a", "boom", cause=ValueError("x"))
        assert adapter_err.marketplace == "g2a"
        assert adapter_err.message == "boom"
        assert isinstance(adapter_err.cause, ValueError)

        engine_err = EngineError("code", "msg", {"k": 1})
        assert engine_err.code == "code"
        assert engine_err.details == {"k": 1}


class TestCommonHelpers:
    """Market Hunter - shared adapter normalization helpers."""

    def test_parse_price_variants(self):
        assert parse_price(12.5) == 12.5
        assert parse_price("$12.99") == 12.99
        assert parse_price("no digits") == 0
        assert parse_price(None) == 0
        assert parse_price(val=True) == 0

    def test_parse_rating_scales(self):
        assert parse_rating(4.5) == 90.0
        assert parse_rating(98) == 98
        assert parse_rating("4.2 stars") == pytest.approx(84.0)
        assert parse_rating("junk") == 95
        assert parse_rating(None) == 95

    def test_parse_sales_variants(self):
        assert parse_sales(123.9) == 123
        assert parse_sales("1,234 sold") == 1234
        assert parse_sales("none") == 100
        assert parse_sales(None) == 100

    def test_detect_delivery_format_categories(self):
        assert detect_delivery_format("cookie session") == "SESSION_COOKIE"
        assert detect_delivery_format("auth token login") == "SESSION_COOKIE"
        assert detect_delivery_format("shared account") == "SHARED_POOL"
        assert detect_delivery_format("family pool") == "SHARED_POOL"
        assert detect_delivery_format("student discount") == "STUDENT_PACK"
        assert detect_delivery_format("invite only") == "BUYER_EMAIL_UPGRADE"
        assert detect_delivery_format("upgrade your own") == "BUYER_EMAIL_UPGRADE"
        assert detect_delivery_format("redeem code") == "PROMO_LINK_OR_CODE"
        assert detect_delivery_format("license key") == "PROMO_LINK_OR_CODE"
        assert detect_delivery_format("personal account") == "DEDICATED_ACCOUNT"
        assert detect_delivery_format("completely opaque") == "UNKNOWN"
        assert detect_delivery_format("plain", "invite link") == "BUYER_EMAIL_UPGRADE"

    def test_normalize_raw_items_filters_and_defaults(self):
        items = [
            None,
            "junk",
            {"name": "No price"},
            {"title": "Free", "price": "0"},
            {"title": "ChatGPT Plus EU only", "price": "9.99"},
            {
                "title": "Copilot Year",
                "price": "19.99",
                "id": 7,
                "seller": "Top",
                "sellerRating": "4.8",
                "salesCount": "2000",
                "deliveryType": "invite",
            },
        ]
        normalized = normalize_raw_items(items, "plati", 30)
        assert len(normalized) == 2

        restricted = normalized[0]
        assert restricted["id"] == "plati-5"
        assert restricted["isGlobal"] is False
        assert restricted["url"].startswith("https://www.plati.com/search?query=")
        assert restricted["seller"]["name"] == "PLATI Verified Seller"
        assert restricted.get("warrantyDays") == 30

        copilot = normalized[1]
        assert copilot["id"] == "7"
        assert copilot["deliveryFormat"] == "BUYER_EMAIL_UPGRADE"
        assert copilot["seller"]["name"] == "Top"
        assert copilot["seller"].get("positiveFeedbackPercent") == 96.0
        assert copilot["seller"].get("totalSalesCount") == 2000
        assert copilot.get("description") == "Copilot Year"


class TestAdapterScrapeParsing:
    """Market Hunter - per-marketplace scrape/HTML parsers."""

    def test_g2a_markdown_dict_and_empty(self):
        g2a = G2aAdapter()
        md = (
            "[**ChatGPT Plus**](https://www.g2a.com/item-i123456)\n"
            "12.50 USD\n"
            "[**Copilot**\\n1 Year](https://www.g2a.com/thing-i7777)\n"
            "19.99 USD"
        )
        items = g2a.parse_listings(md)
        assert len(items) == 2
        assert items[0]["id"] == "123456"
        assert items[0]["priceUsd"] == 12.5
        assert items[0]["seller"]["positiveFeedbackPercent"] == 98
        assert items[0].get("warrantyDays") == 14

        from_dict = g2a.parse_listings({"products": [{"title": "X", "price": 5}]})
        assert from_dict[0]["marketplace"] == "g2a"
        assert g2a.parse_listings({"other": 1}) == []
        assert g2a.parse_listings("") == []
        assert g2a.parse_listings(42) == []

    def test_kinguin_markdown_dict_and_filters(self):
        kinguin = KinguinAdapter()
        md = (
            "[ChatGPT Plus 1 Month]"
            "(https://www.kinguin.net/category/777/chatgpt-plus)\n"
            "From 9.99 USD\n"
            "[logo](https://www.kinguin.net/category/1/logo)\n5.00 USD"
        )
        items = kinguin.parse_listings(md)
        assert len(items) == 1
        assert items[0]["id"] == "777"
        assert items[0]["priceUsd"] == 9.99
        assert items[0].get("warrantyDays") == 30
        assert kinguin.parse_listings({"items": [{"title": "T", "price": 3}]})
        assert kinguin.parse_listings(None) == []

    def test_z2u_markdown_and_dict(self):
        z2u = Z2uAdapter()
        md = "[ChatGPT Plus from$5.99](https://www.z2u.com/product-999/x)"
        items = z2u.parse_listings(md)
        assert len(items) == 1
        assert items[0]["id"] == "999"
        assert items[0]["priceUsd"] == 5.99
        assert z2u.parse_listings({"items": [{"title": "T", "price": 3}]})
        assert z2u.parse_listings([]) == []

    def test_funpay_html_relative_href_and_dict(self):
        funpay = FunPayAdapter()
        html = (
            '<a class="tc-item" href="https://funpay.com/en/lots/offer?id=42">'
            '<div class="tc-desc-text">ChatGPT Plus</div>'
            '<div class="media-user-name">Seller1</div>'
            '<div class="tc-price">$ 5.99</div></a>'
            '<a class="tc-item" href="/en/lots/offer?id=43">'
            '<div class="tc-desc-text">Gemini Pro</div>'
            '<div class="tc-price">$ 3.50</div></a>'
        )
        items = funpay.parse_listings(html)
        assert len(items) == 2
        assert items[0]["id"] == "42"
        assert items[0]["seller"]["name"] == "Seller1"
        assert items[1]["url"] == "https://funpay.com/en/lots/offer?id=43"
        assert items[1]["seller"]["name"] == "FunPay Verified Seller"
        assert funpay.parse_listings({"items": [{"title": "T", "price": 3}]})
        assert funpay.parse_listings("no funpay host here") == []

    def test_funpay_category_map_routing(self):
        funpay = FunPayAdapter()
        assert "1355" in funpay.build_search_target("ChatGPT Plus")["url"]
        assert "4187" in funpay.build_search_target("claude pro")["url"]
        assert "372" in funpay.build_search_target("spotify duo")["url"]
        assert "1355" in funpay.build_search_target("unknown thing")["url"]


class TestScoringEdges:
    """Market Hunter - scoring curve and breaker branches."""

    def test_estimate_msrp_curves(self):
        assert estimate_msrp("Perplexity Pro 1 year") == 200
        assert estimate_msrp("GitHub Copilot 12 month") == 100
        assert estimate_msrp("Adobe CC year") == 600
        assert estimate_msrp("Gemini Pro 6 month") == 120
        assert estimate_msrp("Gemini Pro 3 month") == 60
        assert estimate_msrp("Midjourney Basic") == 20
        assert estimate_msrp("Spotify Premium year") == 120
        assert estimate_msrp("YouTube Premium 12 month") == 140
        assert estimate_msrp("Discord Nitro") == 100
        assert estimate_msrp("unknown product") == 20

    def test_compute_price_sanity_bands(self):
        assert compute_price_sanity(0, 20) == 0
        assert compute_price_sanity(10, 0) == 0
        assert compute_price_sanity(0.5, 20) == 20
        assert compute_price_sanity(1.5, 20) == 50
        assert compute_price_sanity(5.0, 20) == 100
        assert compute_price_sanity(13.0, 20) == 80
        assert compute_price_sanity(17.0, 20) == 50
        assert compute_price_sanity(25.0, 20) == 30

    def test_compute_warranty_score_tiers(self):
        assert compute_warranty_score(None) == 30
        assert compute_warranty_score(30) == 100
        assert compute_warranty_score(14) == 85
        assert compute_warranty_score(7) == 70
        assert compute_warranty_score(1) == 50
        assert compute_warranty_score(0) == 30

    def test_score_listing_circuit_breakers(self):
        cookie_listing = _make_listing(title="ChatGPT cookie account", price=5.0)
        deal = score_listing(cookie_listing)
        assert deal["isCircuitBreakerTripped"] is True
        assert deal["trustTier"] == "CONFIRMED_SCAM"
        assert deal["trustScore"] == 5

        cheap_dedicated = _make_listing(
            title="ChatGPT Plus dedicated account", price=0.5, rating=99
        )
        deal2 = score_listing(cheap_dedicated)
        assert deal2["isCircuitBreakerTripped"] is True

        low_feedback = _make_listing(
            title="ChatGPT Plus dedicated account", price=10.0, rating=50
        )
        deal3 = score_listing(low_feedback)
        assert deal3["isCircuitBreakerTripped"] is True
        assert "seller feedback" in str(deal3.get("circuitBreakerReason", "")).lower()

    def test_score_listing_trust_tier_ladder(self):
        good = _make_listing(
            title="ChatGPT Plus dedicated personal account",
            price=12.0,
            rating=99.5,
            sales=50000,
            warranty=30,
        )
        deal = score_listing(good)
        assert deal["trustTier"] in {"STRONG_BUY", "ACCEPTABLE"}
        assert 0 <= deal["trustScore"] <= 100
        assert deal["discountVsMsrpPercent"] > 0


def _make_listing(
    title: str,
    price: float,
    rating: float = 98.0,
    sales: int = 5000,
    warranty: int = 14,
) -> RawMarketListing:
    return {
        "id": "x1",
        "marketplace": "plati",
        "title": title,
        "url": "https://plati.io/item/x1",
        "priceUsd": price,
        "seller": {
            "name": "S",
            "positiveFeedbackPercent": rating,
            "totalSalesCount": sales,
        },
        "deliveryFormat": detect_delivery_format(title),
        "isStockAvailable": True,
        "isAutoDelivery": True,
        "isGlobal": True,
        "warrantyDays": warranty,
        "description": title,
    }


class TestEngineIntegration:
    """Market Hunter - execute_scan pipeline integration tests."""

    def _plati_payload(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        return {"items": items}

    def _patch_fetchers(self, monkeypatch, api_payload=None, scrape_result=None):
        def fake_api(target, timeout_seconds):
            if target["marketplace"] == "plati":
                return api_payload
            return None

        monkeypatch.setattr(engine, "_fetch_api_target", fake_api)
        monkeypatch.setattr(
            engine, "_scrape_target", lambda target, key, timeout: scrape_result
        )

    def test_execute_scan_end_to_end_degraded_markets(self, monkeypatch):
        self._patch_fetchers(
            monkeypatch,
            api_payload=self._plati_payload(
                [
                    {
                        "id": 1,
                        "name_eng": "ChatGPT Plus Dedicated Personal Account",
                        "price_usd": 12.0,
                        "rating": 99.5,
                        "sales_count": 50000,
                    },
                ]
            ),
        )
        result = engine.execute_scan(
            {
                "query": "chatgpt",
                "typeFilter": "all",
                "minScore": 50,
                "jsonOnly": False,
                "full": False,
            }
        )
        assert result["total_scanned"] == 1
        assert set(result["degraded_markets"]) == {"g2a", "kinguin", "z2u", "funpay"}
        assert result["markets_queried"] == [
            "g2a",
            "kinguin",
            "plati",
            "z2u",
            "funpay",
        ]
        assert result.get("is_degraded_mode") is True
        assert "FIRECRAWL_API_KEY" in result.get("warning", "")
        assert result["valid_deals_count"] <= 1

    def test_execute_scan_filters_and_full_flag(self, monkeypatch):
        self._patch_fetchers(
            monkeypatch,
            api_payload=self._plati_payload(
                [
                    {
                        "id": 1,
                        "name_eng": "ChatGPT Plus Dedicated Personal Account",
                        "price_usd": 12.0,
                        "rating": 99.5,
                        "sales_count": 50000,
                    },
                    {
                        "id": 2,
                        "name_eng": "ChatGPT cookie token",
                        "price_usd": 0.5,
                        "rating": 10,
                        "sales_count": 1,
                    },
                ]
            ),
        )
        base = {
            "query": "chatgpt",
            "typeFilter": "all",
            "minScore": 50,
            "jsonOnly": False,
        }
        result = engine.execute_scan(cast("Any", {**base, "full": False}))
        assert result["total_scanned"] == 2
        assert result["filtered_scams_count"] == 1
        assert len(result["top_deals"]) == 1

        full_result = engine.execute_scan(cast("Any", {**base, "full": True}))
        assert len(full_result["top_deals"]) == 2
        assert full_result["filtered_scams_count"] == 1

    def test_execute_scan_budget_type_and_market_filters(self, monkeypatch):
        self._patch_fetchers(
            monkeypatch,
            api_payload=self._plati_payload(
                [
                    {
                        "id": 1,
                        "name_eng": "ChatGPT Plus Dedicated Personal Account",
                        "price_usd": 12.0,
                        "rating": 99.5,
                        "sales_count": 50000,
                    },
                ]
            ),
        )
        base = {
            "query": "chatgpt",
            "typeFilter": "all",
            "minScore": 50,
            "jsonOnly": False,
            "full": False,
        }
        budget_result = engine.execute_scan(cast("Any", {**base, "budget": 5.0}))
        assert budget_result["valid_deals_count"] == 0
        assert budget_result["budget"] == 5.0

        type_result = engine.execute_scan(cast("Any", {**base, "typeFilter": "link"}))
        assert type_result["valid_deals_count"] == 0

        market_result = engine.execute_scan(cast("Any", {**base, "markets": ["plati"]}))
        assert market_result["markets_queried"] == ["plati"]
        assert market_result["degraded_markets"] == []

    def test_execute_scan_sorted_by_trust_descending(self, monkeypatch):
        self._patch_fetchers(
            monkeypatch,
            api_payload=self._plati_payload(
                [
                    {
                        "id": 1,
                        "name_eng": "ChatGPT Plus Dedicated Account",
                        "price_usd": 8.0,
                        "rating": 60.0,
                        "sales_count": 10,
                    },
                    {
                        "id": 2,
                        "name_eng": "ChatGPT Plus Dedicated Personal Account",
                        "price_usd": 10.0,
                        "rating": 99.9,
                        "sales_count": 90000,
                    },
                ]
            ),
        )
        result = engine.execute_scan(
            {
                "query": "chatgpt",
                "typeFilter": "all",
                "minScore": 0,
                "jsonOnly": False,
                "full": False,
            }
        )
        scores = [d["trustScore"] for d in result["top_deals"]]
        assert scores == sorted(scores, reverse=True)

    def test_scrape_target_keyless_cli_and_sdk_paths(self, monkeypatch):
        class _FakeDoc:
            json: ClassVar[dict] = {"items": []}

        class _FakeApp:
            def __init__(self, **kwargs):
                captured["init"] = kwargs

            def scrape(self, url, **kwargs):
                captured["scrape"] = kwargs
                return _FakeDoc()

        captured: dict[str, Any] = {}
        monkeypatch.setattr(engine, "Firecrawl", _FakeApp)
        target = {
            "marketplace": "g2a",
            "url": "https://www.g2a.com/search?query=x",
            "format": "json",
            "waitForMs": 1234,
        }
        result = engine._scrape_with_sdk(cast("Any", target), "key123", 7.5)
        assert result == {"items": []}
        assert captured["init"]["api_key"] == "key123"
        assert captured["init"]["timeout"] == 7.5
        assert captured["scrape"]["wait_for"] == 1234

        # SDK returning nothing falls through to the CLI fallback
        monkeypatch.setattr(
            engine, "_scrape_with_sdk", lambda target, key, timeout: None
        )
        monkeypatch.setattr(engine, "_scrape_with_cli", lambda url, timeout: "cli text")
        assert engine._scrape_target(cast("Any", target), "key123", 5) == "cli text"


class TestCli:
    """Market Hunter - CLI emission and main() coverage."""

    def _result_data(self, **overrides) -> ScanResultData:
        data: ScanResultData = {
            "query": "chatgpt",
            "budget": None,
            "total_scanned": 1,
            "valid_deals_count": 1,
            "filtered_scams_count": 0,
            "top_deals": [
                {
                    "id": "1",
                    "marketplace": "plati",
                    "title": "ChatGPT Plus Dedicated Account",
                    "url": "https://plati.io/item/1",
                    "priceUsd": 12.0,
                    "seller": {
                        "name": "TopSeller",
                        "positiveFeedbackPercent": 99.5,
                        "totalSalesCount": 50000,
                    },
                    "deliveryFormat": "DEDICATED_ACCOUNT",
                    "isStockAvailable": True,
                    "isAutoDelivery": True,
                    "isGlobal": True,
                    "warrantyDays": 30,
                    "description": "ChatGPT Plus Dedicated Account",
                    "trustScore": 90,
                    "trustTier": "STRONG_BUY",
                    "priceSanityScore": 100,
                    "sellerScore": 90,
                    "formatScore": 95,
                    "warrantyScore": 100,
                    "penaltyDeductions": 0,
                    "detectedRedFlags": ["warning flag"],
                    "isCircuitBreakerTripped": False,
                    "discountVsMsrpPercent": 40,
                    "recommendationSummary": "STRONG_BUY: ok",
                }
            ],
            "markets_queried": ["plati"],
            "degraded_markets": [],
        }
        data.update(cast("Any", overrides))
        return data

    def test_emit_json_envelope(self, capsys):
        emit_json(self._result_data())
        envelope = json.loads(capsys.readouterr().out)
        assert envelope["ok"] is True
        assert envelope["schema_version"] == 1
        assert envelope["command"] == "scan"
        assert envelope["data"]["top_deals"][0]["marketplace"] == "plati"

    def test_emit_json_sanitizes_non_finite(self, capsys):
        data = self._result_data()
        data["top_deals"][0]["trustScore"] = cast("Any", math.nan)
        emit_json(data)
        envelope = json.loads(capsys.readouterr().out)
        assert envelope["data"]["top_deals"][0]["trustScore"] is None

    def test_emit_human_report_full(self, capsys):
        data = self._result_data(
            budget=15.0,
            filtered_scams_count=3,
            warning="test warning",
        )
        emit_human_report(data)
        out = capsys.readouterr().out
        assert "MARKET HUNTER: CHATGPT" in out
        assert "Budget Constraint: <= $15.00 USD" in out
        assert "test warning" in out
        assert "TOP VERIFIED RECOMMENDATION" in out
        assert "50,000 sales" in out
        assert "30 days replacement guarantee" in out
        assert "warning flag" in out
        assert "Filtered Out: 3" in out

    def test_emit_human_report_empty(self, capsys):
        data = self._result_data(
            top_deals=[],
            valid_deals_count=0,
            filtered_scams_count=2,
        )
        emit_human_report(data)
        out = capsys.readouterr().out
        assert "No verified deals found" in out
        assert "Filtered out 2" in out

    def test_main_json_mode(self, monkeypatch, capsys):
        captured: dict[str, Any] = {}

        def fake_scan(options):
            captured.update(options)
            return self._result_data()

        monkeypatch.setattr("scripts.cli.execute_scan", fake_scan)
        rc = cli_main(
            [
                "chatgpt",
                "plus",
                "--json",
                "--budget",
                "15",
                "--type",
                "account",
                "--min-score",
                "60",
                "--markets",
                "g2a, plati",
                "--full",
            ]
        )
        assert rc == 0
        envelope = json.loads(capsys.readouterr().out)
        assert envelope["ok"] is True
        assert captured["query"] == "chatgpt plus"
        assert captured["budget"] == 15.0
        assert captured["typeFilter"] == "account"
        assert captured["minScore"] == 60
        assert captured["markets"] == ["g2a", "plati"]
        assert captured["full"] is True

    def test_main_human_mode(self, monkeypatch, capsys):
        monkeypatch.setattr(
            "scripts.cli.execute_scan", lambda options: self._result_data()
        )
        rc = cli_main(["chatgpt"])
        assert rc == 0
        assert "MARKET HUNTER" in capsys.readouterr().out

    def test_main_usage_error_and_version(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            cli_main([])
        assert exc_info.value.code == 2
        capsys.readouterr()

        with pytest.raises(SystemExit) as exc_info:
            cli_main(["--version"])
        assert exc_info.value.code == 0
        assert "1.0.0" in capsys.readouterr().out


class TestEndToEndSubprocess:
    """Market Hunter - real subprocess entrypoint coverage."""

    def test_cli_subprocess_emits_valid_envelope(self):
        cli_path = Path(__file__).resolve().parents[1] / "scripts" / "cli.py"
        proc = subprocess.run(
            [
                sys.executable,
                str(cli_path),
                "nonexistent-thing-xyz",
                "--json",
                "--markets",
                "plati",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=90,
        )
        assert proc.returncode == 0
        envelope = json.loads(proc.stdout)
        assert envelope["ok"] is True
        assert envelope["command"] == "scan"
        assert envelope["data"]["markets_queried"] == ["plati"]

    def test_cli_subprocess_usage_error(self):
        cli_path = Path(__file__).resolve().parents[1] / "scripts" / "cli.py"
        proc = subprocess.run(
            [sys.executable, str(cli_path)],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        assert proc.returncode == 2


class TestRemainingEdges:
    """Targeted coverage for residual uncovered branches."""

    def test_api_target_non_2xx_and_text_body(self, monkeypatch):
        class Resp404:
            status = 404
            headers: ClassVar[dict[str, str]] = {}

            def read(self):
                return b"not found"

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        class RespText:
            status = 200
            headers: ClassVar[dict[str, str]] = {"content-type": "text/plain"}

            def read(self):
                return b"plain body"

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        monkeypatch.setattr(
            urllib.request,
            "urlopen",
            lambda req, timeout=None: Resp404(),
        )
        assert (
            engine._fetch_api_target(
                {"marketplace": "plati", "url": "https://x", "format": "api"}, 5
            )
            is None
        )

        monkeypatch.setattr(
            urllib.request,
            "urlopen",
            lambda req, timeout=None: RespText(),
        )
        assert (
            engine._fetch_api_target(
                {"marketplace": "plati", "url": "https://x", "format": "api"}, 5
            )
            == "plain body"
        )

    def test_scrape_with_sdk_exception_and_falsy_json(self, monkeypatch):
        class RaiseApp:
            def __init__(self, **kwargs):
                pass

            def scrape(self, url, **kwargs):
                raise RuntimeError("sdk blew up")

        class EmptyDocApp:
            def __init__(self, **kwargs):
                pass

            def scrape(self, url, **kwargs):
                class Doc:
                    json = None

                return Doc()

        target = {"marketplace": "g2a", "url": "https://x", "format": "json"}
        monkeypatch.setattr(engine, "Firecrawl", RaiseApp)
        assert engine._scrape_with_sdk(cast("Any", target), "k", 5) is None
        monkeypatch.setattr(engine, "Firecrawl", EmptyDocApp)
        assert engine._scrape_with_sdk(cast("Any", target), "k", 5) is None

    def test_scrape_with_cli_timeout_and_empty(self, monkeypatch):

        def raise_timeout(*a, **k):
            raise subprocess.TimeoutExpired("cmd", 5)

        monkeypatch.setattr(engine.subprocess, "run", raise_timeout)
        assert engine._scrape_with_cli("https://x", 5) is None

        class EmptyProc:
            stdout = b"   "

        monkeypatch.setattr(engine.subprocess, "run", lambda *a, **k: EmptyProc())
        monkeypatch.setattr(
            engine, "_cli_scrape_command", lambda url: ["firecrawl", "x"]
        )
        assert engine._scrape_with_cli("https://x", 5) is None

    def test_scrape_target_outer_exception_guard(self, monkeypatch):
        monkeypatch.setattr(
            engine,
            "_scrape_with_cli",
            lambda url, timeout: (_ for _ in ()).throw(RuntimeError("x")),
        )
        monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
        target = {"marketplace": "g2a", "url": "https://x", "format": "json"}
        assert engine._scrape_target(cast("Any", target), None, 5) is None

    def test_js_number_to_str_infinity(self):
        assert js_number_to_str(math.inf) == "Infinity"
        assert js_number_to_str(-math.inf) == "-Infinity"
        assert js_number_to_str(3.5) == "3.5"

    def test_unregister_missing_returns_false(self):
        assert unregister_adapter("nonexistent-adapter") is False

    def test_score_listing_low_tiers(self):
        risky = _make_listing(
            title="unknown product",
            price=19.9,
            rating=78,
            sales=5,
            warranty=0,
        )
        assert score_listing(risky)["trustTier"] == "RISKY_BUDGET"

        danger = _make_listing(
            title="unknown product",
            price=21.0,
            rating=78,
            sales=0,
            warranty=0,
        )
        assert score_listing(danger)["trustTier"] == "AVOID_DANGER"

        shared = _make_listing(
            title="ChatGPT Plus shared account",
            price=19.0,
            rating=95,
            sales=1000,
            warranty=30,
        )
        shared_deal = score_listing(shared)
        assert shared_deal["trustTier"] == "CONFIRMED_SCAM"
        assert shared_deal["isCircuitBreakerTripped"] is False


class TestFinalEdges:
    """Last-mile coverage."""

    def test_scrape_target_sdk_truthy_early_return(self, monkeypatch):
        monkeypatch.setattr(
            engine, "_scrape_with_sdk", lambda target, key, timeout: {"ok": 1}
        )
        monkeypatch.setattr(
            engine,
            "_scrape_with_cli",
            lambda url, timeout: (_ for _ in ()).throw(
                AssertionError("CLI should not be reached")
            ),
        )
        target = {"marketplace": "g2a", "url": "https://x", "format": "json"}
        assert engine._scrape_target(cast("Any", target), "key", 5) == {"ok": 1}

    def test_fetch_adapter_listings_scrape_success(self, monkeypatch):
        monkeypatch.setattr(
            engine,
            "_scrape_target",
            lambda target, key, timeout: (
                "[**ChatGPT Plus**](https://www.g2a.com/item-i123456)\n12.50 USD"
            ),
        )
        listings = engine.fetch_adapter_listings(
            G2aAdapter(), "chatgpt", timeout_seconds=5
        )
        assert len(listings) == 1
        assert listings[0]["marketplace"] == "g2a"

    def test_adapter_non_dict_fallthroughs(self):
        plati = PlatiAdapter()
        assert plati.parse_listings(None) == []
        assert plati.parse_listings("text") == []
        assert plati.parse_listings({"items": "not-a-list"}) == []
        kinguin = KinguinAdapter()
        assert kinguin.parse_listings({"other": 1}) == []
        z2u = Z2uAdapter()
        assert z2u.parse_listings({"other": 1}) == []
        assert z2u.parse_listings(None) == []
        funpay = FunPayAdapter()
        assert funpay.parse_listings(None) == []
        assert funpay.parse_listings({"other": 1}) == []
        # HTML offer missing desc block -> skipped
        html = (
            '<a class="tc-item" href="https://funpay.com/en/lots/offer?id=9">'
            '<div class="tc-price">$ 5.00</div></a>'
        )
        assert funpay.parse_listings(html) == []
