"""Plati.Market adapter (port of lib/adapters/plati.ts)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypeGuard
from urllib.parse import quote

from adapters.common import RawScrapedItem, normalize_raw_items
from models import js_string

if TYPE_CHECKING:
    from models import MarketplaceId, RawMarketListing, SearchTarget


def _is_js_number_or_string(val: Any) -> TypeGuard[float | str]:
    """Match JavaScript `typeof val === "number" || typeof val === "string"`."""
    return (isinstance(val, (int, float)) and not isinstance(val, bool)) or isinstance(
        val, str
    )


class PlatiAdapter:
    """Plati.Market adapter."""

    id: MarketplaceId = "plati"
    display_name = "Plati.Market"
    is_enabled_by_default = True

    def build_search_target(self, query: str) -> SearchTarget:
        """Build the Plati API search URL for a query."""
        encoded = quote(query.strip(), safe="!'()*")
        return {
            "marketplace": self.id,
            "url": f"https://plati.io/api/search.ashx?query={encoded}&pagesize=30&response=json",
            "format": "api",
        }

    def parse_listings(self, raw: Any) -> list[RawMarketListing]:
        """Map Plati API items into normalized listings."""
        if not raw or not isinstance(raw, dict):
            return []

        raw_items = raw.get("items")
        if not isinstance(raw_items, list):
            raw_items = raw.get("products")
        items = raw_items if isinstance(raw_items, list) else []

        mapped: list[RawScrapedItem] = []
        for item in items:
            record: dict[str, Any] = item if isinstance(item, dict) else {}
            item_id = record.get("id")
            title = record.get("name_eng") or record.get("name") or record.get("title")
            price = record.get("price_usd") or record.get("price")
            sales = record.get("sales_count") or record.get("salesCount")
            rating = record.get("rating")
            if rating is None:
                rating = 99

            entry: RawScrapedItem = {}
            if "id" in record:
                entry["id"] = js_string(item_id)
            if title is not None or "title" in record:
                entry["title"] = js_string(title)
            if _is_js_number_or_string(price):
                entry["priceUsd"] = price
            if _is_js_number_or_string(rating):
                entry["sellerRating"] = rating
            if _is_js_number_or_string(sales):
                entry["salesCount"] = sales
            if "id" in record:
                entry["url"] = (
                    f"https://plati.market/itm/{js_string(item_id)}?lang=en-US"
                )
            mapped.append(entry)

        return normalize_raw_items(mapped, self.id, 30)
