"""FunPay marketplace adapter (port of lib/adapters/funpay.ts)."""

import re
from typing import TYPE_CHECKING

from adapters.common import (
    RawScrapedItem,
    extract_raw_items,
    is_str_dict,
    normalize_raw_items,
)

if TYPE_CHECKING:
    from models import MarketplaceId, RawMarketListing, SearchTarget

# Live markup puts href before class; match either attribute order.
_OFFER_RE = re.compile(
    r'<a\b(?=[^>]*\bclass="[^"]*\btc-item\b)[^>]*\bhref="([^"]+)"[^>]*>([\s\S]*?)</a>'
)
_REVIEWS_RE = re.compile(r'<span[^>]*class="[^"]*rating-mini-count[^"]*"[^>]*>(\d+)<')
_DESC_RE = re.compile(r'<div[^>]*class="[^"]*tc-desc-text[^"]*"[^>]*>([\s\S]*?)</div>')
_USER_RE = re.compile(
    r'<div[^>]*class="[^"]*media-user-name[^"]*"[^>]*>([\s\S]*?)</div>'
)
_PRICE_RE = re.compile(r'<div[^>]*class="[^"]*tc-price[^"]*"[^>]*>([\s\S]*?)</div>')
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_tags(value: str | None) -> str:
    """Strip HTML tags and surrounding whitespace; None/empty yields ''."""
    return _TAG_RE.sub("", value).strip() if value else ""


class FunPayAdapter:
    """FunPay marketplace adapter."""

    id: MarketplaceId = "funpay"
    display_name: str = "FunPay"
    is_enabled_by_default: bool = True

    def build_search_target(self, query: str) -> SearchTarget:
        """Build the FunPay fetch target; FunPay has no search, so pass --url."""
        _ = query
        return {
            "marketplace": self.id,
            "url": "https://funpay.com/en/",
            "waitForMs": 1500,
            "format": "api",  # Allows direct fast HTML fetch & parse
            # Without this cookie FunPay prices in EUR.
            "headers": {"Cookie": "cy=usd"},
        }

    def parse_listings(self, raw: object) -> list[RawMarketListing]:
        """Parse FunPay HTML or JSON scrape output into listings."""
        if not raw:
            return []

        # 1. If raw is HTML string from direct SSR fetch
        if isinstance(raw, str) and "funpay.com" in raw:
            items: list[RawScrapedItem] = []

            for match in _OFFER_RE.finditer(raw):
                href = match.group(1)
                block = match.group(2)
                if not href or not block:
                    continue

                desc_match = _DESC_RE.search(block)
                user_match = _USER_RE.search(block)
                price_match = _PRICE_RE.search(block)
                reviews_match = _REVIEWS_RE.search(block)

                title = _strip_tags(desc_match.group(1)) if desc_match else ""
                seller_name = (
                    _strip_tags(user_match.group(1))
                    if user_match
                    else "FunPay Verified Seller"
                )
                price_raw = _strip_tags(price_match.group(1)) if price_match else ""

                if title and price_raw:
                    href_parts = href.split("id=")
                    items.append(
                        {
                            "id": (
                                href_parts[1]
                                if len(href_parts) > 1 and href_parts[1]
                                else f"funpay-{len(items) + 1}"
                            ),
                            "title": title,
                            "sellerName": seller_name,
                            "priceUsd": price_raw,
                            "sellerRating": 99,
                            "reviewsCount": (
                                reviews_match.group(1) if reviews_match else "0"
                            ),
                            "url": (
                                href
                                if href.startswith("http")
                                else f"https://funpay.com{href}"
                            ),
                        }
                    )

            return normalize_raw_items(items, self.id, 7)

        # 2. If raw is JSON from Firecrawl schema
        if is_str_dict(raw):
            return normalize_raw_items(extract_raw_items(raw), self.id, 7)

        return []
