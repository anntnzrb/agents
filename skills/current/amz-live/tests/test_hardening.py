from __future__ import annotations

import json
from decimal import Decimal
from io import StringIO
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict, cast

if TYPE_CHECKING:
    import pytest

    from amz_live.models import ProductDetailPayload

import httpx

from amz_live.cli import main
from amz_live.client import AmazonSearchClient
from amz_live.models import SearchQuery, SearchResult
from amz_live.protocol import load_results

SEARCH_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "search_results_fragment.html"


class _EnrichedResult(TypedDict):
    asin: str
    score: float
    reasons: list[str]
    details: ProductDetailPayload
    signal_scores: dict[str, float]


def test_scoring_demotes_usb_a_mismatch_for_usb_c_to_usb_c_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results = [
        SearchResult(
            asin="USBA1",
            title="Braided USB A to USB C Cable 6ft Fast Charging",
            url="https://www.amazon.com/dp/USB-A-1",
            price=Decimal("7.99"),
            rating=Decimal("4.6"),
            review_count=5000,
        ),
        SearchResult(
            asin="USBC1",
            title="Braided USB C to USB C Cable 6ft Fast Charging",
            url="https://www.amazon.com/dp/USB-C-1",
            price=Decimal("7.99"),
            rating=Decimal("4.6"),
            review_count=5000,
        ),
    ]

    def fake_load_results(**_kwargs: object) -> list[SearchResult]:
        return results

    monkeypatch.setattr("amz_live.protocol.load_results", fake_load_results)

    stdout = StringIO()
    exit_code = main(
        [
            "usb c to usb c braided cable",
            "--scoring",
            "--json",
        ],
        stdout=stdout,
    )

    assert exit_code == 0

    payload = cast("list[_EnrichedResult]", json.loads(stdout.getvalue()))
    assert [item["asin"] for item in payload] == ["USBC1", "USBA1"]
    assert payload[0]["score"] > payload[1]["score"]


def test_client_fetch_html_reuses_lightweight_cache_for_same_url() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, text="<html>cached once</html>", request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = AmazonSearchClient(client=http_client)
        url = "https://www.amazon.com/s?k=usb+c+to+usb+c+cable"

        first = client.fetch_html(url)
        second = client.fetch_html(url)

    assert first == second == "<html>cached once</html>"
    assert calls == [url]


def test_protocol_load_results_reuses_cached_search_html(
    monkeypatch: pytest.MonkeyPatch, search_html: str
) -> None:
    calls: list[tuple[str, int, int]] = []

    def fake_search_pages(
        _self: AmazonSearchClient, query: SearchQuery, *, pages: int = 1
    ) -> list[SearchResult]:
        calls.append((query.keywords, query.page, pages))
        from amz_live.parser import parse_search_results

        return parse_search_results(search_html)

    monkeypatch.setattr(
        "amz_live.client.AmazonSearchClient.search_pages",
        fake_search_pages,
    )

    first = load_results(
        query="usb c to usb c braided cable",
        html_path=None,
        page=1,
        pages=1,
        amazon_sort=None,
    )
    second = load_results(
        query="usb c to usb c braided cable",
        html_path=None,
        page=1,
        pages=1,
        amazon_sort=None,
    )

    assert [result.asin for result in first] == [result.asin for result in second]
    assert calls == [("usb c to usb c braided cable", 1, 1)]


def test_scoring_output_includes_merchant_trust_from_detail_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    merchant_html = """
    <html>
      <body>
        <a id="bylineInfo">Visit the Amazon Basics Store</a>
        <div id="availability">In Stock.</div>
        <div id="deliveryBlockMessage">FREE delivery Tomorrow</div>
        <div id="tabular-buybox">
          <div class="tabular-buybox-container">
            <span class="tabular-buybox-text" tabindex="-1">Ships from</span>
            <span class="tabular-buybox-text a-text-bold">Amazon.com</span>
          </div>
          <div class="tabular-buybox-container">
            <span class="tabular-buybox-text" tabindex="-1">Sold by</span>
            <span class="tabular-buybox-text a-text-bold">Amazon.com</span>
          </div>
        </div>
      </body>
    </html>
    """
    results = [
        SearchResult(
            asin="B07CWC39TL",
            title="Amazon Basics USB-C to USB-C Fast Charging Cable",
            url="https://www.amazon.com/dp/B07CWC39TL",
            price=Decimal("7.99"),
            rating=Decimal("4.5"),
            review_count=22038,
        ),
    ]

    def fake_load_results(**_kwargs: object) -> list[SearchResult]:
        return results

    monkeypatch.setattr("amz_live.protocol.load_results", fake_load_results)

    def fake_fetch_product_page(_self: AmazonSearchClient, _url: str) -> str:
        return merchant_html

    monkeypatch.setattr(
        "amz_live.client.AmazonSearchClient.fetch_product_page",
        fake_fetch_product_page,
        raising=False,
    )

    stdout = StringIO()
    exit_code = main(
        [
            "usb c to usb c braided cable",
            "--details",
            "--scoring",
            "--json",
        ],
        stdout=stdout,
    )

    assert exit_code == 0

    payload = cast("list[_EnrichedResult]", json.loads(stdout.getvalue()))
    details = payload[0]["details"]
    assert details["ships_from"] == "Amazon.com"
    assert details["sold_by"] == "Amazon.com"
    assert payload[0]["signal_scores"]["merchant_trust"] > 0
    assert any(
        "merchant" in reason.casefold() or "amazon.com" in reason.casefold()
        for reason in payload[0]["reasons"]
    )
