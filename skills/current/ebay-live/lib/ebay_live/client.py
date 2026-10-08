"""Shared-cookie direct transport with one Firecrawl fallback per blocked page."""

import os
import re
import time
from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING, Self
from urllib.parse import urlparse

from curl_cffi import requests
from firecrawl import Firecrawl  # pyright: ignore[reportMissingTypeStubs]
from firecrawl.v2.utils.error_handler import (  # pyright: ignore[reportMissingTypeStubs]
    RateLimitError,
)
from selectolax.lexbor import LexborHTMLParser

from .models import EbayBlockedError, EbayLiveError
from .parser import parse_search_results
from .query import EBAY_BASE_URL

if TYPE_CHECKING:
    from .models import Transport


@dataclass(frozen=True, slots=True)
class Fetch:
    """HTML plus the observed URL and serving transport."""

    html: str
    url: str
    transport: str


def check_page(html: str, url: str, status: int, *, search: bool) -> None:
    """Detect blocking before interpreting a response as catalog evidence."""
    parsed = urlparse(url)
    tree = LexborHTMLParser(html)
    title_node = tree.css_first("title")
    title = title_node.text().casefold() if title_node else ""
    if (
        status in (403, 429, 503)
        or "/splashui/challenge" in parsed.path
        or "/splashui/captcha" in parsed.path
        or (parsed.hostname or "").startswith("signin.ebay.")
        or "pardon our interruption" in title
        or "error page | ebay" in title
    ):
        raise EbayBlockedError(f"eBay blocked access (HTTP {status}): {url}")
    if status >= HTTPStatus.BAD_REQUEST:
        raise EbayLiveError(f"eBay returned HTTP {status}: {url}")
    if search:
        _ = parse_search_results(html)


class EbayClient:
    """Fetch pages with Safari impersonation and bounded transport fallback."""

    def __init__(self, transport: Transport = "auto") -> None:
        """Create one cookie session for searches and item enrichment."""
        self.base_url: str = os.environ.get("EBAY_LIVE_BASE_URL", EBAY_BASE_URL).rstrip(
            "/"
        )
        self.transport: Transport = transport
        self.session: requests.Session = requests.Session(
            impersonate="safari", timeout=20
        )
        self.log: list[dict[str, object]] = []
        self.warnings: list[str] = []

    def __enter__(self) -> Self:
        """Enter a search session."""
        return self

    def __exit__(self, *_exc: object) -> None:
        """Release the cookie session."""
        self.session.close()

    def fetch(self, url: str, *, search: bool = False) -> Fetch:
        """Fetch once directly; use Firecrawl once when auto detects blocking."""
        if self.transport == "firecrawl":
            return self._firecrawl(url, search=search)
        try:
            response = self.session.get(url)
        except requests.RequestsError as exc:
            # Use Chrome once if Safari cannot complete the request.
            try:
                response = self.session.get(url, impersonate="chrome")
            except requests.RequestsError as chrome_exc:
                raise EbayLiveError(
                    f"eBay direct request failed: {chrome_exc}"
                ) from exc
        final_url = str(response.url)
        try:
            check_page(response.text, final_url, response.status_code, search=search)
        except EbayBlockedError as exc:
            self.log.append(
                {"url": url, "final_url": final_url, "transport": "direct", "ok": False}
            )
            if self.transport == "direct" or not os.environ.get("FIRECRAWL_API_KEY"):
                hint = "Set FIRECRAWL_API_KEY and use --transport auto or firecrawl."
                raise EbayBlockedError(f"{exc}. {hint} Use --html offline.") from exc
            self.warnings.append(
                f"Direct eBay request blocked; used Firecrawl for {url}"
            )
            return self._firecrawl(url, search=search)
        except EbayLiveError:
            self.log.append(
                {"url": url, "final_url": final_url, "transport": "direct", "ok": False}
            )
            raise
        self.log.append(
            {"url": url, "final_url": final_url, "transport": "direct", "ok": True}
        )
        return Fetch(response.text, final_url, "direct")

    def _firecrawl(self, url: str, *, search: bool) -> Fetch:
        key = os.environ.get("FIRECRAWL_API_KEY")
        if not key:
            raise EbayLiveError("--transport firecrawl requires FIRECRAWL_API_KEY")
        app = Firecrawl(
            api_key=key,
            api_url=os.environ.get("FIRECRAWL_API_URL", "https://api.firecrawl.dev"),
            timeout=20,
            max_retries=0,
        )
        retried = False
        while True:
            try:
                document = app.scrape(
                    url,
                    formats=["rawHtml"],
                    only_main_content=False,
                    timeout=20000,
                    max_age=0,
                    store_in_cache=False,
                    auto_resume=False,
                )
                break
            except Exception as exc:
                self.log.append(
                    {
                        "url": url,
                        "final_url": url,
                        "transport": "firecrawl",
                        "ok": False,
                    }
                )
                if not retried and isinstance(exc, RateLimitError):
                    wait = re.search(
                        r"retry after\s+(\d+(?:\.\d+)?)\s*(?:s\b|seconds?\b)",
                        str(exc),
                        re.IGNORECASE,
                    )
                    time.sleep(min(float(wait[1]), 30.0) if wait else 2.0)
                    retried = True
                    continue
                raise EbayLiveError(f"Firecrawl request failed: {exc}") from exc
        html: object = getattr(document, "raw_html", None)
        if not isinstance(html, str) or not html.strip():
            self.log.append(
                {"url": url, "final_url": url, "transport": "firecrawl", "ok": False}
            )
            raise EbayLiveError("Firecrawl returned no raw HTML")
        metadata: object = getattr(document, "metadata", None)
        final: object = getattr(metadata, "url", None)
        status: object = getattr(metadata, "status_code", None)
        final_url = final if isinstance(final, str) else url
        status_code = status if isinstance(status, int) else 200
        try:
            check_page(html, final_url, status_code, search=search)
        except EbayLiveError:
            self.log.append(
                {
                    "url": url,
                    "final_url": final_url,
                    "transport": "firecrawl",
                    "ok": False,
                }
            )
            raise
        self.log.append(
            {"url": url, "final_url": final_url, "transport": "firecrawl", "ok": True}
        )
        return Fetch(html, final_url, "firecrawl")
