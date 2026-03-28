from __future__ import annotations

from collections.abc import Mapping

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
        self.base_url = base_url.rstrip("/")
        self._owns_client = client is None
        merged_headers = {**DEFAULT_HEADERS, **(dict(headers) if headers else {})}
        self._client = client or httpx.Client(
            headers=merged_headers,
            timeout=timeout,
            follow_redirects=True,
        )

    def __enter__(self) -> AmazonSearchClient:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def fetch_html(self, url: str) -> str:
        cached = _HTML_CACHE.get(url)
        if cached is not None:
            return cached

        try:
            response = self._client.get(url)
        except httpx.HTTPError as exc:
            raise AmazonClientError(f"Amazon request failed: {exc}") from exc

        self._raise_for_bad_response(response)
        _HTML_CACHE[url] = response.text
        return response.text

    def fetch_search_page(self, query: SearchQuery) -> str:
        url = build_search_url(query, base_url=self.base_url)
        return self.fetch_html(url)

    def fetch_product_page(self, url: str) -> str:
        return self.fetch_html(url)

    def search(self, query: SearchQuery) -> list[SearchResult]:
        html = self.fetch_search_page(query)
        return parse_search_results(html, base_url=self.base_url)

    def search_pages(self, query: SearchQuery, *, pages: int = 1) -> list[SearchResult]:
        if pages < 1:
            raise ValueError("pages must be >= 1")

        deduped: dict[str, SearchResult] = {}
        for page_number in range(query.page, query.page + pages):
            page_query = SearchQuery(
                query.keywords,
                page=page_number,
                amazon_sort=query.amazon_sort,
            )
            for result in self.search(page_query):
                deduped.setdefault(result.asin, result)
        return list(deduped.values())

    def _raise_for_bad_response(self, response: httpx.Response) -> None:
        body = response.text.casefold()
        url = str(response.url)
        lowered_url = url.casefold()

        if response.status_code == 503 or any(marker in body for marker in _ANTI_BOT_MARKERS):
            raise AmazonAntiBotError(
                f"Amazon blocked the request with a captcha or 503: {url}. "
                "Slow down, try later, or use --html for local debug."
            )

        if any(marker in lowered_url for marker in _ANTI_BOT_URL_MARKERS):
            raise AmazonAntiBotError(
                f"Amazon redirected to a captcha or robot-check page: {url}. "
                "Slow down, try later, or use --html for local debug."
            )

        if response.status_code >= 400:
            raise AmazonClientError(f"Amazon returned HTTP {response.status_code}: {url}")


def search(
    keywords: str,
    *,
    page: int = 1,
    pages: int = 1,
    amazon_sort: str | None = None,
    base_url: str = AMAZON_BASE_URL,
) -> list[SearchResult]:
    query = SearchQuery(keywords, page=page, amazon_sort=amazon_sort)
    with AmazonSearchClient(base_url=base_url) as client:
        return client.search_pages(query, pages=pages)


__all__ = ["AmazonSearchClient", "DEFAULT_HEADERS", "search"]
