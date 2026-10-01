"""Shared normalization helpers for marketplace adapters (port of common.ts)."""

import math
import re
from typing import TYPE_CHECKING, TypedDict, TypeIs
from urllib.parse import quote

from models import DeliveryFormat, MarketplaceId, RawMarketListing, js_string

if TYPE_CHECKING:
    from collections.abc import Sequence


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


# Seller logs into the buyer account: never a self-service delivery.
_CREDENTIAL_PHRASES = (
    r"top[\s-]*up",
    r"by\s*logging",
    r"log\s*in\s*to\s*(?:your|the|my)\s*account",
    r"put\s*(?:it\s*)?into\s*(?:my|your)\s*account",
)
_CREDENTIALS_RE = re.compile("|".join(_CREDENTIAL_PHRASES))
_SELF_SERVICE_RE = re.compile(
    r"without\s*log|no\s*login|self[\s-]*redeem|redeem\s*by\s*yourself"
)
_FLOAT_PREFIX_RE = re.compile(r"[+-]?(\d+(\.\d*)?|\.\d+)")
_NON_NUMERIC_DOT_RE = re.compile(r"[^0-9.]")
_NON_DIGIT_RE = re.compile(r"[^0-9]")

# Ratings at or below this value are treated as a 0-5 scale
_FIVE_POINT_RATING_MAX = 5


def _is_js_number(val: object) -> TypeIs[float | int]:
    """Match JavaScript `typeof val === "number" && !isNaN(val)`."""
    return (
        isinstance(val, (int, float))
        and not isinstance(val, bool)
        and not math.isnan(float(val))
    )


def _js_parse_float(cleaned: str) -> float | None:
    """Match JavaScript parseFloat on a digit-and-dot cleaned string."""
    match = _FLOAT_PREFIX_RE.match(cleaned)
    if match is None:
        return None
    return float(match.group(0))


def _first_defined[T](fields: dict[str, T], *keys: str) -> T | None:
    """Emulate a JavaScript `??` chain across keys: first non-None value."""
    for key in keys:
        value = fields.get(key)
        if value is not None:
            return value
    return None


def _encode_uri_component(value: str) -> str:
    """Match JavaScript encodeURIComponent."""
    return quote(value, safe="!'()*")


def parse_price(val: object) -> float:
    """Parse a price value from a number or loose string."""
    if _is_js_number(val):
        return float(val)
    if isinstance(val, str):
        cleaned = _NON_NUMERIC_DOT_RE.sub("", val)
        parsed = _js_parse_float(cleaned)
        return 0.0 if parsed is None else parsed
    return 0.0


def parse_rating(val: object, fallback: float = 95.0) -> float:
    """Parse a seller rating, normalizing 0-5 scales to percentages."""
    if _is_js_number(val):
        num = float(val)
        return (num / 5) * 100 if num <= _FIVE_POINT_RATING_MAX else num
    if isinstance(val, str):
        cleaned = _NON_NUMERIC_DOT_RE.sub("", val)
        parsed = _js_parse_float(cleaned)
        if parsed is not None:
            return (parsed / 5) * 100 if parsed <= _FIVE_POINT_RATING_MAX else parsed
    return fallback


def parse_sales(val: object, fallback: int = 100) -> int:
    """Parse a sales or review count."""
    if _is_js_number(val):
        return math.floor(float(val))
    if isinstance(val, str):
        cleaned = _NON_DIGIT_RE.sub("", val)
        if cleaned:
            return int(cleaned, 10)
        return fallback
    return fallback


def detect_delivery_format(title: str, raw_type: object = None) -> DeliveryFormat:
    """Classify the delivery format from title and seller-provided type."""
    raw_str = str(raw_type) if raw_type is not None else ""
    combined = f"{title} {raw_str}".lower()
    if (
        "cookie" in combined
        or "session token" in combined
        or "token connect" in combined
        or "auth token" in combined
    ):
        return "SESSION_COOKIE"
    if _CREDENTIALS_RE.search(combined) and not _SELF_SERVICE_RE.search(combined):
        return "CREDENTIALS_REQUIRED"
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


def is_str_dict(val: object) -> TypeIs[dict[str, object]]:
    """Narrow an object to a string-keyed dictionary."""
    return isinstance(val, dict)


def is_object_list(val: object) -> TypeIs[list[object]]:
    """Narrow an object to a list of objects."""
    return isinstance(val, list)


def as_dict(item: object) -> dict[str, object]:
    """Convert a loose item to a string-keyed dictionary."""
    return item if is_str_dict(item) else {}


def extract_raw_items(raw: object) -> list[object]:
    """Extract the items or products list from a raw response dictionary."""
    if not is_str_dict(raw):
        return []
    raw_items = raw.get("items")
    if not is_object_list(raw_items):
        raw_items = raw.get("products")
    return raw_items if is_object_list(raw_items) else []


def normalize_raw_items(
    raw_items: Sequence[object],
    marketplace: MarketplaceId,
    default_warranty_days: float = 14,
) -> list[RawMarketListing]:
    """Normalize loose scraped items into RawMarketListing records."""
    result: list[RawMarketListing] = []

    for i, item in enumerate(raw_items):
        if not item:
            continue

        fields = as_dict(item)
        title_val = fields.get("title") or fields.get("name")
        title: str = str(title_val).strip() if title_val is not None else ""
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

        url_raw = fields.get("url")
        url = (
            str(url_raw)
            if url_raw is not None
            else f"https://www.{marketplace}.com/search?query={_encode_uri_component(title)}"
        )
        seller_raw = fields.get("sellerName") or fields.get("seller")
        seller_name = (
            str(seller_raw)
            if seller_raw is not None
            else f"{marketplace.upper()} Verified Seller"
        )
        desc_raw = fields.get("description")
        desc = str(desc_raw) if desc_raw is not None else title

        result.append(
            {
                "id": js_string(fields.get("id") or f"{marketplace}-{i + 1}"),
                "marketplace": marketplace,
                "title": title,
                "url": url,
                "priceUsd": price_usd,
                "seller": {
                    "name": seller_name,
                    "positiveFeedbackPercent": rating_percent,
                    "totalSalesCount": float(total_sales),
                },
                "deliveryFormat": format_,
                "isStockAvailable": True,
                "isAutoDelivery": True,
                "isGlobal": is_global,
                "warrantyDays": default_warranty_days,
                "description": desc,
            }
        )

    return result
