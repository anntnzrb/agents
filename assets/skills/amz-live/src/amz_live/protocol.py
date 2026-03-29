from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Literal, NotRequired, TypedDict, cast

from .client import AmazonSearchClient
from .detail_parser import parse_product_detail
from .filters import filter_results
from .models import (
    ProductDetail,
    ProductDetailPayload,
    SearchQuery,
    SearchResult,
    SearchResultPayload,
)
from .parser import parse_search_results
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
_SEARCH_RESULTS_CACHE: dict[tuple[str, int, int, str | None, str | None], list[SearchResult]] = {}

class SourcePayload(TypedDict):
    mode: Literal["html", "live"]
    html_path: NotRequired[str]


class QueryPayload(TypedDict):
    keywords: str
    page: int
    pages: int
    amazon_sort: str | None
    zip_code: str | None


class FiltersPayload(TypedDict):
    min_rating: float | None
    max_price: float | None
    badge: str | None
    title_contains: str | None
    include: list[str]
    exclude: list[str]
    limit: int | None


class SummaryPayload(TypedDict):
    raw_result_count: int
    returned_result_count: int


class EnrichmentPayload(TypedDict):
    details: bool
    detail_limit: int | None
    attempted: int
    succeeded: int


class RankedResultScorePayload(ResultScorePayload):
    rank: int


class SerializedSearchResultPayload(SearchResultPayload, total=False):
    details: ProductDetailPayload | None
    score: float
    reasons: list[str]
    signal_scores: dict[str, float]
    brand_source: str | None
    ranking: RankedResultScorePayload


class RankingPayload(TypedDict):
    mode: Literal["agent_value"]
    scored_count: int
    details_used: int
    limit_applied_after_ranking: bool


class SearchResultsPayload(TypedDict):
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



def load_results(
    *,
    query: str,
    html_path: str | None,
    page: int,
    pages: int,
    amazon_sort: str | None,
    zip_code: str | None = None,
) -> list[SearchResult]:
    if html_path:
        html = Path(html_path).read_text(encoding="utf-8")
        return parse_search_results(html)

    cache_key = (query.strip(), page, pages, amazon_sort, zip_code)
    cached = _SEARCH_RESULTS_CACHE.get(cache_key)
    if cached is not None:
        return cached

    results: list[SearchResult] = []
    search_query = SearchQuery(query, page=page, amazon_sort=amazon_sort, zip_code=zip_code)
    with AmazonSearchClient() as client:
        results = client.search_pages(search_query, pages=pages)
    _SEARCH_RESULTS_CACHE[cache_key] = results
    return results


def enrich_results(
    results: Sequence[SearchResult],
    *,
    details: bool,
    detail_limit: int | None,
) -> tuple[dict[str, ProductDetail], int]:
    if not details:
        return {}, 0

    limit = len(results) if detail_limit is None else min(detail_limit, len(results))
    if limit <= 0:
        return {}, 0

    enriched: dict[str, ProductDetail] = {}
    with AmazonSearchClient() as client:
        for result in results[:limit]:
            try:
                html = client.fetch_product_page(result.url)
                enriched[result.asin] = parse_product_detail(html)
            except Exception:
                continue
    return enriched, limit


def search_and_filter(
    *,
    query: str,
    html_path: str | None,
    page: int,
    pages: int,
    amazon_sort: str | None,
    zip_code: str | None = None,
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
    raw_results = load_results(
        query=query,
        html_path=html_path,
        page=page,
        pages=pages,
        amazon_sort=amazon_sort,
        zip_code=zip_code,
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


def build_llm_json(
    *,
    query: str,
    html_path: str | None,
    page: int,
    pages: int,
    amazon_sort: str | None,
    zip_code: str | None = None,
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
    if html_path is not None:
        source: SourcePayload = {"mode": "html", "html_path": html_path}
    else:
        source = {"mode": "live"}

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
    details_by_asin = details_by_asin or {}
    scores_by_asin = scores_by_asin or {}
    serialized: list[SerializedSearchResultPayload] = []
    for index, result in enumerate(results, start=1):
        item = cast(SerializedSearchResultPayload, result.to_dict())
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
                    },
                },
                "query": {
                    "type": "object",
                    "required": ["keywords", "page", "pages", "amazon_sort", "zip_code"],
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
                    "required": ["raw_result_count", "returned_result_count"],
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
                        ],
                    },
                },
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
                            "minRating": {"type": ["number", "null"]},
                            "maxPrice": {"type": ["number", "null"]},
                            "badge": {"type": ["string", "null"]},
                            "titleContains": {"type": ["string", "null"]},
                            "include": {
                                "oneOf": [
                                    {"type": "string"},
                                    {"type": "array", "items": {"type": "string"}},
                                ]
                            },
                            "exclude": {
                                "oneOf": [
                                    {"type": "string"},
                                    {"type": "array", "items": {"type": "string"}},
                                ]
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
