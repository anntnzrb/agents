"""Deterministic relative value ranking with visible caveats."""

import math
import re
from statistics import median
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import Listing


PRICE_OUTLIER_RATIO = 0.4
ACCESSORY = (
    r"\b(?:hinge|earpads?|headband|replacement|cable|shell|board|touchpad|bag)\b"
    r"|\bcase only\b"
)


def query_match(title: str, keywords: str) -> float:
    """Return the fraction of unique normalized query tokens in the title."""
    tokens = set(re.findall(r"[a-z0-9]+", keywords.casefold()))
    title_tokens = set(re.findall(r"[a-z0-9]+", title.casefold()))
    return len(tokens & title_tokens) / len(tokens) if tokens else 0.0


def rank_results(  # noqa: C901 - independent ranking factors.
    results: list[Listing], keywords: str, *, buy_now: bool
) -> list[dict[str, object]]:
    """Rank known totals within each currency; explain missing or noisy evidence."""
    relevant = [r for r in results if query_match(r.title, keywords) == 1]
    medians = {
        currency: median(
            r.total_cost
            for r in relevant
            if r.currency == currency and r.total_cost is not None
        )
        for currency in {r.currency for r in relevant if r.total_cost is not None}
    }
    ranked: list[tuple[float, Listing, list[str]]] = []
    for result in results:
        match = query_match(result.title, keywords)
        value = 0.0
        reasons: list[str] = []
        mid = medians.get(result.currency)
        total = result.total_cost
        if mid is not None and mid > 0 and total is not None:
            if total < PRICE_OUTLIER_RATIO * mid:
                value -= 40
                reasons.append(
                    "likely accessory/part price outlier; below 40% of relevant median"
                )
            else:
                value += max(0.0, min(50.0, 25 * (2 - total / mid))) * match
            reasons.append(
                f"total {total:.2f} versus set median {mid:.2f} {result.currency}"
            )
        else:
            reasons.append("unknown total cost; no price credit")
        if result.seller_feedback_pct is not None:
            value += max(0, min(20, (result.seller_feedback_pct - 90) * 2))
            reasons.append(f"seller {result.seller_feedback_pct:g}% positive")
        if result.seller_feedback_count is not None:
            value += min(10, math.log10(result.seller_feedback_count + 1) * 2.5)
            reasons.append(f"seller feedback count {result.seller_feedback_count}")
        condition = (result.condition or "").casefold()
        value += (
            0
            if "parts" in condition
            else 12
            if "new" in condition
            else 8
            if "refurb" in condition
            else 4
            if "owned" in condition or "used" in condition
            else 0
        )
        reasons.append(f"condition: {result.condition or 'unknown'}")
        if result.shipping_cost == 0:
            value += 5
            reasons.append("free shipping")
        title = result.title.casefold()
        if match < 1:
            value -= 30 * (1 - match)
            reasons.append(f"query token match {match:.0%}")
        if re.search(
            ACCESSORY,
            title,
        ) and not re.search(
            ACCESSORY,
            keywords,
            re.IGNORECASE,
        ):
            value -= 40
            reasons.append("possible accessory; refine include or exclude terms")
        damage = r"\b(?:broke[n]?|repair|parts|not working|defective)\b"
        if re.search(damage, title) and not re.search(damage, keywords, re.IGNORECASE):
            value -= 25
            reasons.append("possible damaged item; refine include or exclude terms")
        if "auction" in result.buying_format:
            reasons.append("auction price is a current bid, not a purchase price")
            if buy_now and re.search(r"\d+d|\d+h", result.time_left or ""):
                reasons.append("long auction wait conflicts with buy-now intent")
        ranked.append((round(max(0, min(100, value)), 2), result, reasons))
    ranked.sort(key=lambda row: (-row[0], row[1].item_id))
    return [
        {
            **result.to_dict(),
            "query_match": query_match(result.title, keywords),
            "score": score,
            "reasons": reasons,
            "rank": rank,
        }
        for rank, (score, result, reasons) in enumerate(ranked, 1)
    ]
