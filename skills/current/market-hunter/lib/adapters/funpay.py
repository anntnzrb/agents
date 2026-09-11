"""FunPay marketplace adapter (port of lib/adapters/funpay.ts)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from adapters.common import RawScrapedItem, normalize_raw_items

if TYPE_CHECKING:
    from models import MarketplaceId, RawMarketListing, SearchTarget

CATEGORY_MAP: dict[str, str] = {
    "chatgpt": "https://funpay.com/en/lots/1355/",
    "claude": "https://funpay.com/en/lots/4187/",
    "copilot": "https://funpay.com/en/lots/4150/",
    "cursor": "https://funpay.com/en/lots/3736/",
    "gemini": "https://funpay.com/en/lots/4093/",
    "discord": "https://funpay.com/en/lots/596/",
    "telegram": "https://funpay.com/en/lots/1266/",
    "spotify": "https://funpay.com/en/lots/372/",
}

_OFFER_RE = re.compile(
    r'<a[^>]*class="[^"]*tc-item[^"]*"[^>]*href="([^"]+)"[^>]*>([\s\S]*?)</a>'
)
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
    display_name = "FunPay"
    is_enabled_by_default = True

    def build_search_target(self, query: str) -> SearchTarget:
        """Build the FunPay lot-category URL for a query."""
        q_lower = query.lower()
        target_url = "https://funpay.com/en/lots/1355/"  # default to AI/chatgpt

        for key, url in CATEGORY_MAP.items():
            if key in q_lower:
                target_url = url
                break

        return {
            "marketplace": self.id,
            "url": target_url,
            "waitForMs": 1500,
            "format": "api",  # Allows direct fast HTML fetch & parse
        }

    def parse_listings(self, raw: Any) -> list[RawMarketListing]:
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
                            "url": (
                                href
                                if href.startswith("http")
                                else f"https://funpay.com{href}"
                            ),
                        }
                    )

            return normalize_raw_items(items, self.id, 7)

        # 2. If raw is JSON from Firecrawl schema
        if isinstance(raw, dict):
            raw_items = raw.get("items")
            if not isinstance(raw_items, list):
                raw_items = raw.get("products")
            return normalize_raw_items(
                raw_items if isinstance(raw_items, list) else [],
                self.id,
                7,
            )

        return []
