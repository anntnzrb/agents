# ruff: noqa: PLR2004 - assertions use literal captured values.
"""Real captured cards and pure query, filtering, and ranking behavior."""

from dataclasses import replace
from pathlib import Path
from typing import cast
from urllib.parse import parse_qs, urlparse

import pytest
from ebay_live.detail_parser import parse_item_detail
from ebay_live.filters import Filters, filter_results
from ebay_live.models import EbayBlockedError, Listing, SearchQuery
from ebay_live.parser import parse_search_results
from ebay_live.query import build_search_url
from ebay_live.score import rank_results
from hypothesis import given
from hypothesis import strategies as st

FIXTURES = Path(__file__).parent / "fixtures"


def test_captured_cards() -> None:
    """Observe IDs, auction, delivery, feedback, and unknown sponsorship."""
    results = parse_search_results(
        (FIXTURES / "search.html").read_text(encoding="utf-8")
    )
    first, second, accessory = results[:3]
    assert len(results) == 12
    assert first.item_id == "178557756440"
    assert first.url == "https://www.ebay.com/itm/178557756440"
    assert first.price == 16
    assert first.shipping_cost == 10.25
    assert first.total_cost == 26.25
    assert first.condition == "Parts Only"
    assert first.buying_format == ("auction",)
    assert first.bid_count == 8
    assert first.time_left == "2d 19h left"
    assert first.seller_name == "crislomcam"
    assert first.seller_feedback_pct == 100
    assert first.seller_feedback_count == 132
    assert first.sponsored is None
    assert second.seller_feedback_count == 6500
    assert accessory.shipping_cost == 0
    assert accessory.buying_format == ("buy_it_now",)
    assert results[4].buying_format == ("best_offer",)


def test_range_and_unknown_shipping() -> None:
    """A price range is not a single guaranteed purchase amount."""
    html = """
        <ul class="srp-results"><li class="s-card">
        <a class="s-card__link" href="/itm/987654321012"></a>
        <div class="s-card__title">Camera</div>
        <span class="s-card__price">$90.00 to $120.00</span></li></ul>
    """
    result = parse_search_results(html)[0]
    assert (
        result.price,
        result.price_max,
        result.shipping_cost,
        result.total_cost,
    ) == (90, 120, None, None)
    assert result.sponsored is None
    with pytest.raises(EbayBlockedError):
        _ = parse_search_results("<html>Loading</html>")
    assert parse_search_results("<h1>No exact matches found</h1>") == []


def test_detail_capture() -> None:
    """Read the captured Product offer, identity, shipping, and returns."""
    result = parse_item_detail((FIXTURES / "item.html").read_text(encoding="utf-8"))
    assert result.title == "Sony WH-1000XM5 Wireless Noise Canceling Headphones - Black"
    assert result.condition == "Used"
    assert result.price == 34
    assert result.brand == "Sony"
    assert result.model == "Sony WH-1000XM5"
    assert result.gtin == "0027242923232"
    assert result.mpn == "WH-1000XM5"
    assert result.availability == "https://schema.org/InStock"
    assert result.shipping_cost == 10.15
    assert result.item_specifics["Brand"] == "Sony"
    assert result.returns is not None
    assert "returns" in result.returns.casefold()


def test_query_map() -> None:
    """Readable options reach eBay's actual URL keys."""
    query = SearchQuery(
        " sony & headphones ",
        sort="price-lowest",
        min_price=10,
        max_price=200,
        condition="used",
        buy_it_now=True,
        page=2,
        per_page=120,
        zip_code="33101",
    )
    params = parse_qs(urlparse(build_search_url(query)).query)
    assert params == {
        "_nkw": ["sony & headphones"],
        "_sop": ["15"],
        "_udlo": ["10"],
        "_udhi": ["200"],
        "LH_ItemCondition": ["3000"],
        "LH_BIN": ["1"],
        "_pgn": ["2"],
        "_ipg": ["120"],
        "_stpos": ["33101"],
    }
    assert parse_qs(
        urlparse(
            build_search_url(SearchQuery("watch", auction=True, sort="ending-soonest"))
        ).query
    )["LH_Auction"] == ["1"]


@given(st.text(min_size=1).filter(lambda value: bool(value.strip())))
def test_query_round_trip(keywords: str) -> None:
    """URL encoding preserves arbitrary non-empty user keywords."""
    params = parse_qs(urlparse(build_search_url(SearchQuery(keywords))).query)
    assert params["_nkw"] == [keywords.strip()]


def test_filters_and_value_ranking() -> None:
    """Prefer comparable value and reject noisy titles using local predicates."""
    good = Listing(
        "1",
        "Sony headphones",
        "https://www.ebay.com/itm/1",
        price=100,
        currency="USD",
        shipping_cost=0,
        condition="Brand New",
        seller_feedback_pct=100,
        seller_feedback_count=1000,
    )
    expensive = replace(good, item_id="2", price=200)
    accessory = replace(
        good, item_id="3", title="Sony headphones replacement case", price=20
    )
    unknown = replace(good, item_id="4", shipping_cost=None, seller_feedback_pct=None)
    rows = [good, expensive, accessory, unknown]
    selected = filter_results(
        rows,
        Filters(
            include=("sony",),
            exclude=("case",),
            title_contains="headphones",
            min_seller_feedback=99,
            free_shipping=True,
        ),
    )
    assert [r.item_id for r in selected] == ["1", "2"]
    ranked = rank_results([good, expensive], "Sony headphones", buy_now=False)
    assert [r["item_id"] for r in ranked] == ["1", "2"]
    assert cast("float", ranked[0]["score"]) > cast("float", ranked[1]["score"])
    noisy = rank_results([accessory, unknown], "Sony headphones", buy_now=False)
    assert "possible accessory; refine include or exclude terms" in cast(
        "list[str]", next(r for r in noisy if r["item_id"] == "3")["reasons"]
    )
    assert "unknown total cost; no price credit" in cast(
        "list[str]", next(r for r in noisy if r["item_id"] == "4")["reasons"]
    )


@pytest.mark.parametrize(
    ("url", "status", "fixture"),
    [
        ("https://www.ebay.com/sch/i.html", 403, "akamai.html"),
        ("https://www.ebay.com/sch/i.html", 429, "search.html"),
        ("https://www.ebay.com/sch/i.html", 503, "search.html"),
        ("https://www.ebay.com/splashui/challenge", 200, "search.html"),
        ("https://www.ebay.com/splashui/captcha", 200, "search.html"),
        ("https://signin.ebay.com/", 200, "search.html"),
        ("https://www.ebay.com/sch/i.html", 200, "challenge.html"),
    ],
)
def test_block_detection(url: str, status: int, fixture: str) -> None:
    """Recognize all specified block responses, even when cards are present."""
    from ebay_live.client import check_page  # noqa: PLC0415 - isolated transport test.

    with pytest.raises(EbayBlockedError):
        check_page(
            (FIXTURES / fixture).read_text(encoding="utf-8"), url, status, search=True
        )


def test_damaged_title_is_not_a_value_pick() -> None:
    """A broken listing must not beat an intact comparable solely on price."""
    intact = Listing(
        "1",
        "Sony headphones",
        "https://www.ebay.com/itm/1",
        price=100,
        currency="USD",
        shipping_cost=0,
        condition="Pre-Owned",
    )
    broken = replace(
        intact, item_id="2", price=79, title="Sony headphones Left Side Broke"
    )
    ranked = rank_results([broken, intact], "Sony headphones", buy_now=False)
    assert [r["item_id"] for r in ranked] == ["1", "2"]
    assert "possible damaged item; refine include or exclude terms" in cast(
        "list[str]", ranked[1]["reasons"]
    )


def test_no_match_template_is_not_visible_evidence() -> None:
    """A script template cannot prove that an unrecognized page has no matches."""
    with pytest.raises(EbayBlockedError):
        _ = parse_search_results('<script>template="No exact matches";</script>Loading')
    assert parse_search_results("<h1>No exact matches</h1>") == []


def test_structured_detail_shipping() -> None:
    """Read an Offer rate when the page has no DOM shipping field."""
    html = """<script type="application/ld+json">
    {"@type":"Product","name":"Camera","offers":{"price":"90.00",
    "priceCurrency":"USD","shippingDetails":[{"shippingRate":{
    "value":"8.50","currency":"USD"}}]}}
    </script>"""
    detail = parse_item_detail(html)
    assert detail.price == 90
    assert detail.shipping_cost == 8.5


def test_captured_accessories_do_not_win() -> None:
    """Captured cheap bags and boards rank below complete OLED consoles."""
    listings = parse_search_results(
        (FIXTURES / "steam-rewrite.html").read_text(encoding="utf-8")
    )
    ranked = rank_results(listings, "steam deck oled", buy_now=False)
    assert all(cast("float", r["total_cost"]) > 200 for r in ranked[:4])


@pytest.mark.parametrize(
    "answer_class",
    [
        "ITEMS_CAROUSEL_WITH_COLOR",
        "NAVIGATION_ANSWER_COLLAPSIBLE_CAROUSEL",
    ],
)
def test_answer_carousels_are_not_river_listings(answer_class: str) -> None:
    """Nested listing-looking cards and cards outside the river never count."""
    card = """<li class="s-card">
    <a class="s-card__link" href="/itm/987654321012"></a>
    <div class="s-card__title">Camera</div></li>"""
    other = card.replace("987654321012", "987654321013")
    html = f"""{other}<ul class="srp-results">{card}
    <li class="srp-river-answer srp-river-answer--{answer_class}">
    <ul>{other}</ul></li></ul>"""
    results = parse_search_results(html)
    assert [r.item_id for r in results] == ["987654321012"]


def test_query_relevance_uses_whole_normalized_tokens() -> None:
    """Substrings such as 40700 must not count as a match for 4070."""
    from ebay_live.score import query_match  # noqa: PLC0415 - focused pure signal.

    assert query_match("NVIDIA RTX-4070", "rtx 4070 RTX") == 1
    assert query_match("NVIDIA RTX 40700", "rtx 4070") == 0.5


def test_captured_shell_above_outlier_cutoff() -> None:
    """A replacement shell above the price cutoff still loses to a console."""
    listings = parse_search_results(
        (FIXTURES / "steam-rewrite.html").read_text(encoding="utf-8")
    )
    shell = next(r for r in listings if "Full Cover Shell" in r.title)
    console = next(r for r in listings if r.title == "Valve OLED Steam Deck 512 GB")
    ranked = rank_results([shell, console], "steam deck oled", buy_now=False)
    assert [r["item_id"] for r in ranked] == [console.item_id, shell.item_id]


def test_captured_sponsored_is_unknown() -> None:
    """Obfuscated labels in every captured card do not prove sponsorship."""
    listings = parse_search_results(
        (FIXTURES / "search.html").read_text(encoding="utf-8")
    )
    assert all(r.sponsored is None for r in listings)
    ranked = rank_results(listings, "sony", buy_now=False)
    assert all("sponsored listing" not in str(r["reasons"]) for r in ranked)


def test_store_subtitle_and_new_listing_badge() -> None:
    """A minimally edited real card separates badges and store copy from evidence."""
    listing = parse_search_results(
        (FIXTURES / "store-badge.html").read_text(encoding="utf-8")
    )[0]
    assert listing.condition == "Brand New"
    assert listing.title == (
        "Sony WH-1000XM5 Wireless Noise Canceling Headphones - Black, needs repair"
    )


@pytest.mark.parametrize(
    "condition",
    [
        "New (Other)",
        "Open Box",
        "Pre-Owned",
        "Used",
        "Excellent - Refurbished",
        "Certified - Refurbished",
        "Seller Refurbished",
        "For parts or not working",
        None,
    ],
)
def test_known_conditions_after_store_copy(condition: str | None) -> None:
    """Known condition labels survive a preceding tagline; absent labels stay null."""
    html = (FIXTURES / "store-badge.html").read_text(encoding="utf-8")
    listing = parse_search_results(html.replace("Brand New", condition or "Sale"))[0]
    assert listing.condition == condition


def test_new_listing_badge_is_not_title_text() -> None:
    """The leading badge on a minimally edited captured title is stripped."""
    html = (FIXTURES / "store-badge.html").read_text(encoding="utf-8")
    listing = parse_search_results(html)[0]
    assert listing.title.startswith("Sony WH-1000XM5")
    assert "New Listing" not in listing.title
