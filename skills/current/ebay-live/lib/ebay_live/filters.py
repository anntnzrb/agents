"""Pure local filters over observed listing evidence."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import Listing


@dataclass(frozen=True, slots=True)
class Filters:
    """Local predicates, applied before ranking and limiting."""

    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    title_contains: str | None = None
    min_seller_feedback: float | None = None
    free_shipping: bool = False
    limit: int | None = None


def filter_results(results: list[Listing], filters: Filters) -> list[Listing]:
    """Require all include terms and reject any exclude term in titles."""
    selected: list[Listing] = []
    for result in results:
        title = result.title.casefold()
        if any(term.casefold() not in title for term in filters.include):
            continue
        if any(term.casefold() in title for term in filters.exclude):
            continue
        if filters.title_contains and filters.title_contains.casefold() not in title:
            continue
        if filters.min_seller_feedback is not None and (
            result.seller_feedback_pct is None
            or result.seller_feedback_pct < filters.min_seller_feedback
        ):
            continue
        if filters.free_shipping and result.shipping_cost != 0:
            continue
        selected.append(result)
    return selected
