"""Search pipeline and published JSON Schema for agent output."""

import math
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

from .client import EbayClient, check_page
from .detail_parser import parse_item_detail
from .filters import Filters, filter_results
from .models import CONDITIONS, SORTS, EbayLiveError, SearchQuery
from .parser import parse_search_page
from .query import build_search_url
from .score import query_match, rank_results

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .models import Listing, Transport


MAX_FEEDBACK = 100


def read_string(
    data: Mapping[str, object], key: str, default: str | None = None
) -> str | None:
    """Read an optional string at the CLI or RPC boundary."""
    value = data.get(key, default)
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{key} must be a string")
    return value.strip() or None


def read_int(
    data: Mapping[str, object], key: str, default: int | None = None
) -> int | None:
    """Read a non-negative integer, rejecting JSON booleans."""
    value = data.get(key, default)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{key} must be a non-negative integer")
    return value


def read_number(data: Mapping[str, object], key: str) -> float | None:
    """Read a finite, non-negative number."""
    value = data.get(key)
    if value is None:
        return None
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError(f"{key} must be a finite non-negative number")
    return float(value)


def read_bool(data: Mapping[str, object], key: str) -> bool:
    """Read a strict JSON boolean, defaulting to false."""
    value = data.get(key, False)
    if not isinstance(value, bool):
        raise TypeError(f"{key} must be a boolean")
    return value


def read_terms(data: Mapping[str, object], key: str) -> tuple[str, ...]:
    """Read repeatable title terms as an array or a single string."""
    value = data.get(key, [])
    if isinstance(value, str):
        return (value,)
    if not isinstance(value, list):
        raise TypeError(f"{key} must be a string or an array of strings")
    terms: list[str] = []
    for term in cast("list[object]", value):
        if not isinstance(term, str) or not term.strip():
            raise ValueError(f"{key} must contain non-empty strings")
        terms.append(term.strip())
    return tuple(terms)


@dataclass(frozen=True, slots=True)
class SearchRequest:
    """Validated parameters shared by CLI and JSONL RPC."""

    query: SearchQuery
    filters: Filters
    pages: int = 1
    transport: Transport = "auto"
    html_path: str | None = None
    details: bool = False
    detail_limit: int | None = None
    scoring: bool = False

    @classmethod
    def from_mapping(cls, data: Mapping[str, object]) -> SearchRequest:
        """Validate untrusted request fields once, before the pipeline."""
        keywords = read_string(data, "query")
        if not keywords:
            raise ValueError("query must be a non-empty string")
        transport = read_string(data, "transport", "auto")
        if transport not in ("auto", "direct", "firecrawl"):
            raise ValueError("transport must be auto, direct, or firecrawl")
        page = read_int(data, "page", 1)
        pages = read_int(data, "pages", 1)
        per_page = read_int(data, "perPage", 60)
        if page is None or pages is None or per_page is None or pages < 1:
            raise ValueError("page, pages, and perPage must be positive integers")
        feedback = read_number(data, "minSellerFeedback")
        if feedback is not None and feedback > MAX_FEEDBACK:
            raise ValueError("minSellerFeedback must be between 0 and 100")
        html_path = read_string(data, "htmlPath")
        if html_path and pages != 1:
            raise ValueError("--html accepts exactly one page")
        return cls(
            query=SearchQuery(
                keywords,
                sort=read_string(data, "sort", "best-match") or "best-match",
                min_price=read_number(data, "minPrice"),
                max_price=read_number(data, "maxPrice"),
                condition=read_string(data, "condition"),
                buy_it_now=read_bool(data, "buyItNow"),
                auction=read_bool(data, "auction"),
                page=page,
                per_page=per_page,
                zip_code=read_string(data, "zipCode"),
            ),
            filters=Filters(
                include=read_terms(data, "include"),
                exclude=read_terms(data, "exclude"),
                title_contains=read_string(data, "titleContains"),
                min_seller_feedback=feedback,
                free_shipping=read_bool(data, "freeShipping"),
                limit=read_int(data, "limit"),
            ),
            pages=pages,
            transport=transport,
            html_path=html_path,
            details=read_bool(data, "details"),
            detail_limit=read_int(data, "detailLimit"),
            scoring=read_bool(data, "scoring"),
        )

    def execute(self) -> dict[str, object]:  # noqa: C901 - sequential search pipeline.
        """Fetch, deduplicate, filter, rank, limit, and optionally enrich."""
        with EbayClient(self.transport) as client:
            deduped: dict[str, Listing] = {}
            rewrite_excluded = 0
            final_url = build_search_url(self.query, base_url=client.base_url)
            if self.html_path:
                html = Path(self.html_path).read_text(encoding="utf-8")
                check_page(html, final_url, 200, search=True)
                parsed = parse_search_page(html)
                deduped = {r.item_id: r for r in parsed.results}
                rewrite_excluded = parsed.rewrite_excluded_count
                client.log.append(
                    {
                        "url": self.html_path,
                        "final_url": final_url,
                        "transport": "html",
                        "ok": True,
                    }
                )
            else:
                for page in range(self.query.page, self.query.page + self.pages):
                    url = build_search_url(
                        replace(self.query, page=page), base_url=client.base_url
                    )
                    fetched = client.fetch(url, search=True)
                    final_url = fetched.url
                    parsed = parse_search_page(fetched.html)
                    results = parsed.results
                    rewrite_excluded += parsed.rewrite_excluded_count
                    for result in results:
                        _ = deduped.setdefault(result.item_id, result)
                    if not results:
                        break
            if not deduped:
                client.warnings.append(
                    "Zero exact matches; expanded rewrite results excluded"
                )
            selected = filter_results(list(deduped.values()), self.filters)
            payloads = (
                rank_results(
                    selected, self.query.keywords, buy_now=self.query.buy_it_now
                )
                if self.scoring
                else [
                    {
                        **r.to_dict(),
                        "query_match": query_match(r.title, self.query.keywords),
                    }
                    for r in selected
                ]
            )
            if self.filters.limit is not None:
                payloads = payloads[: self.filters.limit]
            attempted = 0
            enriched = 0
            if self.details:
                for result in payloads[: self.detail_limit]:
                    attempted += 1
                    item_id = result["item_id"]
                    url = f"{client.base_url}/itm/{item_id}"
                    try:
                        fetched = client.fetch(url)
                        detail = parse_item_detail(fetched.html)
                    except EbayLiveError as exc:
                        client.warnings.append(
                            f"Detail fetch failed for {item_id}: {exc}"
                        )
                        continue
                    result["details"] = asdict(detail)
                    enriched += 1
            if self.query.zip_code:
                client.warnings.append(
                    "ZIP hint is best-effort; delivery location was not confirmed"
                )
            payload: dict[str, object] = {
                "type": "ebay-live.search_results",
                "version": "1",
                "ok": True,
                "source": {
                    "mode": "html" if self.html_path else "live",
                    "html_path": self.html_path,
                    "checked_at": datetime.now(UTC).isoformat(),
                },
                "query": {**asdict(self.query), "pages": self.pages, "url": final_url},
                "filters": {
                    **asdict(self.filters),
                    "include": list(self.filters.include),
                    "exclude": list(self.filters.exclude),
                },
                "summary": {
                    "raw_result_count": len(deduped),
                    "exact_result_count": len(deduped),
                    "rewrite_excluded_count": rewrite_excluded,
                    "returned_result_count": len(payloads),
                    "transport": sorted(
                        {str(row["transport"]) for row in client.log if row["ok"]}
                    ),
                    "fetches": client.log,
                },
                "enrichment": {
                    "requested": self.details,
                    "detail_limit": self.detail_limit,
                    "attempted": attempted,
                    "succeeded": enriched,
                },
                "results": payloads,
            }
            if client.warnings:
                payload["warnings"] = client.warnings
            if self.scoring:
                payload["ranking"] = {
                    "method": "relative-value-v1",
                    "score_range": [0, 100],
                    "population": len(selected),
                    "buy_now_intent": self.query.buy_it_now,
                }
            return payload


def object_schema(
    properties: dict[str, object], *, optional: tuple[str, ...] = ()
) -> dict[str, object]:
    """Build a closed object schema; additive fields must be declared."""
    return {
        "type": "object",
        "properties": properties,
        "required": [k for k in properties if k not in optional],
        "additionalProperties": False,
    }


def get_schema_document() -> dict[str, object]:
    """Publish the exact output fields and supported RPC request names."""
    string: dict[str, object] = {"type": "string"}
    nullable_string: dict[str, object] = {"type": ["string", "null"]}
    number: dict[str, object] = {"type": ["number", "null"]}
    integer: dict[str, object] = {"type": "integer", "minimum": 0}
    nullable_int: dict[str, object] = {"type": ["integer", "null"], "minimum": 0}
    boolean: dict[str, object] = {"type": "boolean"}
    strings: dict[str, object] = {"type": "array", "items": string}
    listing: dict[str, object] = {
        **dict.fromkeys(("item_id", "title", "url"), string),
        **dict.fromkeys(
            (
                "price",
                "price_max",
                "shipping_cost",
                "total_cost",
                "seller_feedback_pct",
            ),
            number,
        ),
        **dict.fromkeys(
            (
                "currency",
                "condition",
                "time_left",
                "time_end",
                "seller_name",
                "location",
            ),
            nullable_string,
        ),
        "buying_format": {
            "type": "array",
            "items": {"enum": ["auction", "buy_it_now", "best_offer"]},
        },
        "bid_count": nullable_int,
        "seller_feedback_count": nullable_int,
        "sponsored": {"type": ["boolean", "null"]},
        "query_match": {"type": "number", "minimum": 0, "maximum": 1},
        "score": {"type": "number", "minimum": 0, "maximum": 100},
        "reasons": strings,
        "rank": integer,
        "details": object_schema(
            {
                **dict.fromkeys(
                    (
                        "title",
                        "currency",
                        "condition",
                        "time_left",
                        "seller_name",
                        "seller_feedback_text",
                        "returns",
                        "shipping_text",
                        "brand",
                        "model",
                        "gtin",
                        "mpn",
                        "availability",
                    ),
                    nullable_string,
                ),
                "price": number,
                "shipping_cost": number,
                "bid_count": nullable_int,
                "item_specifics": {"type": "object", "additionalProperties": string},
            }
        ),
    }
    envelope = object_schema(
        {
            "type": {"const": "ebay-live.search_results"},
            "version": {"const": "1"},
            "ok": {"const": True},
            "source": object_schema(
                {
                    "mode": {"enum": ["html", "live"]},
                    "html_path": nullable_string,
                    "checked_at": string,
                }
            ),
            "query": object_schema(
                {
                    "keywords": string,
                    "sort": {"enum": list(SORTS)},
                    "min_price": number,
                    "max_price": number,
                    "condition": {"enum": [None, *CONDITIONS]},
                    "buy_it_now": boolean,
                    "auction": boolean,
                    "page": integer,
                    "per_page": {"enum": [60, 120, 240]},
                    "zip_code": nullable_string,
                    "pages": integer,
                    "url": string,
                }
            ),
            "filters": object_schema(
                {
                    "include": strings,
                    "exclude": strings,
                    "title_contains": nullable_string,
                    "min_seller_feedback": number,
                    "free_shipping": boolean,
                    "limit": nullable_int,
                }
            ),
            "summary": object_schema(
                {
                    "raw_result_count": integer,
                    "exact_result_count": integer,
                    "rewrite_excluded_count": integer,
                    "returned_result_count": integer,
                    "transport": strings,
                    "fetches": {
                        "type": "array",
                        "items": object_schema(
                            {
                                "url": string,
                                "final_url": string,
                                "transport": {"enum": ["direct", "firecrawl", "html"]},
                                "ok": boolean,
                            }
                        ),
                    },
                }
            ),
            "enrichment": object_schema(
                {
                    "requested": boolean,
                    "detail_limit": nullable_int,
                    "attempted": integer,
                    "succeeded": integer,
                }
            ),
            "results": {
                "type": "array",
                "items": object_schema(
                    listing, optional=("score", "reasons", "rank", "details")
                ),
            },
            "warnings": strings,
            "ranking": object_schema(
                {
                    "method": {"const": "relative-value-v1"},
                    "score_range": {"const": [0, 100]},
                    "population": integer,
                    "buy_now_intent": boolean,
                }
            ),
        },
        optional=("warnings", "ranking"),
    )
    return {
        "type": "ebay-live.schema",
        "version": "1",
        "name": "ebay-live",
        "llm_json": envelope,
        "rpc": {
            "commands": ["ping", "get_schema", "search"],
            "request_fields": [
                "query",
                "sort",
                "minPrice",
                "maxPrice",
                "condition",
                "buyItNow",
                "auction",
                "page",
                "pages",
                "perPage",
                "zipCode",
                "include",
                "exclude",
                "titleContains",
                "minSellerFeedback",
                "freeShipping",
                "limit",
                "details",
                "detailLimit",
                "scoring",
                "transport",
                "htmlPath",
            ],
        },
    }
