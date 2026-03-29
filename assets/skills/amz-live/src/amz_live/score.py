from __future__ import annotations

import re
from decimal import Decimal
from dataclasses import dataclass
from typing import Literal, TypedDict

from .models import ProductDetail, SearchResult

ScoringMode = Literal["agent_value"]

_GENERIC_BRAND_TOKENS = {
    "usb",
    "type",
    "cable",
    "charger",
    "adapter",
    "cord",
    "charging",
    "fast",
    "nylon",
    "braided",
}


class ResultScorePayload(TypedDict):
    score: float
    reasons: list[str]
    signal_scores: dict[str, float]
    brand_source: str | None


@dataclass(frozen=True, slots=True)
class ResultScore:
    score: float
    reasons: tuple[str, ...]
    signal_scores: dict[str, float]
    brand_source: str | None

    def to_dict(self) -> ResultScorePayload:
        return {
            "score": self.score,
            "reasons": list(self.reasons),
            "signal_scores": self.signal_scores,
            "brand_source": self.brand_source,
        }


def score_results(
    results: list[SearchResult],
    *,
    query: str | None = None,
    details_by_asin: dict[str, ProductDetail] | None = None,
) -> tuple[list[SearchResult], dict[str, ResultScore]]:
    details_by_asin = details_by_asin or {}
    priced = [result.price for result in results if result.price is not None]
    min_price = min(priced) if priced else None
    max_price = max(priced) if priced else None

    scored: list[tuple[SearchResult, ResultScore, int]] = []
    for index, result in enumerate(results):
        detail = details_by_asin.get(result.asin)
        result_score = _score_result(
            result,
            query=query,
            detail=detail,
            min_price=min_price,
            max_price=max_price,
        )
        scored.append((result, result_score, index))

    scored.sort(
        key=lambda item: (
            -item[1].score,
            float(item[0].price) if item[0].price is not None else float("inf"),
            -(float(item[0].rating) if item[0].rating is not None else -1),
            -(item[0].review_count or -1),
            item[2],
        )
    )
    return [item[0] for item in scored], {item[0].asin: item[1] for item in scored}


def _score_result(
    result: SearchResult,
    *,
    query: str | None,
    detail: ProductDetail | None,
    min_price: Decimal | None,
    max_price: Decimal | None,
) -> ResultScore:
    signals: dict[str, float] = {}
    reasons: list[str] = []

    signals["merchant_trust"] = _score_merchant_trust(detail)
    merchant_reason = _merchant_reason(detail)
    if merchant_reason is not None:
        reasons.append(merchant_reason)

    signals["rating"] = _score_rating(result)
    if result.rating is not None:
        reasons.append(f"rating {float(result.rating):.1f}")

    signals["review_count"] = _score_review_count(result)
    if result.review_count is not None:
        reasons.append(f"{result.review_count} reviews")

    signals["price_value"] = _score_price(result, min_price=min_price, max_price=max_price)
    if result.price is not None and min_price is not None and result.price == min_price:
        reasons.append("lowest price in filtered set")

    signals["badge"] = _score_badges(result)
    if signals["badge"] > 0 and result.badges:
        reasons.append(", ".join(result.badges[:2]))

    brand, brand_source = _detect_brand(result, detail)
    signals["brand"] = _score_brand(result, brand=brand)
    if brand:
        reasons.append(f"brand {brand}")

    signals["spec_trust"] = _score_spec_trust(result, detail=detail)
    if signals["spec_trust"] > 0:
        reasons.append("certified/trust wording")

    signals["availability"] = _score_availability(detail)
    if signals["availability"] > 0:
        reasons.append("in stock")

    signals["delivery"] = 2.0 if detail and detail.delivery_text else 0.0
    if signals["delivery"] > 0:
        reasons.append("delivery shown")

    signals["connector_match"] = _score_connector_match(result, query=query)
    if signals["connector_match"] < 0:
        reasons.append("connector mismatch vs query")
    elif signals["connector_match"] > 0:
        reasons.append("connector match vs query")

    score = round(min(100.0, max(0.0, sum(signals.values()))), 2)
    return ResultScore(
        score=score,
        reasons=tuple(reasons[:5]),
        signal_scores={key: round(value, 2) for key, value in signals.items()},
        brand_source=brand_source,
    )


def _score_rating(result: SearchResult) -> float:
    rating = float(result.rating) if result.rating is not None else None
    if rating is None:
        return -25.0
    if rating >= 4.7:
        return 22.0
    if rating >= 4.6:
        return 19.0
    if rating >= 4.5:
        return 16.0
    if rating >= 4.4:
        return 10.0
    if rating >= 4.3:
        return 4.0
    return -20.0


def _score_review_count(result: SearchResult) -> float:
    count = result.review_count
    if count is None:
        return -10.0
    if count >= 10_000:
        return 18.0
    if count >= 3_000:
        return 14.0
    if count >= 1_000:
        return 10.0
    if count >= 300:
        return 6.0
    if count >= 100:
        return 2.0
    return -8.0


def _score_price(result: SearchResult, *, min_price: Decimal | None, max_price: Decimal | None) -> float:
    if result.price is None:
        return -20.0
    if min_price is None or max_price is None or min_price == max_price:
        return 12.5
    return 25.0 * float(max_price - result.price) / float(max_price - min_price)


def _score_badges(result: SearchResult) -> float:
    score = 0.0
    for badge in result.badges:
        lowered = badge.casefold()
        if "best seller" in lowered:
            score += 4.0
        elif "amazon's choice" in lowered or "amazons choice" in lowered:
            score += 4.0
        elif "top rated" in lowered:
            score += 2.0
    return min(6.0, score)


def _detect_brand(
    result: SearchResult,
    detail: ProductDetail | None,
) -> tuple[str | None, str | None]:
    if detail and detail.brand:
        return detail.brand, "details"

    words = result.title.replace(",", " ").split()
    if not words:
        return None, None
    for count in range(3, 0, -1):
        candidate_words = words[:count]
        if any(word.casefold() in _GENERIC_BRAND_TOKENS for word in candidate_words):
            continue
        return " ".join(candidate_words), "title"
    return None, None


def _score_brand(result: SearchResult, *, brand: str | None) -> float:
    if brand is None:
        return -8.0
    if brand.casefold() == "amazon basics":
        return 14.0
    if brand.casefold() == result.title.casefold():
        return -8.0
    return 6.0


def _score_spec_trust(result: SearchResult, *, detail: ProductDetail | None) -> float:
    haystack = " ".join(
        [
            result.title,
            *(detail.bullet_points if detail else ()),
        ]
    ).casefold()
    if "usb-if certified" in haystack:
        return 4.0
    if "certified" in haystack:
        return 2.0
    return 0.0


def _score_availability(detail: ProductDetail | None) -> float:
    if detail is None or detail.availability_text is None:
        return 0.0
    lowered = detail.availability_text.casefold()
    if "in stock" in lowered:
        return 4.0
    if "currently unavailable" in lowered or "out of stock" in lowered:
        return -20.0
    return 0.0


def _score_merchant_trust(detail: ProductDetail | None) -> float:
    if detail is None:
        return 0.0

    merchant_fields = tuple(
        value.casefold() for value in (detail.ships_from, detail.sold_by) if value is not None
    )
    if not merchant_fields:
        return 0.0
    if any(value == "amazon.com" for value in merchant_fields):
        if all(value == "amazon.com" for value in merchant_fields):
            return 8.0
        return 5.0
    return 2.0


def _merchant_reason(detail: ProductDetail | None) -> str | None:
    if detail is None:
        return None
    if detail.sold_by and detail.sold_by.casefold() == "amazon.com":
        return "merchant Amazon.com"
    if detail.ships_from and detail.ships_from.casefold() == "amazon.com":
        return "ships from Amazon.com"
    if detail.sold_by:
        return f"merchant {detail.sold_by}"
    if detail.ships_from:
        return f"ships from {detail.ships_from}"
    return None


def _score_connector_match(result: SearchResult, *, query: str | None) -> float:
    if query is None:
        return 0.0

    query_connectors = _extract_connectors(query)
    title_connectors = _extract_connectors(result.title)
    if not query_connectors or not title_connectors:
        return 0.0
    if query_connectors == title_connectors:
        return 6.0
    if len(query_connectors) == len(title_connectors):
        return -12.0
    return -6.0


def _extract_connectors(text: str) -> tuple[str, ...]:
    normalized = text.casefold().replace("-", " ")
    connectors: list[str] = []
    patterns = (
        ("usb c", r"usb\s*c"),
        ("usb a", r"usb\s*a"),
        ("micro usb", r"micro\s*usb"),
        ("lightning", r"lightning"),
    )
    for label, pattern in patterns:
        connectors.extend(label for _ in re.finditer(pattern, normalized))
    return tuple(connectors)
