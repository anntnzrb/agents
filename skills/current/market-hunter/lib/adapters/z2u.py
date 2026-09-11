"""Z2U marketplace adapter (port of lib/adapters/z2u.ts)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from adapters.common import RawScrapedItem, normalize_raw_items

if TYPE_CHECKING:
    from models import MarketplaceId, RawMarketListing, SearchTarget

_LINK_RE = re.compile(r"\[([^\]]+)\]\((https://www\.z2u\.com/product-[^)]+)\)")
_FROM_PRICE_RE = re.compile(r"from\$([0-9]+(?:\.[0-9]+)?)")
_PRICE_RE = re.compile(r"\$([0-9]+(?:\.[0-9]+)?)")
_TITLE_RE = re.compile(r"([^\\\[]+)")


class Z2uAdapter:
    """Z2U marketplace adapter."""

    id: MarketplaceId = "z2u"
    display_name = "Z2U"
    is_enabled_by_default = True

    def build_search_target(self, query: str) -> SearchTarget:
        """Build the Z2U search URL for a query."""
        encoded = quote(query.strip(), safe="!'()*")
        return {
            "marketplace": self.id,
            "url": f"https://www.z2u.com/search?q={encoded}",
            "waitForMs": 2000,
            "format": "json",
        }

    def parse_listings(self, raw: Any) -> list[RawMarketListing]:
        """Parse Z2U markdown or JSON scrape output into listings."""
        if not raw:
            return []

        if isinstance(raw, str):
            items: list[RawScrapedItem] = []
            for match in _LINK_RE.finditer(raw):
                full_block = match.group(1) or ""
                url = match.group(2)
                price_match = _FROM_PRICE_RE.search(full_block) or _PRICE_RE.search(
                    full_block
                )
                title_match = _TITLE_RE.match(full_block)

                title = title_match.group(1).strip() if title_match else ""
                price = price_match.group(1) if price_match else ""

                if title and price:
                    item: RawScrapedItem = {
                        "title": title,
                        "url": url,
                        "priceUsd": price,
                        "sellerRating": 98,
                    }
                    if url:
                        parts = url.split("/product-")
                        item_id = parts[1].split("/")[0] if len(parts) > 1 else ""
                        item["id"] = item_id or f"z2u-{len(items) + 1}"
                    items.append(item)

            return normalize_raw_items(items, self.id, 14)

        if isinstance(raw, dict):
            raw_items = raw.get("items")
            if not isinstance(raw_items, list):
                raw_items = raw.get("products")
            return normalize_raw_items(
                raw_items if isinstance(raw_items, list) else [],
                self.id,
                14,
            )

        return []
