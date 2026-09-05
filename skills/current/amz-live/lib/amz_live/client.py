"""Sync HTTP client for live Amazon search pages."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from collections.abc import Mapping
    from types import TracebackType

import http

import httpx

from .models import AmazonAntiBotError, AmazonClientError, SearchQuery, SearchResult
from .parser import parse_search_results
from .query import AMAZON_BASE_URL, build_search_url

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Upgrade-Insecure-Requests": "1",
}
_ANTI_BOT_MARKERS = (
    "captcha",
    "validatecaptcha",
    "robot check",
    "not a robot",
    "enter the characters you see below",
    "type the characters you see in this image",
    "automated access",
)
_ANTI_BOT_URL_MARKERS = (
    "validatecaptcha",
    "errors/captcha",
    "errors/validatecaptcha",
)
_HTML_CACHE: dict[str, str] = {}


class AmazonSearchClient:
    """Small sync client for read-only live Amazon search."""

    def __init__(
        self,
        *,
        base_url: str = AMAZON_BASE_URL,
        timeout: float = 20.0,
        headers: Mapping[str, str] | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        """Configure base URL, timeout, headers, and transport."""
        self.base_url: str = base_url.rstrip("/")
        self._owns_client: bool = client is None
        merged_headers = {**DEFAULT_HEADERS, **(dict(headers) if headers else {})}
        self._client: httpx.Client = client or httpx.Client(
            headers=merged_headers,
            timeout=timeout,
            follow_redirects=True,
        )

    def __enter__(self) -> Self:
        """Enter the client context."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        """Close the owned client on context exit."""
        self.close()
        return False

    def close(self) -> None:
        """Close the owned HTTP client."""
        if self._owns_client:
            self._client.close()

    def fetch_html(self, url: str) -> str:
        """Fetch a page body, using the in-memory cache."""
        cached = _HTML_CACHE.get(url)
        if cached is not None:
            return cached

        try:
            response = self._client.get(url)
        except httpx.HTTPError as exc:
            msg = f"Amazon request failed: {exc}"
            raise AmazonClientError(msg) from exc

        self._raise_for_bad_response(response)
        _HTML_CACHE[url] = response.text
        return response.text

    def fetch_search_page(self, query: SearchQuery) -> str:
        """Fetch the search-results page for a query."""
        url = build_search_url(query, base_url=self.base_url)
        return self.fetch_html(url)

    def fetch_product_page(self, url: str) -> str:
        """Fetch a product-detail page by URL."""
        return self.fetch_html(url)

    def search(self, query: SearchQuery) -> list[SearchResult]:
        """Search one page and parse the results."""
        html = self.fetch_search_page(query)
        return parse_search_results(html, base_url=self.base_url)

    def search_pages(self, query: SearchQuery, *, pages: int = 1) -> list[SearchResult]:
        """Search multiple pages and deduplicate by ASIN."""
        if pages < 1:
            msg = "pages must be >= 1"
            raise ValueError(msg)

        deduped: dict[str, SearchResult] = {}
        for page_number in range(query.page, query.page + pages):
            page_query = SearchQuery(
                query.keywords,
                page=page_number,
                amazon_sort=query.amazon_sort,
                zip_code=query.zip_code,
            )
            for result in self.search(page_query):
                _ = deduped.setdefault(result.asin, result)
        return list(deduped.values())

    def _raise_for_bad_response(self, response: httpx.Response) -> None:
        body = response.text.casefold()
        url = str(response.url)
        lowered_url = url.casefold()

        if response.status_code == http.HTTPStatus.SERVICE_UNAVAILABLE or any(
            marker in body for marker in _ANTI_BOT_MARKERS
        ):
            msg = (
                f"Amazon blocked the request with a captcha or 503: {url}. "
                "Slow down, try later, or use --html for local debug."
            )
            raise AmazonAntiBotError(msg)

        if any(marker in lowered_url for marker in _ANTI_BOT_URL_MARKERS):
            msg = (
                f"Amazon redirected to a captcha or robot-check page: {url}. "
                "Slow down, try later, or use --html for local debug."
            )
            raise AmazonAntiBotError(msg)

        if response.status_code >= http.HTTPStatus.BAD_REQUEST:
            msg = f"Amazon returned HTTP {response.status_code}: {url}"
            raise AmazonClientError(msg)


def search(
    keywords: str,
    *,
    page: int = 1,
    pages: int = 1,
    amazon_sort: str | None = None,
    base_url: str = AMAZON_BASE_URL,
) -> list[SearchResult]:
    """Search live Amazon pages and return parsed results."""
    query = SearchQuery(keywords, page=page, amazon_sort=amazon_sort)
    client = AmazonSearchClient(base_url=base_url)
    try:
        return client.search_pages(query, pages=pages)
    finally:
        client.close()


__all__ = ["DEFAULT_HEADERS", "AmazonSearchClient", "search"]
