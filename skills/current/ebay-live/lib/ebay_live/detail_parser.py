"""Extract item-page DOM and Product JSON-LD evidence."""

import json
import re
from contextlib import suppress
from typing import TYPE_CHECKING, TypeIs, cast

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

from selectolax.lexbor import LexborHTMLParser

from .models import EbayLiveError, ItemDetail
from .parser import money, text


def is_object(value: object) -> TypeIs[dict[str, object]]:
    """Narrow a decoded JSON object at the external boundary."""
    return isinstance(value, dict)


def is_list(value: object) -> TypeIs[list[object]]:
    """Narrow a decoded JSON array at the external boundary."""
    return isinstance(value, list)


def load_json(value: str) -> object:
    """Decode JSON without propagating untyped SDK values."""
    loads: Callable[[str], object] = json.loads
    return cast("object", loads(value))


def products(value: object) -> Iterator[dict[str, object]]:
    """Find Product nodes in direct blocks, arrays, or JSON-LD graphs."""
    if is_object(value):
        kind = value.get("@type")
        if kind == "Product" or (is_list(kind) and "Product" in kind):
            yield value
        yield from products(value.get("@graph"))
    elif is_list(value):
        for entry in value:
            yield from products(entry)


def string(value: object) -> str | None:
    """Read a scalar string from structured data."""
    return value if isinstance(value, str) else None


def shipping_rate(offer: dict[str, object]) -> float | None:
    """Read a same-currency JSON-LD rate when shipping DOM is absent."""
    shipping = offer.get("shippingDetails")
    if is_list(shipping):
        shipping = next(iter(shipping), None)
    if not is_object(shipping):
        return None
    rate = shipping.get("shippingRate")
    if not is_object(rate) or rate.get("currency") != offer.get("priceCurrency"):
        return None
    value = rate.get("value")
    if isinstance(value, (str, int, float)):
        with suppress(ValueError):
            return float(value)
    return None


def parse_item_detail(html: str) -> ItemDetail:  # noqa: C901 - flat DOM and JSON-LD extraction.
    """Parse detail evidence and fail when no item is recognizable."""
    tree = LexborHTMLParser(html)
    root = tree.root
    if root is None:
        raise EbayLiveError("empty item page")
    product: dict[str, object] = {}
    for node in tree.css('script[type="application/ld+json"]'):
        try:
            found = next(products(load_json(node.text())), None)
        except json.JSONDecodeError:
            continue
        if found is not None:
            product = found
            break
    title = text(root, "h1.x-item-title__mainTitle") or string(product.get("name"))
    if not title:
        raise EbayLiveError("eBay item page has no title or Product JSON-LD")
    raw_offer = product.get("offers")
    if is_list(raw_offer):
        raw_offer = next(iter(raw_offer), None)
    offer = raw_offer if is_object(raw_offer) else {}
    price = money(text(root, ".x-price-primary"))
    raw_price = offer.get("price")
    if price is None and isinstance(raw_price, (str, int, float)):
        with suppress(ValueError):
            price = float(raw_price)
    brand = product.get("brand")
    brand_name = string(brand.get("name")) if is_object(brand) else string(brand)
    specifics: dict[str, str] = {}
    for section in tree.css(".ux-layout-section-module-evo"):
        if not section.text(strip=True).startswith("Item specifics"):
            continue
        for row in section.css(".ux-labels-values, .ux-layout-section-evo__col"):
            label = text(row, ".ux-labels-values__labels")
            value = text(row, ".ux-labels-values__values")
            if label and value:
                specifics[label.rstrip(":")] = value
    shipping = text(root, ".ux-labels-values--shipping .ux-labels-values__values")
    shipping_cost = (
        0.0 if re.search(r"free", shipping or "", re.IGNORECASE) else money(shipping)
    )
    if shipping is None:
        shipping_cost = shipping_rate(offer)
    bids = re.search(r"([\d,]+)", text(root, ".x-bid-count") or "")
    return ItemDetail(
        title=title,
        price=price,
        currency=string(offer.get("priceCurrency")),
        condition=text(root, ".x-item-condition-text .ux-textspans")
        or text(root, ".x-item-condition-text .clipped")
        or string(offer.get("itemCondition")),
        bid_count=int(bids[1].replace(",", "")) if bids else None,
        time_left=text(root, ".ux-timer"),
        seller_name=text(root, ".x-sellercard-atf__about-seller-item--seller-name"),
        seller_feedback_text=text(root, ".x-sellercard-atf__data-item"),
        returns=text(root, ".ux-labels-values--returns .ux-labels-values__values"),
        shipping_text=shipping,
        shipping_cost=shipping_cost,
        brand=brand_name or specifics.get("Brand"),
        model=string(product.get("model")) or specifics.get("Model"),
        gtin=string(product.get("gtin13"))
        or string(product.get("gtin"))
        or string(product.get("gtin12"))
        or specifics.get("UPC"),
        mpn=string(product.get("mpn")) or specifics.get("MPN"),
        availability=string(offer.get("availability")),
        item_specifics=specifics,
    )
