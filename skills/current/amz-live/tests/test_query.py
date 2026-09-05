from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

    from amz_live.models import SearchResult

from urllib.parse import parse_qs, urlparse

from amz_live.client import AmazonSearchClient
from amz_live.query import SearchQuery, build_search_url


def test_search_query_to_params_uses_amazon_k_and_page_fields() -> None:
    query = SearchQuery("usb c to usb c braided cable", page=3)

    assert query.to_params() == {"k": "usb c to usb c braided cable", "page": "3"}


def test_build_search_url_encodes_keywords_into_canonical_search_url() -> None:
    url = build_search_url(SearchQuery("usb c to usb c braided cable", page=3))
    parsed = urlparse(url)

    assert parsed.scheme == "https"
    assert parsed.netloc == "www.amazon.com"
    assert parsed.path == "/s"
    assert parse_qs(parsed.query) == {
        "k": ["usb c to usb c braided cable"],
        "page": ["3"],
    }


def test_search_pages_preserves_zip_code_across_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    seen_zip_codes: list[str | None] = []

    def fake_search(_self: AmazonSearchClient, query: SearchQuery) -> list[SearchResult]:
        seen_zip_codes.append(query.zip_code)
        return []

    monkeypatch.setattr(AmazonSearchClient, "search", fake_search)

    with AmazonSearchClient() as client:
        _ = client.search_pages(SearchQuery("usb c pd charger", zip_code="33101"), pages=2)

    assert seen_zip_codes == ["33101", "33101"]


def test_search_query_to_params_adds_zip_filter_when_present() -> None:
    query = SearchQuery("usb c pd charger", page=1, zip_code="33101")

    assert query.to_params() == {
        "k": "usb c pd charger",
        "page": "1",
        "rh": "p_47:33101",
    }


def test_build_search_url_encodes_zip_filter_when_present() -> None:
    url = build_search_url(SearchQuery("usb c pd charger", zip_code="33101"))
    parsed = urlparse(url)

    assert parse_qs(parsed.query) == {
        "k": ["usb c pd charger"],
        "page": ["1"],
        "rh": ["p_47:33101"],
    }
