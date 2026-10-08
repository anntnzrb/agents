"""Typed search inputs, listing records, and transport errors."""

import math
import re
from dataclasses import dataclass, field
from typing import Literal

Transport = Literal["auto", "direct", "firecrawl"]
SORTS = {
    "best-match": "12",
    "ending-soonest": "1",
    "newly-listed": "10",
    "price-lowest": "15",
    "price-highest": "16",
    "nearest": "7",
}
CONDITIONS = {
    "new": "1000",
    "open-box": "1500",
    "refurbished": "2000",
    "used": "3000",
    "for-parts": "7000",
}


class EbayLiveError(RuntimeError):
    """Network, blocking, or unrecognized page failure."""


class EbayBlockedError(EbayLiveError):
    """A challenge or sign-in wall prevented catalog access."""


@dataclass(frozen=True, slots=True)
class SearchQuery:
    """Normalized eBay-side query parameters."""

    keywords: str
    sort: str = "best-match"
    min_price: float | None = None
    max_price: float | None = None
    condition: str | None = None
    buy_it_now: bool = False
    auction: bool = False
    page: int = 1
    per_page: int = 60
    zip_code: str | None = None

    def __post_init__(self) -> None:
        """Reject invalid search parameters before fetching."""
        object.__setattr__(self, "keywords", self.keywords.strip())
        if not self.keywords:
            raise ValueError("query must not be empty")
        if self.sort not in SORTS:
            raise ValueError("unknown sort")
        if self.condition is not None and self.condition not in CONDITIONS:
            raise ValueError("unknown condition")
        if self.page < 1 or self.per_page not in (60, 120, 240):
            raise ValueError("page must be positive; perPage must be 60, 120, or 240")
        for price in (self.min_price, self.max_price):
            if price is not None and (not math.isfinite(price) or price < 0):
                raise ValueError("prices must be finite and non-negative")
        if (
            self.min_price is not None
            and self.max_price is not None
            and self.min_price > self.max_price
        ):
            raise ValueError("minPrice must not exceed maxPrice")
        if self.buy_it_now and self.auction:
            raise ValueError("buyItNow and auction are mutually exclusive")
        if self.zip_code is not None and not re.fullmatch(r"[0-9]{5}", self.zip_code):
            raise ValueError("zipCode must be a five-digit US ZIP code")


@dataclass(frozen=True, slots=True)
class Listing:
    """Observed card fields; missing evidence stays null."""

    item_id: str
    title: str
    url: str
    price: float | None = None
    price_max: float | None = None
    currency: str | None = None
    shipping_cost: float | None = None
    condition: str | None = None
    buying_format: tuple[str, ...] = ()
    bid_count: int | None = None
    time_left: str | None = None
    time_end: str | None = None
    seller_name: str | None = None
    seller_feedback_pct: float | None = None
    seller_feedback_count: int | None = None
    location: str | None = None
    sponsored: bool | None = None

    @property
    def total_cost(self) -> float | None:
        """Return price plus shipping only when both amounts are known."""
        if self.price is None or self.shipping_cost is None:
            return None
        return round(self.price + self.shipping_cost, 2)

    def to_dict(self) -> dict[str, object]:
        """Serialize a listing with explicit nullable fields."""
        return {
            "item_id": self.item_id,
            "title": self.title,
            "url": self.url,
            "price": self.price,
            "price_max": self.price_max,
            "currency": self.currency,
            "shipping_cost": self.shipping_cost,
            "total_cost": self.total_cost,
            "condition": self.condition,
            "buying_format": list(self.buying_format),
            "bid_count": self.bid_count,
            "time_left": self.time_left,
            "time_end": self.time_end,
            "seller_name": self.seller_name,
            "seller_feedback_pct": self.seller_feedback_pct,
            "seller_feedback_count": self.seller_feedback_count,
            "location": self.location,
            "sponsored": self.sponsored,
        }


@dataclass(frozen=True, slots=True)
class ItemDetail:
    """Item-page evidence kept separate from the search snapshot."""

    title: str | None = None
    price: float | None = None
    currency: str | None = None
    condition: str | None = None
    bid_count: int | None = None
    time_left: str | None = None
    seller_name: str | None = None
    seller_feedback_text: str | None = None
    returns: str | None = None
    shipping_text: str | None = None
    shipping_cost: float | None = None
    brand: str | None = None
    model: str | None = None
    gtin: str | None = None
    mpn: str | None = None
    availability: str | None = None
    item_specifics: dict[str, str] = field(default_factory=dict)
