"""Z2U marketplace adapter (port of lib/adapters/z2u.ts)."""

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

_CARD_HEAD = r'<a\b(?=[^>]*\bclass="[^"]*\bproductCardStyle)[^>]*'
_CARD_TAIL = r'\bhref="(https://www\.z2u\.com/product-[^"]+)"[^>]*>([\s\S]*?)</a>'
_CARD_RE = re.compile(_CARD_HEAD + _CARD_TAIL)
_CARD_TITLE_RE = re.compile(r'<span class="title">([^<]+)</span>')
_CARD_PRICE_RE = re.compile(r'<span class="priceTxt">\$([0-9]+(?:\.[0-9]+)?)</span>')
_CARD_ATTR_RE = re.compile(r'<span class="fromAttr">([^<]+)</span>')
_LINK_RE = re.compile(r"\[([^\]]+)\]\((https://www\.z2u\.com/product-[^)]+)\)")
_FROM_PRICE_RE = re.compile(r"from\$([0-9]+(?:\.[0-9]+)?)")
_PRICE_RE = re.compile(r"\$([0-9]+(?:\.[0-9]+)?)")
_TITLE_RE = re.compile(r"([^\\\[]+)")


def _product_id(url: str, fallback: str) -> str:
    parts = url.split("/product-")
    item_id = parts[1].split("/")[0] if len(parts) > 1 else ""
    return item_id or fallback


def _parse_cards(raw: str) -> list[RawScrapedItem]:
    items: list[RawScrapedItem] = []
    for match in _CARD_RE.finditer(raw):
        url, block = match.group(1), match.group(2)
        title_match = _CARD_TITLE_RE.search(block)
        price_match = _CARD_PRICE_RE.search(block)
        if not title_match or not price_match:
            continue
        item: RawScrapedItem = {
            "id": _product_id(url, f"z2u-{len(items) + 1}"),
            "title": title_match.group(1).strip(),
            "url": url,
            "priceUsd": price_match.group(1),
            "sellerRating": 98,
        }
        if attr_match := _CARD_ATTR_RE.search(block):
            item["deliveryType"] = attr_match.group(1).strip()
        items.append(item)
    return items


def _parse_markdown(raw: str) -> list[RawScrapedItem]:
    items: list[RawScrapedItem] = []
    for match in _LINK_RE.finditer(raw):
        full_block = match.group(1) or ""
        url = match.group(2)
        price_match = _FROM_PRICE_RE.search(full_block) or _PRICE_RE.search(full_block)
        title_match = _TITLE_RE.match(full_block)
        title = title_match.group(1).strip() if title_match else ""
        price = price_match.group(1) if price_match else ""
        if title and price:
            items.append(
                {
                    "id": _product_id(url, f"z2u-{len(items) + 1}"),
                    "title": title,
                    "url": url,
                    "priceUsd": price,
                    "sellerRating": 98,
                }
            )
    return items


class Z2uAdapter:
    """Z2U marketplace adapter."""

    id: MarketplaceId = "z2u"
    display_name: str = "Z2U"
    is_enabled_by_default: bool = True

    def build_search_target(self, query: str) -> SearchTarget:
        """Build the Z2U search URL; it renders client-side, so prefer --url."""
        encoded = quote(query.strip(), safe="!'()*")
        return {
            "marketplace": self.id,
            "url": f"https://www.z2u.com/search?q={encoded}",
            "format": "api",
        }

    def parse_listings(self, raw: object) -> list[RawMarketListing]:
        """Parse Z2U category HTML, scraped markdown, or JSON into listings."""
        if not raw:
            return []

        if isinstance(raw, str):
            items = _parse_cards(raw) if "productCardStyle" in raw else []
            return normalize_raw_items(items or _parse_markdown(raw), self.id, 14)

        if is_str_dict(raw):
            return normalize_raw_items(extract_raw_items(raw), self.id, 14)

        return []
