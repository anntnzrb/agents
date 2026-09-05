"""Typed domain models for Amazon live search."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from decimal import Decimal


class AmazonLiveSearchError(RuntimeError):
    """Base error for the package."""


class AmazonAntiBotError(AmazonLiveSearchError):
    """Raised when Amazon serves a captcha, robot check, or related block page."""


class AmazonClientError(AmazonLiveSearchError):
    """Raised for network and non-bot HTTP failures."""


class ProductDetailPayload(TypedDict):
    """Serialized product-detail payload."""

    brand: str | None
    availability_text: str | None
    delivery_text: str | None
    ships_from: str | None
    sold_by: str | None
    bullet_points: list[str]


class SearchResultPayload(TypedDict):
    """Serialized search-result payload."""

    asin: str
    title: str
    url: str
    price: float | None
    rating: float | None
    review_count: int | None
    badges: list[str]


@dataclass(frozen=True, slots=True)
class SearchQuery:
    """Amazon search query inputs."""

    keywords: str
    page: int = 1
    amazon_sort: str | None = None
    zip_code: str | None = None

    def __post_init__(self) -> None:
        """Validate and normalize query fields."""
        keywords = self.keywords.strip()
        amazon_sort = self.amazon_sort.strip() if self.amazon_sort else None
        zip_code = self.zip_code.strip() if self.zip_code else None

        if not keywords:
            msg = "keywords must not be empty"
            raise ValueError(msg)
        if self.page < 1:
            msg = "page must be >= 1"
            raise ValueError(msg)

        object.__setattr__(self, "keywords", keywords)
        object.__setattr__(self, "amazon_sort", amazon_sort)
        object.__setattr__(self, "zip_code", zip_code)

    def to_params(self) -> dict[str, str]:
        """Render query fields as Amazon search params."""
        params = {"k": self.keywords, "page": str(self.page)}
        if self.amazon_sort:
            params["s"] = self.amazon_sort
        if self.zip_code:
            params["rh"] = f"p_47:{self.zip_code}"
        return params


@dataclass(frozen=True, slots=True)
class ProductDetail:
    """Normalized subset of Amazon product-detail page data."""

    brand: str | None = None
    availability_text: str | None = None
    delivery_text: str | None = None
    ships_from: str | None = None
    sold_by: str | None = None
    bullet_points: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> ProductDetailPayload:
        """Serialize to a plain payload dict."""
        return {
            "brand": self.brand,
            "availability_text": self.availability_text,
            "delivery_text": self.delivery_text,
            "ships_from": self.ships_from,
            "sold_by": self.sold_by,
            "bullet_points": list(self.bullet_points),
        }


@dataclass(frozen=True, slots=True)
class SearchResult:
    """Normalized subset of Amazon search-result card data."""

    asin: str
    title: str
    url: str
    price: Decimal | None = None
    rating: Decimal | None = None
    review_count: int | None = None
    badges: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> SearchResultPayload:
        """Serialize to a plain payload dict."""
        return {
            "asin": self.asin,
            "title": self.title,
            "url": self.url,
            "price": float(self.price) if self.price is not None else None,
            "rating": float(self.rating) if self.rating is not None else None,
            "review_count": self.review_count,
            "badges": list(self.badges),
        }
