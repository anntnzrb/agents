"""Plati.Market adapter (port of lib/adapters/plati.ts)."""

from typing import TYPE_CHECKING, TypeIs
from urllib.parse import quote

from adapters.common import (
    RawScrapedItem,
    extract_raw_items,
    is_str_dict,
    normalize_raw_items,
)
from models import js_string

if TYPE_CHECKING:
    from models import MarketplaceId, RawMarketListing, SearchTarget


def _is_js_number_or_string(val: object) -> TypeIs[float | str]:
    """Match JavaScript `typeof val === "number" || typeof val === "string"`."""
    return (isinstance(val, (int, float)) and not isinstance(val, bool)) or isinstance(
        val, str
    )


def _map_plati_item(item: object) -> RawScrapedItem | None:
    """Normalize a single Plati API item into a RawScrapedItem."""
    if not is_str_dict(item):
        return None
    record = item
    item_id: object = record.get("id")
    title: object = record.get("name_eng") or record.get("name") or record.get("title")
    price: object = record.get("price_usd") or record.get("price")
    sales: object = record.get("sales_count") or record.get("salesCount")
    rating_val: object = record.get("rating")
    rating: object = 99 if rating_val is None else rating_val

    entry: RawScrapedItem = {}
    if "id" in record:
        entry["id"] = js_string(item_id)
        entry["url"] = f"https://plati.market/itm/{js_string(item_id)}?lang=en-US"
    if title is not None or "title" in record:
        entry["title"] = js_string(title)
    if _is_js_number_or_string(price):
        entry["priceUsd"] = price
    if _is_js_number_or_string(rating):
        entry["sellerRating"] = rating
    if _is_js_number_or_string(sales):
        entry["salesCount"] = sales
    return entry


class PlatiAdapter:
    """Plati.Market adapter."""

    id: MarketplaceId = "plati"
    display_name: str = "Plati.Market"
    is_enabled_by_default: bool = True

    def build_search_target(self, query: str) -> SearchTarget:
        """Build the Plati API search URL for a query."""
        encoded = quote(query.strip(), safe="!'()*")
        return {
            "marketplace": self.id,
            "url": f"https://plati.io/api/search.ashx?query={encoded}&pagesize=30&response=json",
            "format": "api",
        }

    def parse_listings(self, raw: object) -> list[RawMarketListing]:
        """Map Plati API items into normalized listings."""
        items = extract_raw_items(raw)
        mapped: list[RawScrapedItem] = []
        for item in items:
            if (entry := _map_plati_item(item)) is not None:
                mapped.append(entry)

        return normalize_raw_items(mapped, self.id, 30)
