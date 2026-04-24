from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin

from selectolax.parser import HTMLParser, Node

from .models import SearchResult

_CARD_SELECTOR = '[data-component-type="s-search-result"][data-asin]'
_PRICE_SELECTORS = (
    '[data-cy="price-recipe"] .a-price[data-a-size="xl"] .a-offscreen',
    '[data-cy="price-recipe"] .a-price .a-offscreen',
    '.a-price[data-a-size="xl"] .a-offscreen',
)
_RATING_SELECTORS = (
    '[data-cy="reviews-block"] .a-icon-alt',
    '[data-cy="reviews-block"] a[aria-label*="out of 5 stars"]',
    '[data-cy="reviews-block"] .a-size-small.a-color-base',
)
_REVIEW_COUNT_SELECTORS = (
    '[data-cy="reviews-block"] a[aria-label*="ratings"]',
    '[data-cy="reviews-block"] a[aria-label$=" rating"]',
    '[data-cy="reviews-block"] [aria-label*="ratings"]',
    '[data-cy="reviews-block"] .s-underline-text',
)
_BADGE_SELECTORS = (
    ".rio-badge-label [aria-label]",
    ".rio-badge-label",
    '[data-cy="reviews-block"] .puis-bold-weight-text',
)


def parse_search_results(
    html: str,
    *,
    base_url: str = "https://www.amazon.com",
) -> list[SearchResult]:
    tree = HTMLParser(html)
    return [
        result
        for node in tree.css(_CARD_SELECTOR)
        if (result := _parse_result_card(node, base_url=base_url)) is not None
    ]


def _parse_result_card(node: Node, *, base_url: str) -> SearchResult | None:
    asin = _clean_text(node.attributes.get("data-asin", ""))
    if not asin:
        return None

    title = _first_text(node, ('[data-cy="title-recipe"] h2 span', "h2 span", "h2"))
    href = _first_attr(
        node,
        ('[data-cy="title-recipe"] a', "h2 a", "a.a-link-normal.s-no-outline"),
        "href",
    )
    if not title or not href:
        return None

    return SearchResult(
        asin=asin,
        title=title,
        url=urljoin(base_url, href),
        price=_extract_price(node),
        rating=_extract_rating(node),
        review_count=_extract_review_count(node),
        badges=_extract_badges(node),
    )


def _extract_price(node: Node) -> Decimal | None:
    for selector in _PRICE_SELECTORS:
        for price_node in node.css(selector):
            value = _parse_decimal(price_node.text(separator=" ", strip=True))
            if value is not None:
                return value
    return None


def _extract_rating(node: Node) -> Decimal | None:
    for selector in _RATING_SELECTORS:
        for rating_node in node.css(selector):
            raw = rating_node.attributes.get("aria-label") or rating_node.text(
                separator=" ",
                strip=True,
            )
            value = _parse_rating(raw)
            if value is not None:
                return value
    return None


def _extract_review_count(node: Node) -> int | None:
    for selector in _REVIEW_COUNT_SELECTORS:
        for review_node in node.css(selector):
            raw = review_node.attributes.get("aria-label") or review_node.text(
                separator=" ",
                strip=True,
            )
            value = _parse_review_count(raw)
            if value is not None:
                return value
    return None


def _extract_badges(node: Node) -> tuple[str, ...]:
    seen: set[str] = set()
    badges: list[str] = []

    for selector in _BADGE_SELECTORS:
        for badge_node in node.css(selector):
            raw = badge_node.attributes.get("aria-label") or badge_node.text(
                separator=" ",
                strip=True,
            )
            badge = _clean_text(raw)
            if not badge or badge in seen:
                continue
            seen.add(badge)
            badges.append(badge)

    return tuple(badges)


def _first_text(node: Node, selectors: tuple[str, ...]) -> str | None:
    for selector in selectors:
        match = node.css_first(selector)
        if match is None:
            continue
        text = _clean_text(match.text(separator=" ", strip=True))
        if text:
            return text
    return None


def _first_attr(node: Node, selectors: tuple[str, ...], attr: str) -> str | None:
    for selector in selectors:
        for match in node.css(selector):
            value = _clean_text(match.attributes.get(attr, ""))
            if not value:
                continue
            if attr == "href" and _is_placeholder_href(value):
                continue
            return value
    return None


def _is_placeholder_href(value: str) -> bool:
    lowered = value.casefold()
    return lowered == "#" or lowered.startswith("javascript:")


def _clean_text(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(value.split())


def _parse_decimal(value: str) -> Decimal | None:
    match = re.search(r"(\d[\d,]*\.\d+|\d[\d,]*)", value)
    if match is None:
        return None

    normalized = match.group(1).replace(",", "")
    try:
        return Decimal(normalized)
    except InvalidOperation:
        return None


def _parse_rating(value: str) -> Decimal | None:
    return _parse_decimal(value)


def _parse_review_count(value: str) -> int | None:
    lowered = value.casefold()
    if "out of 5 stars" in lowered:
        return None

    aria_match = re.search(r"([0-9][0-9,]*)\s+ratings?\b", value, re.IGNORECASE)
    if aria_match is not None:
        return int(aria_match.group(1).replace(",", ""))

    compact_match = re.search(r"(\d+(?:\.\d+)?)\s*([KMB])\b", value, re.IGNORECASE)
    if compact_match is not None:
        number = Decimal(compact_match.group(1))
        multiplier = {
            "k": 1_000,
            "m": 1_000_000,
            "b": 1_000_000_000,
        }[compact_match.group(2).casefold()]
        return int(number * multiplier)

    digits_match = re.search(r"([0-9][0-9,]*)", value)
    if digits_match is not None:
        return int(digits_match.group(1).replace(",", ""))

    return None
