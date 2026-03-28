from __future__ import annotations

from collections.abc import Iterable, Sequence
from decimal import Decimal

from .models import SearchResult


def filter_results(
    results: Iterable[SearchResult],
    *,
    min_rating: float | Decimal | None = None,
    max_price: float | Decimal | None = None,
    badge: str | None = None,
    title_contains: str | None = None,
    include: Sequence[str] | None = None,
    exclude: Sequence[str] | None = None,
    limit: int | None = None,
) -> list[SearchResult]:
    if limit is not None and limit < 0:
        raise ValueError("limit must be >= 0")

    min_rating_value = _coerce_decimal(min_rating)
    max_price_value = _coerce_decimal(max_price)
    badge_value = _normalize_term(badge)
    title_value = _normalize_term(title_contains)
    include_terms = tuple(filter(None, (_normalize_term(term) for term in include or ())))
    exclude_terms = tuple(filter(None, (_normalize_term(term) for term in exclude or ())))

    filtered: list[SearchResult] = []
    for result in results:
        if not _matches(
            result,
            min_rating=min_rating_value,
            max_price=max_price_value,
            badge=badge_value,
            title_contains=title_value,
            include=include_terms,
            exclude=exclude_terms,
        ):
            continue
        filtered.append(result)
        if limit is not None and len(filtered) >= limit:
            break

    return filtered


def _matches(
    result: SearchResult,
    *,
    min_rating: Decimal | None,
    max_price: Decimal | None,
    badge: str | None,
    title_contains: str | None,
    include: Sequence[str],
    exclude: Sequence[str],
) -> bool:
    title = result.title.casefold()
    searchable_text = " ".join((result.title, *result.badges)).casefold()

    if min_rating is not None and (result.rating is None or result.rating < min_rating):
        return False
    if max_price is not None and (result.price is None or result.price > max_price):
        return False
    if badge is not None and not any(badge in item.casefold() for item in result.badges):
        return False
    if title_contains is not None and title_contains not in title:
        return False
    if include and not all(term in searchable_text for term in include):
        return False
    if exclude and any(term in searchable_text for term in exclude):
        return False
    return True


def _coerce_decimal(value: float | Decimal | None) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _normalize_term(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().casefold()
    return normalized or None
