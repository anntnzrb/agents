"""Derive per-variant evaluation costs from published token counts."""

import math
from decimal import Decimal

from .contracts import is_str_dict


def _number(value: object) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return Decimal(str(value))


def derive_eval_cost(  # noqa: PLR0913
    rows: list[dict[str, object]],
    metric: str,
    attempts: int,
    prices: dict[str, dict[str, object]],
    *,
    source_url: str,
    manifest_hash: str | None,
) -> list[dict[str, object]]:
    """Calculate costs, preserving unavailable inputs as null."""
    if attempts < 1:
        raise ValueError("attempts must be positive")
    result: list[dict[str, object]] = []
    for row in rows:
        slug = row.get("slug")
        score = _number(row.get(metric))
        if not isinstance(slug, str) or score is None:
            continue
        counts = row.get("canonicalEvalTokenCounts")
        counts = counts.get(metric) if is_str_dict(counts) else None
        counts = counts if is_str_dict(counts) else {}
        pricing = prices.get(slug, {})
        input_price = _number(row.get("price1mInputTokens"))
        output_price = _number(row.get("price1mOutputTokens"))
        input_source = "evaluation_manifest"
        if input_price is None:
            input_price = _number(pricing.get("price_1m_input_tokens"))
            input_source = "free_api_snapshot"
        output_source = "evaluation_manifest"
        if output_price is None:
            output_price = _number(pricing.get("price_1m_output_tokens"))
            output_source = "free_api_snapshot"
        cache_price = _number(row.get("cacheHitPrice"))
        cache_source = "evaluation_manifest"
        if cache_price is None:
            cache_price = _number(pricing.get("price_1m_cache_hit_tokens"))
            cache_source = (
                "free_api_snapshot" if cache_price is not None else "input_rate"
            )
        token_input = _number(counts.get("input"))
        answer = _number(counts.get("answer"))
        reasoning = _number(counts.get("reasoning"))
        cacheable = _number(counts.get("cacheableInput"))
        total = None
        if (
            token_input is not None
            and answer is not None
            and reasoning is not None
            and cacheable is not None
            and input_price is not None
            and output_price is not None
        ) and cacheable <= token_input:
            effective_cache_price = (
                cache_price if cache_price is not None else input_price
            )
            total = (
                (token_input - cacheable) * input_price
                + cacheable * effective_cache_price
                + (answer + reasoning) * output_price
            ) / Decimal(1_000_000)
        result.append(
            {
                "slug": slug,
                "name": row.get("name"),
                "score": float(score),
                "score_status": "published",
                "metric": metric,
                "tokens": counts,
                "attempts": attempts,
                "total_cost_usd": float(total) if total is not None else None,
                "cost_per_task_usd": float(total / attempts)
                if total is not None
                else None,
                "value_status": "derived",
                "source_url": source_url,
                "manifest_hash": manifest_hash,
                "pricing_source": {
                    "input": input_source,
                    "output": output_source,
                    "cache_hit": cache_source,
                },
                "prices_per_million": {
                    "input": float(input_price) if input_price is not None else None,
                    "output": float(output_price) if output_price is not None else None,
                    "cache_hit": float(cache_price)
                    if cache_price is not None
                    else None,
                },
                "cache_pricing": "cache_hit_assumed"
                if cache_price is not None
                else "input_rate_fallback",
            }
        )
    return result
