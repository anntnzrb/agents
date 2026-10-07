"""Sync HTTP client for live Amazon search pages."""

import json
import os
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal, Self, TypeIs
from urllib.parse import urlencode

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from types import TracebackType

import http

import httpx2
from selectolax.lexbor import LexborHTMLParser

from .models import AmazonAntiBotError, AmazonClientError, SearchPageInfo, SearchQuery, SearchResult
from .parser import discover_deal_filter, parse_search_page
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


def _is_mapping(value: object) -> TypeIs[dict[str, object]]:
    return isinstance(value, dict)


def _load_json(text: str) -> object:
    load: Callable[..., object] = json.loads
    return load(text)


class AmazonSearchClient:
    """Small sync client for read-only live Amazon search."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        timeout: float = 20.0,
        headers: Mapping[str, str] | None = None,
        client: httpx2.Client | None = None,
    ) -> None:
        """Configure base URL, timeout, headers, and transport."""
        self.base_url: str = (
            base_url or os.environ.get("AMZ_LIVE_BASE_URL", AMAZON_BASE_URL)
        ).rstrip("/")
        self.delivery_zip: str | None = None
        self._deal_filters: dict[str, tuple[str, str]] = {}
        self.page_info: SearchPageInfo = SearchPageInfo()
        self.checked_at: str | None = None
        self._owns_client: bool = client is None
        merged_headers = {**DEFAULT_HEADERS, **(dict(headers) if headers else {})}
        self._client: httpx2.Client = client or httpx2.Client(
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
    ) -> Literal[False]:
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
        except httpx2.HTTPError as exc:
            msg = f"Amazon request failed: {exc}"
            raise AmazonClientError(msg) from exc

        self._raise_for_bad_response(response)
        return response.text

    def set_delivery_zip(self, zip_code: str, bootstrap_url: str) -> None:
        """Set a guest US delivery session through Amazon's location widget."""
        if self.delivery_zip == zip_code:
            return
        initial = LexborHTMLParser(self.fetch_html(bootstrap_url))
        node = initial.css_first(
            "#nav-global-location-data-modal-action[data-a-modal]", strict=False
        )
        if node is None:
            raise AmazonClientError("Amazon delivery-location widget was not found")
        try:
            config = _load_json(node.attributes.get("data-a-modal") or "")
        except json.JSONDecodeError as exc:
            raise AmazonClientError(
                "Amazon delivery-location widget has invalid configuration"
            ) from exc
        if not _is_mapping(config):
            raise AmazonClientError("Amazon delivery-location widget has invalid configuration")
        path = config.get("url")
        headers = config.get("ajaxHeaders")
        if (
            not isinstance(path, str)
            or not path.startswith("/")
            or path.startswith("//")
            or not _is_mapping(headers)
        ):
            raise AmazonClientError(
                "Amazon delivery-location widget has invalid endpoint or headers"
            )
        token = headers.get("anti-csrftoken-a2z")
        if not isinstance(token, str):
            raise AmazonClientError("Amazon delivery-location widget is missing its CSRF token")
        try:
            modal = self._client.get(self.base_url + path, headers={"anti-csrftoken-a2z": token})
            self._raise_for_bad_response(modal)
            match = re.search(r'CSRF_TOKEN\s*:\s*"([^"]+)"', modal.text)
            if match is None:
                raise AmazonClientError("Amazon delivery-location modal is missing its CSRF token")
            response = self._client.post(
                self.base_url + "/portal-migration/hz/glow/address-change?actionSource=glow",
                headers={
                    "anti-csrftoken-a2z": match.group(1),
                    "X-Requested-With": "XMLHttpRequest",
                },
                json={
                    "locationType": "LOCATION_INPUT",
                    "zipCode": zip_code,
                    "deviceType": "web",
                    "storeContext": "generic",
                    "pageType": "Search",
                    "actionSource": "glow",
                },
            )
            self._raise_for_bad_response(response)
            updated = _load_json(response.text)
        except (httpx2.HTTPError, json.JSONDecodeError) as exc:
            raise AmazonClientError("Amazon delivery-location request failed") from exc
        if not _is_mapping(updated) or updated.get("isAddressUpdated") != 1:
            raise AmazonClientError(f"Amazon rejected delivery ZIP {zip_code}")
        self.delivery_zip = zip_code

    def fetch_search_page(self, query: SearchQuery) -> str:
        """Fetch the search-results page for a query."""
        url = build_search_url(query, base_url=self.base_url)
        if query.zip_code:
            self.set_delivery_zip(query.zip_code, url)
        if query.deals:
            key = query.keywords
            if key not in self._deal_filters:
                self._deal_filters[key] = discover_deal_filter(
                    self.fetch_html(url), base_url=self.base_url
                )
            term, _label = self._deal_filters[key]
            url = f"{self.base_url}/s?{urlencode({**query.to_params(), 'rh': term})}"
        return self.fetch_html(url)

    def fetch_product_page(self, url: str) -> str:
        """Fetch a product-detail page by URL."""
        return self.fetch_html(url)

    def search(self, query: SearchQuery) -> list[SearchResult]:
        """Search one page and parse the results."""
        html = self.fetch_search_page(query)
        results, self.page_info = parse_search_page(
            html, base_url=self.base_url, require_deals=query.deals
        )
        if (
            results
            and query.deals
            and self.page_info.deal_refinement != self._deal_filters[query.keywords][1]
        ):
            raise AmazonClientError(
                "Amazon applied a different deal filter than the discovered one"
            )
        self.checked_at = datetime.now(UTC).isoformat()
        if query.zip_code and not re.search(
            rf"\b{query.zip_code}\b", self.page_info.delivery_location or ""
        ):
            location = self.page_info.delivery_location or "location missing"
            raise AmazonClientError(
                f"Amazon did not confirm delivery ZIP {query.zip_code}: {location}"
            )
        return results

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
                deals=query.deals,
            )
            previous_info = self.page_info
            page_results = self.search(page_query)
            if not page_results:
                if deduped:
                    self.page_info = previous_info
                break
            for result in page_results:
                _ = deduped.setdefault(result.asin, result)
        return list(deduped.values())

    def _raise_for_bad_response(self, response: httpx2.Response) -> None:
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
