"""Kinguin marketplace adapter (port of lib/adapters/kinguin.ts)."""

import re
from typing import TYPE_CHECKING
from urllib.parse import quote

from adapters.common import (
    RawScrapedItem,
    extract_raw_items,
    is_str_dict,
    normalize_raw_items,
)

if TYPE_CHECKING:
    from models import MarketplaceId, RawMarketListing, SearchTarget

_LINK_HEAD_PAT = r"\[([^\]]+)\]\((https://www\.kinguin\.net/category/[^)]+)\)"
_LINK_TAIL_PAT = r"[\s\S]*?([0-9]+(?:\.[0-9]+)?)\s*(?:USD|\$|EUR|€)"
_LINK_RE = re.compile(f"{_LINK_HEAD_PAT}{_LINK_TAIL_PAT}")


class KinguinAdapter:
    """Kinguin marketplace adapter."""

    id: MarketplaceId = "kinguin"
    display_name: str = "Kinguin"
    is_enabled_by_default: bool = True

    def build_search_target(self, query: str) -> SearchTarget:
        """Build the Kinguin listing URL for a query."""
        encoded = quote(query.strip(), safe="!'()*")
        return {
            "marketplace": self.id,
            "url": f"https://www.kinguin.net/listing?phrase={encoded}&active=1&hide_out_of_stock=1",
            "waitForMs": 2000,
            "format": "json",
        }

    def parse_listings(self, raw: object) -> list[RawMarketListing]:
        """Parse Kinguin markdown or JSON scrape output into listings."""
        if not raw:
            return []

        if isinstance(raw, str):
            items: list[RawScrapedItem] = []
            for match in _LINK_RE.finditer(raw):
                title = match.group(1).strip() if match.group(1) else ""
                url = match.group(2)
                price = match.group(3)
                if title and price and "logo" not in title and "Sign in" not in title:
                    item: RawScrapedItem = {
                        "title": title,
                        "url": url,
                        "priceUsd": price,
                        "sellerRating": 97,
                    }
                    if url:
                        parts = url.split("/category/")
                        item_id = parts[1].split("/")[0] if len(parts) > 1 else ""
                        item["id"] = item_id or f"kinguin-{len(items) + 1}"
                    items.append(item)

            return normalize_raw_items(items, self.id, 30)

        if is_str_dict(raw):
            return normalize_raw_items(extract_raw_items(raw), self.id, 30)

        return []
