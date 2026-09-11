"""G2A marketplace adapter (port of lib/adapters/g2a.ts)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from adapters.common import RawScrapedItem, normalize_raw_items

if TYPE_CHECKING:
    from models import MarketplaceId, RawMarketListing, SearchTarget

_LINK_RE = re.compile(
    r"\[\*\*([^*]+)\*\*([\s\S]*?)\]\((https://www\.g2a\.com/[^)]+)\)"
    r"[\s\S]*?([0-9]+(?:\.[0-9]+)?)\s*USD"
)
_WHITESPACE_RE = re.compile(r"\s+")
_NEWLINES_RE = re.compile(r"[\n\r]+")
_MARKDOWN_CHARS_RE = re.compile(r"[-\\*#]+")
_NON_DIGIT_RE = re.compile(r"[^0-9]")


class G2aAdapter:
    """G2A marketplace adapter."""

    id: MarketplaceId = "g2a"
    display_name = "G2A"
    is_enabled_by_default = True

    def build_search_target(self, query: str) -> SearchTarget:
        """Build the G2A search URL for a query."""
        encoded = quote(query.strip(), safe="!'()*")
        return {
            "marketplace": self.id,
            "url": f"https://www.g2a.com/search?query={encoded}",
            "waitForMs": 2000,
            "format": "json",
        }

    def parse_listings(self, raw: Any) -> list[RawMarketListing]:
        """Parse G2A markdown or JSON scrape output into listings."""
        if not raw:
            return []

        if isinstance(raw, str):
            items: list[RawScrapedItem] = []
            for match in _LINK_RE.finditer(raw):
                title = _WHITESPACE_RE.sub(" ", match.group(1) or "").strip()
                sub_text = _WHITESPACE_RE.sub(
                    " ",
                    _MARKDOWN_CHARS_RE.sub(
                        " ", _NEWLINES_RE.sub(" ", match.group(2) or "")
                    ),
                ).strip()
                url = match.group(3)
                price = match.group(4)
                full_title = f"{title} - {sub_text}" if sub_text else title
                if title and price:
                    item: RawScrapedItem = {
                        "title": full_title,
                        "url": url,
                        "priceUsd": price,
                        "sellerRating": 98,
                    }
                    if url:
                        parts = url.split("-i")
                        cleaned_id = (
                            _NON_DIGIT_RE.sub("", parts[1]) if len(parts) > 1 else ""
                        )
                        item["id"] = cleaned_id or f"g2a-{len(items) + 1}"
                    if sub_text:
                        item["deliveryType"] = sub_text
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
