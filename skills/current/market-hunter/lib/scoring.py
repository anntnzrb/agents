"""Trust and deal scoring engine (port of lib/scoring.ts)."""

import math
import re

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


def _check_circuit_breaker(
    listing: RawMarketListing, msrp: float, searchable_text: str
) -> tuple[bool, str | None]:
    """Evaluate hard circuit breakers on suspicious or banned offers."""
    if listing["deliveryFormat"] == "SESSION_COOKIE" or "cookie" in searchable_text:
        return True, "High-risk session cookie injection detected"
    if listing["seller"]["positiveFeedbackPercent"] < _MIN_SELLER_FEEDBACK_PERCENT:
        pct_str = js_number_to_str(listing["seller"]["positiveFeedbackPercent"])
        return True, f"Low seller feedback rating ({pct_str}%)"
    if (
        listing["priceUsd"] < _DEDICATED_ACCOUNT_SUSPICIOUS_PRICE
        and msrp >= _PREMIUM_SERVICE_MSRP
        and listing["deliveryFormat"] == "DEDICATED_ACCOUNT"
    ):
        return True, (
            "Unrealistically low price for dedicated account (high fraud probability)"
        )
    return False, None


def _determine_trust_tier(final_trust_score: int) -> TrustTier:
    """Map a numerical trust score to its discrete TrustTier."""
    if final_trust_score >= _TIER_STRONG_BUY:
        return "STRONG_BUY"
    if final_trust_score >= _TIER_ACCEPTABLE:
        return "ACCEPTABLE"
    if final_trust_score >= _TIER_RISKY_BUDGET:
        return "RISKY_BUDGET"
    if final_trust_score >= _TIER_AVOID_DANGER:
        return "AVOID_DANGER"
    return "CONFIRMED_SCAM"


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

    is_tripped, circuit_breaker_reason = _check_circuit_breaker(
        listing, msrp, searchable_text
    )

    raw_score = (
        5
        if is_tripped
        else js_round(
            0.30 * price_score
            + 0.30 * seller_score
            + 0.25 * format_score
            + 0.15 * warranty_score
            - penalty_deductions
        )
    )
    final_trust_score = max(0, min(100, raw_score))
    trust_tier = _determine_trust_tier(final_trust_score)

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

    deal: ScoredDeal = {
        "id": listing["id"],
        "marketplace": listing["marketplace"],
        "title": listing["title"],
        "url": listing["url"],
        "priceUsd": listing["priceUsd"],
        "seller": listing["seller"],
        "deliveryFormat": listing["deliveryFormat"],
        "isStockAvailable": listing["isStockAvailable"],
        "isAutoDelivery": listing["isAutoDelivery"],
        "isGlobal": listing["isGlobal"],
        "trustScore": float(final_trust_score),
        "trustTier": trust_tier,
        "priceSanityScore": float(price_score),
        "sellerScore": float(seller_score),
        "formatScore": float(format_score),
        "warrantyScore": float(warranty_score),
        "penaltyDeductions": float(penalty_deductions),
        "detectedRedFlags": detected_red_flags,
        "isCircuitBreakerTripped": is_tripped,
        "discountVsMsrpPercent": float(discount_percent),
        "recommendationSummary": recommendation_summary,
    }
    if "originalCurrency" in listing:
        deal["originalCurrency"] = listing["originalCurrency"]
    if "originalPrice" in listing:
        deal["originalPrice"] = listing["originalPrice"]
    if "warrantyDays" in listing:
        deal["warrantyDays"] = listing["warrantyDays"]
    if "description" in listing:
        deal["description"] = listing["description"]
    if circuit_breaker_reason is not None:
        deal["circuitBreakerReason"] = circuit_breaker_reason

    return deal
