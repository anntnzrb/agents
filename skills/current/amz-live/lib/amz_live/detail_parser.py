"""Product-detail page parsing for Amazon live search."""

from __future__ import annotations

import re

from selectolax.parser import HTMLParser

from .models import ProductDetail

_MIN_TABLE_CELLS = 2


def parse_product_detail(html: str) -> ProductDetail:
    """Parse a product-detail page into normalized data."""
    tree = HTMLParser(html)
    merchant_fields = _extract_merchant_fields(tree)
    return ProductDetail(
        brand=_extract_brand(tree),
        availability_text=_extract_availability_text(tree),
        delivery_text=_extract_text(
            tree,
            (
                "#deliveryBlockMessage",
                "#mir-layout-DELIVERY_BLOCK-slot-PRIMARY_DELIVERY_MESSAGE_LARGE",
            ),
        ),
        ships_from=merchant_fields.get("ships from"),
        sold_by=merchant_fields.get("sold by"),
        bullet_points=_extract_bullet_points(tree),
    )


def _extract_brand(tree: HTMLParser) -> str | None:
    for row in tree.css("#productOverview_feature_div tr"):
        cells = [_clean_text(cell.text(separator=" ", strip=True)) for cell in row.css("td")]
        if len(cells) >= _MIN_TABLE_CELLS and cells[0].casefold() == "brand":
            return cells[1]

    byline = _extract_text(tree, ("#bylineInfo",))
    if byline is None:
        return None
    return re.sub(r"^Visit the\s+|\s+Store$", "", byline).strip() or None


def _extract_availability_text(tree: HTMLParser) -> str | None:
    availability = _extract_text(tree, ("#availability",))
    if availability is None:
        return None
    return availability.split(" {", 1)[0]


def _extract_bullet_points(tree: HTMLParser, *, limit: int = 5) -> tuple[str, ...]:
    seen: set[str] = set()
    items: list[str] = []
    for node in tree.css("#feature-bullets ul li span.a-list-item"):
        text = _clean_text(node.text(separator=" ", strip=True))
        if not text or text in seen:
            continue
        seen.add(text)
        items.append(text)
        if len(items) >= limit:
            break
    return tuple(items)


def _extract_merchant_fields(tree: HTMLParser) -> dict[str, str]:
    fields: dict[str, str] = {}
    for row in tree.css("#tabular-buybox .tabular-buybox-container"):
        texts = [
            _clean_text(node.text(separator=" ", strip=True))
            for node in row.css(".tabular-buybox-text")
        ]
        texts = [text for text in texts if text]
        if len(texts) < _MIN_TABLE_CELLS:
            continue
        label = texts[0].casefold().rstrip(":")
        if label in {"ships from", "sold by"}:
            fields[label] = texts[-1]
    return fields


def _extract_text(tree: HTMLParser, selectors: tuple[str, ...]) -> str | None:
    for selector in selectors:
        node = tree.css_first(selector)
        if node is None:
            continue
        text = _clean_text(node.text(separator=" ", strip=True))
        if text:
            return text
    return None


def _clean_text(value: str) -> str:
    return " ".join(value.split())
