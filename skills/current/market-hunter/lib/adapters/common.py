"""Shared normalization helpers for marketplace adapters (port of common.ts)."""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from typing import Any, TypedDict, cast
from urllib.parse import quote

from models import DeliveryFormat, MarketplaceId, RawMarketListing, js_string


class RawScrapedItem(TypedDict, total=False):
    """Loose shape of a single scraped or API-returned offer."""

    id: str | float
    title: str
    name: str
    priceUsd: float | str
    price: float | str
    rawPrice: float | str
    price_usd: float | str
    sellerName: str
    seller: str
    sellerRating: float | str
    rating: float | str
    sellerSalesCount: float | str
    salesCount: float | str
    sales_count: float | str
    reviewsCount: float | str
    deliveryType: str
    isGlobal: bool
    url: str
    warranty: str
    description: str


_FLOAT_PREFIX_RE = re.compile(r"[+-]?(\d+(\.\d*)?|\.\d+)")
_NON_NUMERIC_DOT_RE = re.compile(r"[^0-9.]")
_NON_DIGIT_RE = re.compile(r"[^0-9]")

# Ratings at or below this value are treated as a 0-5 scale
_FIVE_POINT_RATING_MAX = 5


def _is_js_number(val: Any) -> bool:
    """Match JavaScript `typeof val === "number" && !isNaN(val)`."""
    return (
        isinstance(val, (int, float))
        and not isinstance(val, bool)
        and not math.isnan(val)
    )


def _js_parse_float(cleaned: str) -> float | None:
    """Match JavaScript parseFloat on a digit-and-dot cleaned string."""
    match = _FLOAT_PREFIX_RE.match(cleaned)
    if match is None:
        return None
    return float(match.group(0))


def _first_defined(fields: dict[str, Any], *keys: str) -> Any:
    """Emulate a JavaScript `??` chain across keys: first non-None value."""
    for key in keys:
        value = fields.get(key)
        if value is not None:
            return value
    return None


def _encode_uri_component(value: str) -> str:
    """Match JavaScript encodeURIComponent."""
    return quote(value, safe="!'()*")


def parse_price(val: Any) -> float:
    """Parse a price value from a number or loose string."""
    if _is_js_number(val):
        return val
    if isinstance(val, str):
        cleaned = _NON_NUMERIC_DOT_RE.sub("", val)
        parsed = _js_parse_float(cleaned)
        return 0 if parsed is None else parsed
    return 0


def parse_rating(val: Any, fallback: float = 95) -> float:
    """Parse a seller rating, normalizing 0-5 scales to percentages."""
    if _is_js_number(val):
        return (val / 5) * 100 if val <= _FIVE_POINT_RATING_MAX else val
    if isinstance(val, str):
        cleaned = _NON_NUMERIC_DOT_RE.sub("", val)
        parsed = _js_parse_float(cleaned)
        if parsed is not None:
            return (parsed / 5) * 100 if parsed <= _FIVE_POINT_RATING_MAX else parsed
    return fallback


def parse_sales(val: Any, fallback: int = 100) -> int:
    """Parse a sales or review count."""
    if _is_js_number(val):
        return math.floor(val)
    if isinstance(val, str):
        cleaned = _NON_DIGIT_RE.sub("", val)
        if cleaned:
            return int(cleaned, 10)
        return fallback
    return fallback


def detect_delivery_format(title: str, raw_type: Any = None) -> DeliveryFormat:
    """Classify the delivery format from title and seller-provided type."""
    combined = f"{title} {raw_type or ''}".lower()

    if (
        "cookie" in combined
        or "session token" in combined
        or "token connect" in combined
        or "auth token" in combined
    ):
        return "SESSION_COOKIE"
    if (
        "shared" in combined
        or "family pool" in combined
        or "multi device" in combined
        or "5 devices" in combined
    ):
        return "SHARED_POOL"
    if "student" in combined or "edu pack" in combined or "github student" in combined:
        return "STUDENT_PACK"
    if (
        "invite" in combined
        or "upgrade your" in combined
        or "top up" in combined
        or "on your email" in combined
    ):
        return "BUYER_EMAIL_UPGRADE"
    if (
        "link" in combined
        or "code" in combined
        or "redeem" in combined
        or "voucher" in combined
        or "key" in combined
    ):
        return "PROMO_LINK_OR_CODE"
    if (
        "account" in combined
        or "acc" in combined
        or "personal" in combined
        or "dedicated" in combined
        or "private" in combined
    ):
        return "DEDICATED_ACCOUNT"

    return "UNKNOWN"


def normalize_raw_items(
    raw_items: Sequence[Any],
    marketplace: MarketplaceId,
    default_warranty_days: float = 14,
) -> list[RawMarketListing]:
    """Normalize loose scraped items into RawMarketListing records."""
    result: list[RawMarketListing] = []

    for i, item in enumerate(raw_items):
        if not item:
            continue

        fields = cast("dict[str, Any]", item) if isinstance(item, dict) else {}

        title = (fields.get("title") or fields.get("name") or "").strip()
        if not title:
            continue

        price_usd = parse_price(
            _first_defined(fields, "priceUsd", "price", "rawPrice", "price_usd")
        )
        if price_usd <= 0:
            continue

        rating_percent = parse_rating(_first_defined(fields, "sellerRating", "rating"))
        total_sales = parse_sales(
            _first_defined(
                fields, "sellerSalesCount", "salesCount", "sales_count", "reviewsCount"
            )
        )
        format_ = detect_delivery_format(title, fields.get("deliveryType"))

        title_lower = title.lower()
        is_global = (
            "us only" not in title_lower
            and "eu only" not in title_lower
            and "restricted" not in title_lower
            and "region locked" not in title_lower
        )

        result.append(
            {
                "id": js_string(fields.get("id") or f"{marketplace}-{i + 1}"),
                "marketplace": marketplace,
                "title": title,
                "url": fields.get("url")
                or f"https://www.{marketplace}.com/search?query={_encode_uri_component(title)}",
                "priceUsd": price_usd,
                "seller": {
                    "name": fields.get("sellerName")
                    or fields.get("seller")
                    or f"{marketplace.upper()} Verified Seller",
                    "positiveFeedbackPercent": rating_percent,
                    "totalSalesCount": total_sales,
                },
                "deliveryFormat": format_,
                "isStockAvailable": True,
                "isAutoDelivery": True,
                "isGlobal": is_global,
                "warrantyDays": default_warranty_days,
                "description": fields.get("description") or title,
            }
        )

    return result
