"""Protocol layer: loading, enrichment, serialization, and schemas."""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, NotRequired, TypedDict
from urllib.parse import urljoin

import httpx2

if TYPE_CHECKING:
    from collections.abc import Sequence
    from decimal import Decimal

from .client import AmazonSearchClient
from .detail_parser import parse_product_detail
from .filters import filter_results
from .models import (
    AmazonAntiBotError,
    AmazonLiveSearchError,
    ProductDetail,
    ProductDetailPayload,
    SearchPageInfo,
    SearchQuery,
    SearchResult,
    SearchResultPayload,
)
from .parser import parse_search_page
from .score import ResultScore, ResultScorePayload, score_results

PROTOCOL_VERSION = "1"
LLM_JSON_TYPE = "amz-live.search_results"
SCHEMA_TYPE = "amz-live.schema"
SCHEMA_NAME = "amz-live"
_LLM_JSON_REQUIRED_FIELDS = [
    "type",
    "version",
    "ok",
    "source",
    "query",
    "filters",
    "summary",
    "results",
]


class SourcePayload(TypedDict):
    """Result source descriptor."""

    mode: Literal["html", "live"]
    html_path: NotRequired[str]
    checked_at: NotRequired[str]


class QueryPayload(TypedDict):
    """Echoed query parameters."""

    keywords: str
    page: int
    pages: int
    amazon_sort: str | None
    zip_code: str | None
    deals: bool
    deal_refinement: str | None


class FiltersPayload(TypedDict):
    """Applied result filters."""

    min_rating: float | None
    max_price: float | None
    badge: str | None
    title_contains: str | None
    include: list[str]
    exclude: list[str]
    limit: int | None


class SummaryPayload(TypedDict):
    """Result counts summary."""

    raw_result_count: int
    returned_result_count: int
    delivery_location: str | None


class EnrichmentPayload(TypedDict):
    """Detail-enrichment outcome."""

    details: bool
    detail_limit: int | None
    attempted: int
    succeeded: int


class RankedResultScorePayload(ResultScorePayload):
    """Result score with ranking position."""

    rank: int


class SerializedSearchResultPayload(SearchResultPayload, total=False):
    """Serialized result with details and score."""

    details: ProductDetailPayload | None
    score: float
    reasons: list[str]
    signal_scores: dict[str, float]
    brand_source: str | None
    ranking: RankedResultScorePayload


class RankingPayload(TypedDict):
    """Ranking run metadata."""

    mode: Literal["agent_value"]
    scored_count: int
    details_used: int
    limit_applied_after_ranking: bool


class SearchResultsPayload(TypedDict):
    """Top-level LLM JSON envelope."""

    type: str
    version: str
    ok: bool
    source: SourcePayload
    query: QueryPayload
    filters: FiltersPayload
    summary: SummaryPayload
    enrichment: EnrichmentPayload
    results: list[SerializedSearchResultPayload]
    ranking: NotRequired[RankingPayload]
    warnings: NotRequired[list[str]]


def load_results(
    *,
    query: str,
    html_path: str | None,
    page: int,
    pages: int,
    amazon_sort: str | None,
    zip_code: str | None = None,
    deals: bool = False,
    client: AmazonSearchClient | None = None,
) -> list[SearchResult]:
    """Load results from a local HTML file or live search."""
    search_query = SearchQuery(
        query, page=page, amazon_sort=amazon_sort, zip_code=zip_code, deals=deals
    )
    if html_path:
        html = Path(html_path).read_text(encoding="utf-8")
        results, info = parse_search_page(html, require_deals=deals)
        if client is not None:
            client.page_info = info
        return results
    if client is not None:
        return client.search_pages(search_query, pages=pages)
    with AmazonSearchClient() as owned_client:
        return owned_client.search_pages(search_query, pages=pages)


def enrich_results(
    results: Sequence[SearchResult],
    *,
    details: bool,
    detail_limit: int | None,
    client: AmazonSearchClient,
) -> tuple[dict[str, ProductDetail], int]:
    """Fetch product details for filtered results."""
    if not details:
        return {}, 0

    limit = len(results) if detail_limit is None else min(detail_limit, len(results))
    if limit <= 0:
        return {}, 0

    enriched: dict[str, ProductDetail] = {}
    attempted = 0
    for result in results[:limit]:
        attempted += 1
        try:
            html = client.fetch_product_page(urljoin(client.base_url, f"/dp/{result.asin}"))
            enriched[result.asin] = parse_product_detail(html)
        except AmazonAntiBotError:
            break
        except AmazonLiveSearchError, httpx2.HTTPError, OSError, ValueError, TypeError:
            continue
    return enriched, attempted


def search_and_filter(
    *,
    client: AmazonSearchClient,
    query: str,
    html_path: str | None,
    page: int,
    pages: int,
    amazon_sort: str | None,
    zip_code: str | None = None,
    deals: bool = False,
    min_rating: float | Decimal | None = None,
    max_price: float | Decimal | None = None,
    badge: str | None = None,
    title_contains: str | None = None,
    include: Sequence[str] | None = None,
    exclude: Sequence[str] | None = None,
    limit: int | None = None,
    details: bool = False,
    detail_limit: int | None = None,
    scoring: bool = False,
) -> tuple[
    list[SearchResult],
    list[SearchResult],
    dict[str, ProductDetail],
    int,
    dict[str, ResultScore],
]:
    """Run the full load, filter, enrich, and score pipeline."""
    raw_results = load_results(
        query=query,
        html_path=html_path,
        page=page,
        pages=pages,
        amazon_sort=amazon_sort,
        zip_code=zip_code,
        deals=deals,
        client=client,
    )
    filtered_results = filter_results(
        raw_results,
        min_rating=min_rating,
        max_price=max_price,
        badge=badge,
        title_contains=title_contains,
        include=include,
        exclude=exclude,
        limit=None if scoring else limit,
    )
    details_by_asin, attempted = enrich_results(
        filtered_results,
        details=details,
        detail_limit=detail_limit,
        client=client,
    )
    scores_by_asin: dict[str, ResultScore] = {}
    if scoring:
        filtered_results, scores_by_asin = score_results(
            filtered_results,
            query=query,
            details_by_asin=details_by_asin,
        )
        if limit is not None:
            filtered_results = filtered_results[:limit]
    return raw_results, filtered_results, details_by_asin, attempted, scores_by_asin


@dataclass(frozen=True, slots=True, kw_only=True)
class SearchRequest:
    """Resolved search parameters shared by both transports."""

    query: str = ""
    html_path: str | None = None
    page: int = 1
    pages: int = 1
    amazon_sort: str | None = None
    zip_code: str | None = None
    deals: bool = False
    min_rating: float | Decimal | None = None
    max_price: float | Decimal | None = None
    badge: str | None = None
    title_contains: str | None = None
    include: Sequence[str] | None = None
    exclude: Sequence[str] | None = None
    limit: int | None = None
    details: bool = False
    detail_limit: int | None = None
    scoring: bool = False

    def execute(self) -> tuple[SearchResultsPayload, list[SearchResult]]:
        """Search once and serialize the domain envelope using real result data."""
        with AmazonSearchClient() as client:
            raw, filtered, details, attempted, scores = search_and_filter(
                client=client,
                query=self.query,
                html_path=self.html_path,
                page=self.page,
                pages=self.pages,
                amazon_sort=self.amazon_sort,
                zip_code=self.zip_code,
                deals=self.deals,
                min_rating=self.min_rating,
                max_price=self.max_price,
                badge=self.badge,
                title_contains=self.title_contains,
                include=self.include,
                exclude=self.exclude,
                limit=self.limit,
                details=self.details,
                detail_limit=self.detail_limit,
                scoring=self.scoring,
            )
        payload = build_llm_json(
            query=self.query,
            html_path=self.html_path,
            page=self.page,
            pages=self.pages,
            amazon_sort=self.amazon_sort,
            zip_code=self.zip_code,
            deals=self.deals,
            page_info=client.page_info,
            checked_at=client.checked_at,
            min_rating=self.min_rating,
            max_price=self.max_price,
            badge=self.badge,
            title_contains=self.title_contains,
            include=self.include,
            exclude=self.exclude,
            limit=self.limit,
            details=self.details,
            detail_limit=self.detail_limit,
            scoring=self.scoring,
            raw_results=raw,
            filtered_results=filtered,
            details_by_asin=details,
            detail_attempted=attempted,
            scores_by_asin=scores,
        )
        return payload, filtered


def build_llm_json(
    *,
    query: str,
    html_path: str | None,
    page: int,
    pages: int,
    amazon_sort: str | None,
    zip_code: str | None = None,
    deals: bool = False,
    page_info: SearchPageInfo | None = None,
    checked_at: str | None = None,
    min_rating: float | Decimal | None,
    max_price: float | Decimal | None,
    badge: str | None,
    title_contains: str | None,
    include: Sequence[str] | None,
    exclude: Sequence[str] | None,
    limit: int | None,
    raw_results: Sequence[SearchResult],
    filtered_results: Sequence[SearchResult],
    details: bool = False,
    detail_limit: int | None = None,
    details_by_asin: dict[str, ProductDetail] | None = None,
    detail_attempted: int = 0,
    scoring: bool = False,
    scores_by_asin: dict[str, ResultScore] | None = None,
) -> SearchResultsPayload:
    """Build the LLM-first JSON envelope for results."""
    page_info = page_info or SearchPageInfo()
    if html_path is not None:
        source: SourcePayload = {"mode": "html", "html_path": html_path}
    else:
        source = {"mode": "live"}
        if checked_at is not None:
            source["checked_at"] = checked_at

    details_by_asin = details_by_asin or {}
    scores_by_asin = scores_by_asin or {}
    payload: SearchResultsPayload = {
        "type": LLM_JSON_TYPE,
        "version": PROTOCOL_VERSION,
        "ok": True,
        "source": source,
        "query": {
            "keywords": query,
            "page": page,
            "pages": pages,
            "amazon_sort": amazon_sort,
            "zip_code": zip_code,
            "deals": deals,
            "deal_refinement": page_info.deal_refinement,
        },
        "filters": {
            "min_rating": _json_number(min_rating),
            "max_price": _json_number(max_price),
            "badge": badge,
            "title_contains": title_contains,
            "include": list(include or ()),
            "exclude": list(exclude or ()),
            "limit": limit,
        },
        "summary": {
            "raw_result_count": len(raw_results),
            "returned_result_count": len(filtered_results),
            "delivery_location": page_info.delivery_location,
        },
        "enrichment": {
            "details": details,
            "detail_limit": detail_limit,
            "attempted": detail_attempted,
            "succeeded": len(details_by_asin),
        },
        "results": serialize_results(
            filtered_results,
            details_by_asin=details_by_asin,
            details=details,
            scores_by_asin=scores_by_asin,
        ),
    }
    warnings: list[str] = []
    location = page_info.delivery_location or "unknown"
    if zip_code is None or re.search(rf"\b{re.escape(zip_code.strip())}\b", location) is None:
        warnings.append(f"US ZIP not verified; observed delivery location: {location}.")
    if not raw_results:
        warnings.append(
            "Amazon reported no matching products; other searches may still have deals."
        )
    if warnings:
        payload["warnings"] = warnings
    if scoring:
        payload["ranking"] = {
            "mode": "agent_value",
            "scored_count": len(scores_by_asin),
            "details_used": len(details_by_asin),
            "limit_applied_after_ranking": True,
        }
    return payload


def serialize_results(
    results: Sequence[SearchResult],
    *,
    details: bool = False,
    details_by_asin: dict[str, ProductDetail] | None = None,
    scores_by_asin: dict[str, ResultScore] | None = None,
) -> list[SerializedSearchResultPayload]:
    """Serialize results with optional details and scores."""
    details_by_asin = details_by_asin or {}
    scores_by_asin = scores_by_asin or {}
    serialized: list[SerializedSearchResultPayload] = []
    for index, result in enumerate(results, start=1):
        item: SerializedSearchResultPayload = {**result.to_dict()}
        if details:
            detail = details_by_asin.get(result.asin)
            item["details"] = detail.to_dict() if detail is not None else None
        score = scores_by_asin.get(result.asin)
        if score is not None:
            score_payload = score.to_dict()
            item["score"] = score_payload["score"]
            item["reasons"] = score_payload["reasons"]
            item["signal_scores"] = score_payload["signal_scores"]
            item["brand_source"] = score_payload["brand_source"]
            item["ranking"] = {
                "rank": index,
                "score": score_payload["score"],
                "reasons": score_payload["reasons"],
                "signal_scores": score_payload["signal_scores"],
                "brand_source": score_payload["brand_source"],
            }
        serialized.append(item)
    return serialized


def get_schema_document() -> dict[str, object]:
    """Return the machine-readable capability document."""
    return {
        "type": SCHEMA_TYPE,
        "version": PROTOCOL_VERSION,
        "name": SCHEMA_NAME,
        "description": "Read-only Amazon search CLI with pi-inspired JSONL RPC.",
        "capabilities": {
            "read_only": True,
            "modes": ["cli", "rpc"],
            "outputs": ["text", "json", "llm-json"],
        },
        "cli": {
            "query_required_unless": ["--schema", "--mode rpc"],
            "options": {
                "--json": {"output": "raw_results_array"},
                "--llm-json": {"output": "rich_search_envelope"},
                "--schema": {"output": "schema_document"},
                "--mode rpc": {"output": "jsonl_rpc"},
                "--zip": {"query": "delivery_zip_code"},
                "--deals": {"query": "amazon_deal_refinement"},
                "--details": {"enrichment": "product_details"},
                "--detail-limit": {"enrichment_limit": "product_details"},
                "--scoring": {"ranking": "agent_value"},
            },
        },
        "llm_json": {
            "type": "object",
            "required": list(_LLM_JSON_REQUIRED_FIELDS),
            "properties": {
                "type": {"type": "string", "const": LLM_JSON_TYPE},
                "version": {"type": "string", "const": PROTOCOL_VERSION},
                "ok": {"type": "boolean"},
                "source": {
                    "type": "object",
                    "required": ["mode"],
                    "properties": {
                        "mode": {"type": "string", "enum": ["live", "html"]},
                        "html_path": {"type": ["string", "null"]},
                        "checked_at": {"type": "string", "format": "date-time"},
                    },
                },
                "query": {
                    "type": "object",
                    "required": [
                        "keywords",
                        "page",
                        "pages",
                        "amazon_sort",
                        "zip_code",
                        "deals",
                        "deal_refinement",
                    ],
                    "properties": {
                        "deals": {"type": "boolean"},
                        "deal_refinement": {"type": ["string", "null"]},
                    },
                },
                "filters": {
                    "type": "object",
                    "required": [
                        "min_rating",
                        "max_price",
                        "badge",
                        "title_contains",
                        "include",
                        "exclude",
                        "limit",
                    ],
                },
                "summary": {
                    "type": "object",
                    "required": ["raw_result_count", "returned_result_count", "delivery_location"],
                    "properties": {"delivery_location": {"type": ["string", "null"]}},
                },
                "results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": [
                            "asin",
                            "title",
                            "url",
                            "price",
                            "rating",
                            "review_count",
                            "badges",
                            "reference_price",
                            "reference_price_label",
                            "discount_percent",
                            "prime_exclusive",
                            "coupon_text",
                            "sponsored",
                        ],
                        "properties": {
                            "reference_price": {"type": ["number", "null"]},
                            "reference_price_label": {"type": ["string", "null"]},
                            "discount_percent": {
                                "type": ["number", "null"],
                                "description": "Percent below reference price, before coupons.",
                            },
                            "prime_exclusive": {
                                "type": ["boolean", "null"],
                                "description": "Price requires Prime; null if unknown.",
                            },
                            "coupon_text": {"type": ["string", "null"]},
                            "sponsored": {"type": "boolean"},
                        },
                    },
                },
                "warnings": {"type": "array", "items": {"type": "string"}},
            },
        },
        "rpc": {
            "pi_inspired": True,
            "full_pi_rpc": False,
            "transport": "jsonl",
            "request_command_field": "type",
            "legacy_request_command_field": "command",
            "response_envelope": {
                "type": "object",
                "required": ["type", "command", "success"],
                "properties": {
                    "id": {"type": ["string", "number", "null"]},
                    "type": {"type": "string", "const": "response"},
                    "command": {"type": "string"},
                    "success": {"type": "boolean"},
                    "data": {},
                    "error": {
                        "type": "object",
                        "required": ["code", "message"],
                    },
                },
            },
            "commands": {
                "ping": {
                    "request": _rpc_request_schema(command="ping"),
                    "response_data": {
                        "type": "object",
                        "required": ["ok", "version"],
                    },
                },
                "get_schema": {
                    "request": _rpc_request_schema(command="get_schema"),
                    "response_data": {"$ref": "#"},
                },
                "search": {
                    "request": _rpc_request_schema(
                        command="search",
                        properties={
                            "query": {"type": "string"},
                            "page": {"type": "integer", "minimum": 1},
                            "pages": {"type": "integer", "minimum": 1},
                            "amazonSort": {"type": ["string", "null"]},
                            "zipCode": {"type": ["string", "null"]},
                            "deals": {"type": ["boolean", "null"]},
                            "minRating": {"type": ["number", "null"]},
                            "maxPrice": {"type": ["number", "null"]},
                            "badge": {"type": ["string", "null"]},
                            "titleContains": {"type": ["string", "null"]},
                            "include": {
                                "oneOf": [
                                    {"type": "string"},
                                    {"type": "array", "items": {"type": "string"}},
                                ],
                            },
                            "exclude": {
                                "oneOf": [
                                    {"type": "string"},
                                    {"type": "array", "items": {"type": "string"}},
                                ],
                            },
                            "limit": {"type": ["integer", "null"], "minimum": 0},
                            "htmlPath": {"type": ["string", "null"]},
                            "details": {"type": ["boolean", "null"]},
                            "detailLimit": {"type": ["integer", "null"], "minimum": 0},
                            "scoring": {"type": ["boolean", "null"]},
                        },
                        required=["query"],
                    ),
                    "response_data": {
                        "type": "object",
                        "required": list(_LLM_JSON_REQUIRED_FIELDS),
                    },
                },
            },
        },
    }


def _rpc_request_schema(
    *,
    command: str,
    properties: dict[str, object] | None = None,
    required: Sequence[str] | None = None,
) -> dict[str, object]:
    request_properties: dict[str, object] = {
        "id": {"type": ["string", "number", "null"]},
        "type": {
            "type": "string",
            "description": "Primary request field for the RPC command name.",
        },
        "command": {
            "type": "string",
            "description": "Legacy alias; use type.",
        },
    }
    if properties:
        request_properties.update(properties)

    type_required = ["type", *(required or ())]
    command_required = ["command", *(required or ())]

    return {
        "type": "object",
        "properties": request_properties,
        "anyOf": [
            {
                "required": type_required,
                "properties": {"type": {"const": command}},
            },
            {
                "required": command_required,
                "properties": {"command": {"const": command}},
            },
        ],
    }


def _json_number(value: float | Decimal | None) -> float | None:
    if value is None:
        return None
    return float(value)
