"""Trust and deal scoring engine (port of lib/scoring.ts)."""

from __future__ import annotations

import math
import re
from typing import cast

from models import (
    NUMBER_EPSILON,
    DeliveryFormat,
    RawMarketListing,
    ScoredDeal,
    TrustTier,
    js_number_to_str,
    js_round,
    js_to_fixed2,
)

RED_FLAG_PATTERNS: tuple[tuple[re.Pattern[str], int, str], ...] = (
    (
        re.compile(
            r"session\s*token|cookie\s*inject|auth\s*cookie|auth\s*token",
            re.IGNORECASE,
        ),
        100,
        "Session Cookie / Auth Token Hijack Risk",
    ),
    (
        re.compile(
            r"shared|family\s*pool|multi\s*device|5\s*devices|co-use|shared\s*account",
            re.IGNORECASE,
        ),
        40,
        "Shared Multi-User Pool",
    ),
    (
        re.compile(
            r"\|\s*go\s*\||\bchatgpt\s*go\b|\bgo\s*subscription\b",
            re.IGNORECASE,
        ),
        15,
        "Tier Mismatch Risk (May be lower-tier Go option in dropdown)",
    ),
    (
        re.compile(r"no\s*warranty|no\s*replacement|as-is", re.IGNORECASE),
        30,
        "No Seller Replacement Warranty",
    ),
    (
        re.compile(r"change\s*pass(word)?\s*in\s*1\s*h(our)?", re.IGNORECASE),
        35,
        "Short Lifetime / Churn Account",
    ),
    (
        re.compile(r"risk\s*of\s*ban|temporary\s*use", re.IGNORECASE),
        25,
        "Reported Ban Risk",
    ),
    (
        re.compile(r"carded|cracked|stolen", re.IGNORECASE),
        100,
        "Carded / Fraudulent Origin",
    ),
)


# Price sanity ratio thresholds (priceUsd / msrp)
_PRICE_RATIO_MICRO_DUMP = 0.05
_PRICE_RATIO_SWEET_SPOT_MIN = 0.10
_PRICE_RATIO_SWEET_SPOT_MAX = 0.50
_PRICE_RATIO_FAIR_DISCOUNT_MAX = 0.75
_PRICE_RATIO_RETAIL_MAX = 1.00

# Warranty day thresholds
_WARRANTY_DAYS_STRONG = 30
_WARRANTY_DAYS_STANDARD = 14
_WARRANTY_DAYS_MINIMAL = 7
_WARRANTY_DAYS_ANY = 1

# Circuit breaker thresholds
_MIN_SELLER_FEEDBACK_PERCENT = 75
_DEDICATED_ACCOUNT_SUSPICIOUS_PRICE = 0.80
_PREMIUM_SERVICE_MSRP = 20

# Trust tier thresholds
_TIER_STRONG_BUY = 85
_TIER_ACCEPTABLE = 70
_TIER_RISKY_BUDGET = 50
_TIER_AVOID_DANGER = 25


def estimate_msrp(title: str) -> int:
    """Estimate the standard retail price for a listing by title keywords."""
    t = title.lower()
    if "perplexity" in t and (
        "year" in t or "1 yr" in t or "12 month" in t or "1y" in t
    ):
        return 200
    if "copilot" in t and ("year" in t or "1 yr" in t or "12 month" in t or "1y" in t):
        return 100
    if "adobe" in t and ("year" in t or "1 yr" in t or "12 month" in t):
        return 600
    if "gemini" in t and ("6 month" in t or "6m" in t):
        return 120
    if "gemini" in t and ("3 month" in t or "3m" in t):
        return 60
    if (
        "gemini" in t
        or "chatgpt" in t
        or "claude" in t
        or "cursor" in t
        or "midjourney" in t
    ):
        return 20
    if "spotify" in t and ("year" in t or "12 month" in t):
        return 120
    if "youtube" in t and ("year" in t or "12 month" in t):
        return 140
    if "discord" in t and ("nitro" in t or "year" in t):
        return 100
    return 20


def compute_price_sanity(price_usd: float, msrp: float) -> int:
    """Score the price-to-MSRP ratio against arbitrage sanity curves."""
    if price_usd <= 0 or msrp <= 0:
        return 0
    ratio = price_usd / msrp

    # Suspicious micro-dump (e.g. $0.50 for a $20 service) -> high scam likelihood
    if ratio < _PRICE_RATIO_MICRO_DUMP:
        return 20
    if ratio < _PRICE_RATIO_SWEET_SPOT_MIN:
        return 50

    # Sweet spot for arbitrage / promo links (e.g. $2.50 to $9.00 on $20 service)
    if _PRICE_RATIO_SWEET_SPOT_MIN <= ratio <= _PRICE_RATIO_SWEET_SPOT_MAX:
        return 100

    # Fair discount ($10.00 to $15.00 on $20 service)
    if _PRICE_RATIO_SWEET_SPOT_MAX < ratio <= _PRICE_RATIO_FAIR_DISCOUNT_MAX:
        return 80

    # Low arbitrage / near retail
    if _PRICE_RATIO_FAIR_DISCOUNT_MAX < ratio <= _PRICE_RATIO_RETAIL_MAX:
        return 50

    # Above retail
    return 30


def compute_seller_score(pos_percent: float, sales_count: float | None = None) -> int:
    """Score seller reliability with Bayesian smoothing and log-scaled volume."""
    count = 100 if sales_count is None else sales_count
    # Bayesian smoothed feedback ratio (prior of 95% on 50 sales)
    smoothed_percent = (pos_percent * count + 95 * 50) / (count + 50)

    # Log-scaled sales volume score (0 - 100)
    volume_score = min(100, max(10, 20 * math.log10(max(1, count))))

    return js_round(0.6 * smoothed_percent + 0.4 * volume_score)


_FORMAT_SCORES: dict[str, int] = {
    "DEDICATED_ACCOUNT": 95,
    "BUYER_EMAIL_UPGRADE": 90,
    "PROMO_LINK_OR_CODE": 85,
    "STUDENT_PACK": 65,
    "SHARED_POOL": 30,
    "SESSION_COOKIE": 0,
}


def compute_format_score(format: DeliveryFormat) -> int:
    """Score the delivery format safety class."""
    return _FORMAT_SCORES.get(format, 50)


def compute_warranty_score(warranty_days: float | None = None) -> int:
    """Score the seller replacement warranty window."""
    days = 0 if warranty_days is None else warranty_days
    if days >= _WARRANTY_DAYS_STRONG:
        return 100
    if days >= _WARRANTY_DAYS_STANDARD:
        return 85
    if days >= _WARRANTY_DAYS_MINIMAL:
        return 70
    if days >= _WARRANTY_DAYS_ANY:
        return 50
    return 30


def score_listing(listing: RawMarketListing) -> ScoredDeal:
    """Score a raw listing through the trust and deal decision engine."""
    msrp = estimate_msrp(listing["title"])
    price_score = compute_price_sanity(listing["priceUsd"], msrp)
    seller_score = compute_seller_score(
        listing["seller"]["positiveFeedbackPercent"],
        listing["seller"].get("totalSalesCount"),
    )
    format_score = compute_format_score(listing["deliveryFormat"])
    warranty_score = compute_warranty_score(listing.get("warrantyDays"))

    detected_red_flags: list[str] = []
    penalty_deductions = 0
    searchable_text = f"{listing['title']} {listing.get('description') or ''}".lower()

    for pattern, penalty, label in RED_FLAG_PATTERNS:
        if pattern.search(searchable_text):
            detected_red_flags.append(label)
            penalty_deductions += penalty

    # Check hard circuit breakers
    is_circuit_breaker_tripped = False
    circuit_breaker_reason: str | None = None

    if listing["deliveryFormat"] == "SESSION_COOKIE" or "cookie" in searchable_text:
        is_circuit_breaker_tripped = True
        circuit_breaker_reason = "High-risk session cookie injection detected"
    elif listing["seller"]["positiveFeedbackPercent"] < _MIN_SELLER_FEEDBACK_PERCENT:
        is_circuit_breaker_tripped = True
        circuit_breaker_reason = (
            "Low seller feedback rating "
            f"({js_number_to_str(listing['seller']['positiveFeedbackPercent'])}%)"
        )
    elif (
        listing["priceUsd"] < _DEDICATED_ACCOUNT_SUSPICIOUS_PRICE
        and msrp >= _PREMIUM_SERVICE_MSRP
        and listing["deliveryFormat"] == "DEDICATED_ACCOUNT"
    ):
        is_circuit_breaker_tripped = True
        circuit_breaker_reason = (
            "Unrealistically low price for dedicated account (high fraud probability)"
        )

    final_trust_score = (
        5
        if is_circuit_breaker_tripped
        else js_round(
            0.30 * price_score
            + 0.30 * seller_score
            + 0.25 * format_score
            + 0.15 * warranty_score
            - penalty_deductions
        )
    )

    final_trust_score = max(0, min(100, final_trust_score))

    trust_tier: TrustTier = "CONFIRMED_SCAM"
    if final_trust_score >= _TIER_STRONG_BUY:
        trust_tier = "STRONG_BUY"
    elif final_trust_score >= _TIER_ACCEPTABLE:
        trust_tier = "ACCEPTABLE"
    elif final_trust_score >= _TIER_RISKY_BUDGET:
        trust_tier = "RISKY_BUDGET"
    elif final_trust_score >= _TIER_AVOID_DANGER:
        trust_tier = "AVOID_DANGER"

    discount_percent = max(
        0,
        js_round(((msrp - listing["priceUsd"]) / msrp) * 100 + NUMBER_EPSILON),
    )
    recommendation_summary = (
        f"{trust_tier}: ${js_to_fixed2(listing['priceUsd'])} "
        f"({discount_percent}% off est. ${js_number_to_str(msrp)} retail)"
    )
    if len(detected_red_flags) > 0:
        recommendation_summary += f" | Warnings: {', '.join(detected_red_flags)}"

    return cast(
        "ScoredDeal",
        {
            **listing,
            "trustScore": final_trust_score,
            "trustTier": trust_tier,
            "priceSanityScore": price_score,
            "sellerScore": seller_score,
            "formatScore": format_score,
            "warrantyScore": warranty_score,
            "penaltyDeductions": penalty_deductions,
            "detectedRedFlags": detected_red_flags,
            "isCircuitBreakerTripped": is_circuit_breaker_tripped,
            **(
                {"circuitBreakerReason": circuit_breaker_reason}
                if circuit_breaker_reason is not None
                else {}
            ),
            "discountVsMsrpPercent": discount_percent,
            "recommendationSummary": recommendation_summary,
        },
    )
