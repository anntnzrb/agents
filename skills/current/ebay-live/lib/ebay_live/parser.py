"""Parse current eBay cards and reject unrecognized empty pages."""

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from selectolax.lexbor import LexborHTMLParser

from .models import EbayBlockedError, Listing

if TYPE_CHECKING:
    from selectolax.lexbor import LexborNode

MONEY = re.compile(r"(?:US\s*)?\$\s*([\d,]+(?:\.\d{1,2})?)")
CONDITION = re.compile(
    r"""
    Brand[ ]New | New(?:[ ]\(Other\)(?::?[ ]see[ ]details)?)? |
    Open[ ]Box | Pre-Owned | Used |
    (?:Certified|Excellent|Very[ ]Good|Good|Seller|Manufacturer)
    (?:[ ]-[ ]|[ ])Refurbished |
    Refurbished | For[ ]parts[ ]or[ ]not[ ]working | Parts[ ]Only
    """,
    re.IGNORECASE | re.VERBOSE,
)
SELLER = re.compile(r"(.+?)\s+([\d.]+)%\s+positive\s*\(([\d,.]+[KMkm]?)\)")


def text(node: LexborNode, selector: str) -> str | None:
    """Read visible selector text with normalized whitespace."""
    match = node.css_first(selector)
    if match is None:
        return None
    return " ".join(match.text(separator=" ", strip=True).split()) or None


def money(value: str | None) -> float | None:
    """Read a USD amount without mistaking bids or dates for prices."""
    match = MONEY.search(value or "")
    return float(match[1].replace(",", "")) if match else None


def count(value: str) -> int:
    """Expand feedback abbreviations such as 6.5K."""
    cleaned = value.replace(",", "").upper()
    factor = 1000 if cleaned.endswith("K") else 1000000 if cleaned.endswith("M") else 1
    return int(float(cleaned.rstrip("KM")) * factor)


def parse_card(card: LexborNode) -> Listing | None:
    """Extract one real listing, excluding eBay's promotional placeholders."""
    link = card.css_first(
        'a.s-card__link[href*="/itm/"], a.s-item__link[href*="/itm/"]'
    )
    title = text(card, ".s-card__title, .s-item__title")
    match = re.search(
        r"/itm/(?:[^/?]+/)?(\d+)(?:[/?]|$)",
        (link.attributes.get("href") or "") if link else "",
    )
    if (
        not match
        or not title
        or match[1] == "123456"
        or title.startswith("Shop on eBay")
    ):
        return None
    title = title.replace("Opens in a new window or tab", "").strip()
    title = re.sub(r"^New Listing\s+", "", title, flags=re.IGNORECASE)
    rows = [
        n.text(separator=" ", strip=True)
        for n in card.css(".s-card__attribute-row, .s-item__details")
    ]
    attrs = " ".join(rows)
    prices = [
        m[1] for m in MONEY.finditer(text(card, ".s-card__price, .s-item__price") or "")
    ]
    price = float(prices[0].replace(",", "")) if prices else None
    price_max = float(prices[1].replace(",", "")) if len(prices) > 1 else None
    shipping = next(
        (r for r in rows if re.search(r"delivery|shipping", r, re.IGNORECASE)), ""
    )
    shipping_cost = (
        0.0
        if re.search(r"free (delivery|shipping)", shipping, re.IGNORECASE)
        else money(shipping)
    )
    seller = next(
        (
            seller_match
            for row in rows
            if (seller_match := SELLER.fullmatch(row)) is not None
        ),
        None,
    )
    bids = re.search(r"([\d,]+) bids?\b", attrs, re.IGNORECASE)
    formats: list[str] = []
    if bids or "auction" in attrs.casefold():
        formats.append("auction")
    if "buy it now" in attrs.casefold():
        formats.append("buy_it_now")
    if "best offer" in attrs.casefold():
        formats.append("best_offer")
    location = next(
        (r.removeprefix("Located in ") for r in rows if r.startswith("Located in ")),
        None,
    )
    condition = next(
        (
            value
            for node in card.css(".s-card__subtitle, .SECONDARY_INFO")
            if CONDITION.fullmatch(
                value := " ".join(node.text(separator=" ", strip=True).split())
            )
        ),
        None,
    )
    return Listing(
        item_id=match[1],
        title=title,
        url=f"https://www.ebay.com/itm/{match[1]}",
        price=price,
        price_max=price_max,
        currency="USD" if prices else None,
        shipping_cost=shipping_cost,
        condition=condition,
        buying_format=tuple(formats),
        bid_count=int(bids[1].replace(",", "")) if bids else None,
        time_left=text(card, ".s-card__time-left, .s-item__time-left"),
        time_end=text(card, ".s-card__time-end"),
        seller_name=seller[1].strip() if seller else None,
        seller_feedback_pct=float(seller[2]) if seller else None,
        seller_feedback_count=count(seller[3]) if seller else None,
        location=location,
    )


@dataclass(frozen=True, slots=True)
class SearchPage:
    """Exact river listings and the number of excluded expanded matches."""

    results: list[Listing]
    rewrite_excluded_count: int


def parse_search_page(html: str) -> SearchPage:
    """Read direct river children, stopping exact matches at the rewrite marker."""
    tree = LexborHTMLParser(html)
    results: list[Listing] = []
    excluded = 0
    rewritten = False
    for river in tree.css("ul.srp-results"):
        for node in river.iter():
            classes = (node.attributes.get("class") or "").split()
            if "srp-river-answer--REWRITE_START" in classes:
                rewritten = True
            if node.tag != "li" or not {"s-card", "s-item"}.intersection(classes):
                continue
            result = parse_card(node)
            if result is None:
                continue
            if rewritten:
                excluded += 1
            else:
                results.append(result)
    for node in tree.css("script, style"):
        node.decompose()
    if (
        not results
        and not rewritten
        and not re.search(
            r"no exact matches|0 results for|no results found",
            tree.text(),
            re.IGNORECASE,
        )
    ):
        raise EbayBlockedError(
            "eBay search has no real cards or explicit no-match marker"
        )
    return SearchPage(results, excluded)


def parse_search_results(html: str) -> list[Listing]:
    """Return only exact river matches, excluding carousels and expanded matches."""
    return parse_search_page(html).results
