"""Search-results page parsing for Amazon live search."""

import re
from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qs, urljoin, urlparse

from selectolax.lexbor import LexborHTMLParser, LexborNode

from .models import AmazonClientError, SearchPageInfo, SearchResult

_CARD_SELECTOR = '[data-component-type="s-search-result"][data-asin]'
_CURRENT_PRICE = '.a-price:not(.a-text-price):not([data-a-strike="true"])'
_PRICE_SELECTORS = (
    f'[data-cy="price-recipe"] {_CURRENT_PRICE}[data-a-size="xl"] .a-offscreen',
    f'[data-cy="price-recipe"] {_CURRENT_PRICE} .a-offscreen',
    f'{_CURRENT_PRICE}[data-a-size="xl"] .a-offscreen',
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
    ".a-badge-text",
)
_PRIME_OFFER = re.compile(
    r"\b(?:prime (?:exclusive|member price)|exclusive prime)\b",
    re.IGNORECASE,
)
_DEAL_LABEL = re.compile(
    r"\b(?:limited time deal|lightning deal|deal of the day|prime (?:big |day )?deal)\b",
    re.IGNORECASE,
)


def discover_deal_filter(html: str, *, base_url: str) -> tuple[str, str]:
    """Discover an advertised deal refinement without following arbitrary links."""
    tree = LexborHTMLParser(html)
    candidates: list[tuple[str, str]] = []
    origin = urlparse(base_url)
    for link in tree.css("#filter-p_n_deal_type a[href]"):
        target = urlparse(urljoin(base_url, link.attributes.get("href") or ""))
        if (target.scheme, target.netloc, target.path) != (origin.scheme, origin.netloc, "/s"):
            continue
        label = _clean_text(link.text(separator=" ", strip=True))
        refinements = parse_qs(target.query).get("rh", [])
        for refinement in refinements:
            for term in refinement.split(","):
                if re.fullmatch(r"p_n_deal_type:[0-9]+", term) and label:
                    candidates.append((term, label))
    if not candidates:
        raise AmazonClientError("Amazon advertised no usable deal filter for this search")
    for preferred in ("all deals", "all discounts", "today's deals"):
        for item in candidates:
            if item[1].casefold().replace("\u2019", "'") == preferred:
                return item
    return candidates[0]


def parse_search_page(
    html: str, *, base_url: str = "https://www.amazon.com", require_deals: bool = False
) -> tuple[list[SearchResult], SearchPageInfo]:
    """Parse a recognized results page and preserve its observed context."""
    tree = LexborHTMLParser(html)
    root = tree.root
    if root is None:
        raise AmazonClientError("Unrecognized Amazon search page: empty document")
    results = parse_search_results(html, base_url=base_url)
    if not results:
        for element in tree.css("script, style, noscript"):
            element.decompose()
        text = tree.text(separator=" ", strip=True)
        if tree.css(_CARD_SELECTOR) or not re.search(
            r"\b(?:no results for|did not match any products|we couldn't find any results)\b",
            text,
            re.IGNORECASE,
        ):
            raise AmazonClientError(
                "Unrecognized Amazon search page: missing usable cards or a no-results message"
            )
    location = _first_text(root, ("#glow-ingress-line2",)) or None
    if location:
        location = location.replace("\u200c", "").strip()
    refinement = _first_text(root, ('#filter-p_n_deal_type a[aria-current="true"]',)) or None
    if require_deals and results and refinement is None:
        raise AmazonClientError("Amazon did not confirm the requested deal refinement")
    return results, SearchPageInfo(delivery_location=location, deal_refinement=refinement)


def parse_search_results(
    html: str,
    *,
    base_url: str = "https://www.amazon.com",
) -> list[SearchResult]:
    """Parse search-result cards from a search page."""
    tree = LexborHTMLParser(html)
    return [
        result
        for node in tree.css(_CARD_SELECTOR)
        if (result := _parse_result_card(node, base_url=base_url)) is not None
    ]


def _parse_result_card(node: LexborNode, *, base_url: str) -> SearchResult | None:
    asin = _clean_text(node.attributes.get("data-asin", ""))
    if not asin:
        return None

    title = _first_text(
        node,
        (
            '[data-cy="title-recipe"] a h2 span',
            "h2 a span",
            '[data-cy="title-recipe"] h2 span',
            "h2 span",
            "h2",
        ),
    )
    href = _first_attr(
        node,
        ('[data-cy="title-recipe"] a', "h2 a", "a.a-link-normal.s-no-outline"),
        "href",
    )
    if not title or not href:
        return None

    price = _extract_price(node)
    reference_price, reference_label = _extract_reference_price(node)
    discount = None
    if price is not None and reference_price is not None and 0 <= price < reference_price:
        discount = ((reference_price - price) / reference_price * 100).quantize(Decimal("0.01"))
    badges = _extract_badges(node)
    recipe = node.css_first('[data-cy="price-recipe"]', strict=False)
    prime_price = recipe is not None and any(
        _PRIME_OFFER.search(span.text(separator=" ", strip=True))
        for span in recipe.css("span")
        if len(span.css("span")) == 1 and _visible_markup(span)
    )
    return SearchResult(
        asin=asin,
        title=title,
        url=urljoin(base_url, f"/dp/{asin}"),
        price=price,
        rating=_extract_rating(node),
        review_count=_extract_review_count(node),
        badges=badges,
        reference_price=reference_price,
        reference_price_label=reference_label,
        discount_percent=discount,
        prime_exclusive=True
        if prime_price or any(_PRIME_OFFER.search(badge) for badge in badges)
        else None,
        coupon_text=_extract_coupon(node),
        sponsored="/sspa/click" in href
        or node.css_first('[data-component-type="s-sponsored-label-marker"]', strict=False)
        is not None,
    )


def _extract_price(node: LexborNode) -> Decimal | None:
    for selector in _PRICE_SELECTORS:
        for price_node in node.css(selector):
            value = _parse_decimal(price_node.text(separator=" ", strip=True))
            if value is not None:
                return value
    return None


def _extract_reference_price(node: LexborNode) -> tuple[Decimal | None, str | None]:
    selector = '.a-price[data-a-strike="true"] .a-offscreen'
    recipe = node.css_first('[data-cy="price-recipe"]', strict=False)
    reference = (recipe if recipe is not None else node).css_first(selector, strict=False)
    if reference is None:
        return None, None
    price = _parse_decimal(reference.text(separator=" ", strip=True))
    label = None
    parent = reference.parent
    context = parent.parent if parent is not None else None
    if price is not None and context is not None:
        match = re.search(
            r"\b(List Price|List|Typical price|Was|Previously):",
            context.text(separator=" ", strip=True),
            re.IGNORECASE,
        )
        label = match.group(1) if match else None
    return price, label


def _extract_coupon(node: LexborNode) -> str | None:
    return _first_text(
        node,
        (
            '[data-component-type="s-coupon-component"] .s-coupon-unclipped:not(.aok-hidden)',
            '[data-component-type="s-coupon-component"] .s-coupon-clipped:not(.aok-hidden)',
        ),
    )


def _extract_rating(node: LexborNode) -> Decimal | None:
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


def _extract_review_count(node: LexborNode) -> int | None:
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


def _extract_badges(node: LexborNode) -> tuple[str, ...]:
    seen: set[str] = set()
    badges: list[str] = []

    for selector in (*_BADGE_SELECTORS, '[data-cy="price-recipe"] .a-color-price'):
        for badge_node in node.css(selector):
            if not _visible_markup(badge_node):
                continue
            raw = badge_node.attributes.get("aria-label") or badge_node.text(
                separator=" ",
                strip=True,
            )
            badge = _clean_text(raw)
            if selector.endswith(".a-color-price") and not (
                _PRIME_OFFER.search(badge) or _DEAL_LABEL.search(badge)
            ):
                continue
            if not badge or badge == "Ends in" or badge in seen:
                continue
            seen.add(badge)
            badges.append(badge)

    return tuple(badges)


def _visible_markup(node: LexborNode) -> bool:
    """Exclude explicit hidden templates, retaining accessibility price text."""
    current: LexborNode | None = node
    while current is not None:
        attrs = current.attributes
        classes = (attrs.get("class") or "").split()
        if (
            "hidden" in attrs
            or attrs.get("aria-hidden") == "true"
            or any(name in classes for name in ("aok-hidden", "a-hidden"))
        ):
            return False
        current = current.parent
    return True


def _first_text(node: LexborNode, selectors: tuple[str, ...]) -> str | None:
    for selector in selectors:
        match = node.css_first(selector, strict=False)
        if match is None:
            continue
        text = _clean_text(match.text(separator=" ", strip=True))
        if text:
            return text
    return None


def _first_attr(node: LexborNode, selectors: tuple[str, ...], attr: str) -> str | None:
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
