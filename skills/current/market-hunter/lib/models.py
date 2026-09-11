"""Data models, error types, and JS-compatible formatting helpers."""

from __future__ import annotations

import math
import sys
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal, NotRequired, Protocol, TypedDict

SCHEMA_VERSION = 1

type DeliveryFormat = Literal[
    "DEDICATED_ACCOUNT",
    "BUYER_EMAIL_UPGRADE",
    "PROMO_LINK_OR_CODE",
    "STUDENT_PACK",
    "SHARED_POOL",
    "SESSION_COOKIE",
    "UNKNOWN",
]

type TrustTier = Literal[
    "STRONG_BUY",
    "ACCEPTABLE",
    "RISKY_BUDGET",
    "AVOID_DANGER",
    "CONFIRMED_SCAM",
]

type MarketplaceId = str


class SellerMetadata(TypedDict):
    """Seller metadata embedded in a listing."""

    name: str
    positiveFeedbackPercent: float
    totalSalesCount: NotRequired[float]
    totalReviewsCount: NotRequired[float]
    tenureDescription: NotRequired[str]
    isOnline: NotRequired[bool]


class RawMarketListing(TypedDict):
    """A raw marketplace listing before scoring."""

    id: str
    marketplace: str
    title: str
    url: str
    priceUsd: float
    originalCurrency: NotRequired[str]
    originalPrice: NotRequired[float]
    seller: SellerMetadata
    deliveryFormat: DeliveryFormat
    isStockAvailable: bool
    isAutoDelivery: bool
    isGlobal: bool
    warrantyDays: NotRequired[float]
    description: NotRequired[str]


class ScoredDeal(RawMarketListing):
    """A listing after scoring by the decision engine."""

    trustScore: float
    trustTier: TrustTier
    priceSanityScore: float
    sellerScore: float
    formatScore: float
    warrantyScore: float
    penaltyDeductions: float
    detectedRedFlags: list[str]
    isCircuitBreakerTripped: bool
    circuitBreakerReason: NotRequired[str]
    discountVsMsrpPercent: float
    recommendationSummary: str


class SearchTarget(TypedDict):
    """A scrape or API fetch target built by an adapter."""

    marketplace: MarketplaceId
    url: str
    format: Literal["json", "api", "html"]
    queryParams: NotRequired[dict[str, str]]
    waitForMs: NotRequired[int]


class MarketplaceAdapter(Protocol):
    """Contract implemented by each marketplace adapter."""

    id: MarketplaceId
    display_name: str
    is_enabled_by_default: bool

    def build_search_target(self, query: str) -> SearchTarget:
        """Build the fetch or scrape target for a query."""
        ...

    def parse_listings(self, raw: Any) -> list[RawMarketListing]:
        """Normalize raw fetched or scraped data into listings."""
        ...


class ScanOptions(TypedDict):
    """Options accepted by the scan engine."""

    query: str
    budget: NotRequired[float]
    typeFilter: NotRequired[str]
    minScore: NotRequired[int]
    markets: NotRequired[list[str]]
    timeoutSeconds: NotRequired[float]
    jsonOnly: NotRequired[bool]
    full: NotRequired[bool]


class ScanResultData(TypedDict):
    """Payload emitted for a completed scan."""

    query: str
    budget: float | None
    total_scanned: int
    valid_deals_count: int
    filtered_scams_count: int
    top_deals: list[ScoredDeal]
    markets_queried: list[str]
    degraded_markets: list[str]
    is_degraded_mode: NotRequired[bool]
    warning: NotRequired[str]


class EnvelopeError(TypedDict):
    """Error object inside the CLI envelope."""

    code: str
    message: str
    details: NotRequired[dict[str, Any]]


class DealHunterEnvelope(TypedDict):
    """Top-level JSON envelope emitted by the CLI."""

    ok: bool
    schema_version: int
    command: Literal["scan"]
    data: NotRequired[ScanResultData]
    error: NotRequired[EnvelopeError]


class AdapterError(Exception):
    """Failure raised by a marketplace adapter."""

    def __init__(self, marketplace: str, message: str, cause: Any = None) -> None:
        """Initialize the adapter failure."""
        super().__init__(message)
        self.marketplace = marketplace
        self.message = message
        self.cause = cause


class EngineError(Exception):
    """Failure raised by the scan engine."""

    def __init__(
        self, code: str, message: str, details: dict[str, Any] | None = None
    ) -> None:
        """Initialize the engine failure."""
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


def js_round(value: float) -> int:
    """Match JavaScript Math.round (half toward positive infinity)."""
    return math.floor(value + 0.5)


def js_number_to_str(value: float) -> str:
    """Match JavaScript number-to-string conversion in string interpolation."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
        if value.is_integer():
            return str(int(value))
    return str(value)


def js_to_fixed2(value: float) -> str:
    """Match JavaScript Number.prototype.toFixed(2) on the exact binary value."""
    if isinstance(value, float) and math.isnan(value):
        return "NaN"
    if isinstance(value, float) and math.isinf(value):
        return "Infinity" if value > 0 else "-Infinity"
    return str(Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def js_to_locale_string(value: float) -> str:
    """Match JavaScript Number.prototype.toLocaleString() default grouping."""
    if float(value).is_integer():
        return f"{int(value):,}"
    return f"{value:,.3f}".rstrip("0").rstrip(".")


def js_string(value: Any) -> str:
    """Match JavaScript String(value) for JSON scalar types."""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    return js_number_to_str(value) if isinstance(value, (int, float)) else str(value)


NUMBER_EPSILON = sys.float_info.epsilon
