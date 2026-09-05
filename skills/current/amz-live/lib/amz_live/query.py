"""Amazon search URL construction."""

from __future__ import annotations

from urllib.parse import urlencode

from .models import SearchQuery

AMAZON_BASE_URL = "https://www.amazon.com"
AMAZON_SEARCH_PATH = "/s"


def build_search_url(query: SearchQuery, *, base_url: str = AMAZON_BASE_URL) -> str:
    """Build an Amazon search URL from a query."""
    base = base_url.rstrip("/")
    return f"{base}{AMAZON_SEARCH_PATH}?{urlencode(query.to_params())}"


__all__ = ["AMAZON_BASE_URL", "AMAZON_SEARCH_PATH", "SearchQuery", "build_search_url"]
