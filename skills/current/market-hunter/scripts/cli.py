# /// script
# requires-python = ">=3.15.0rc2"
# dependencies = ["firecrawl-py>=4"]
# ///
"""Search and score digital subscriptions and software across deal marketplaces."""

import argparse
import json
import math
import sys
from pathlib import Path
from typing import TYPE_CHECKING

# Add lib directory to sys.path for internal imports
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from adapters.common import is_object_list, is_str_dict
from engine import execute_scan
from models import (
    SCHEMA_VERSION,
    DealHunterEnvelope,
    EngineError,
    ScanOptions,
    ScanResultData,
    ScoredDeal,
    js_number_to_str,
    js_to_fixed2,
    js_to_locale_string,
)

if TYPE_CHECKING:
    from collections.abc import Sequence


def _sanitize_json(value: object) -> object:
    """Match JSON.stringify semantics: NaN/Infinity serialize to null."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if is_str_dict(value):
        return {k: _sanitize_json(v) for k, v in value.items()}
    if is_object_list(value):
        return [_sanitize_json(v) for v in value]
    return value


def emit_json(data: ScanResultData) -> None:
    """Emit the structured JSON envelope."""
    envelope: DealHunterEnvelope = {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "command": "scan",
        "data": data,
    }
    print(json.dumps(_sanitize_json(envelope), indent=2, ensure_ascii=False))


def _format_top_pick(lines: list[str], top_pick: ScoredDeal) -> None:
    """Format the top verified recommendation section."""
    seller = top_pick["seller"]
    total_sales = seller.get("totalSalesCount")
    sales_suffix = f", {js_to_locale_string(total_sales)} sales" if total_sales else ""

    lines.append("👑 TOP VERIFIED RECOMMENDATION")
    lines.append(f"- Product: {top_pick['title']}")
    lines.append(f"- Marketplace: {top_pick['marketplace'].upper()}")
    price_str = js_to_fixed2(top_pick["priceUsd"])
    disc_str = js_number_to_str(top_pick["discountVsMsrpPercent"])
    score_str = js_number_to_str(top_pick["trustScore"])
    pos_str = js_number_to_str(seller["positiveFeedbackPercent"])
    lines.append(f"- Price: ${price_str} USD ({disc_str}% discount vs retail)")
    if "pricePerMonthUsd" in top_pick:
        per_month = js_to_fixed2(top_pick["pricePerMonthUsd"])
        lines.append(
            f"- Per Month: ${per_month} USD over {top_pick.get('months')} months"
        )
    lines.append(f"- Trust & Deal Score: {score_str}/100 [{top_pick['trustTier']}]")
    lines.append(f"- Delivery Format: {top_pick['deliveryFormat']}")
    lines.append(f"- Seller: {seller['name']} ({pos_str}% positive{sales_suffix})")
    warranty_days = top_pick.get("warrantyDays")
    if warranty_days:
        lines.append(
            f"- Warranty: {js_number_to_str(warranty_days)} days replacement guarantee"
        )
    lines.append(f"- Direct URL: {top_pick['url']}")
    if len(top_pick["detectedRedFlags"]) > 0:
        lines.append(f"- ⚠️ Warnings: {', '.join(top_pick['detectedRedFlags'])}")
    lines.append("")


def _format_ranked_deal(lines: list[str], rank: int, deal: ScoredDeal) -> None:
    """Format a single ranked deal entry."""
    score_str = js_number_to_str(deal["trustScore"])
    price_str = js_to_fixed2(deal["priceUsd"])
    pos_str = js_number_to_str(deal["seller"]["positiveFeedbackPercent"])
    market_upper = deal["marketplace"].upper()
    tier = deal["trustTier"]
    fmt = deal["deliveryFormat"]
    seller_name = deal["seller"]["name"]
    lines.append(
        f"{rank}. [Score: {score_str}/100 - {tier}] ${price_str} | {market_upper}"
    )
    lines.append(f"   Title: {deal['title']}")
    lines.append(f"   Format: {fmt} | Seller: {seller_name} ({pos_str}%)")
    if "pricePerMonthUsd" in deal:
        per_month = js_to_fixed2(deal["pricePerMonthUsd"])
        lines.append(f"   Per Month: ${per_month} over {deal.get('months')} months")
    lines.append(f"   Link: {deal['url']}")
    if len(deal["detectedRedFlags"]) > 0:
        lines.append(f"   Flags: {', '.join(deal['detectedRedFlags'])}")
    lines.append("")


def emit_human_report(data: ScanResultData) -> None:
    """Emit the human-readable terminal report."""
    lines: list[str] = []

    lines.append("=" * 80)
    lines.append(f"🎯 MARKET HUNTER: {data['query'].upper()}")
    markets_str = ", ".join(data["markets_queried"])
    lines.append(
        f"Scanned: {data['total_scanned']} total offers across [{markets_str}]"
    )
    if data["budget"] is not None:
        lines.append(f"Budget Constraint: <= ${js_to_fixed2(data['budget'])} USD")
    warning = data.get("warning")
    if warning:
        lines.append("-" * 80)
        lines.append(f"⚠️  NOTICE: {warning}")
    lines.append("=" * 80)
    lines.append("")

    if len(data["top_deals"]) == 0:
        lines.append("No verified deals found matching your criteria.")
        if data["filtered_scams_count"] > 0:
            scams = data["filtered_scams_count"]
            lines.append(f"Filtered out {scams} low-trust or high-risk listings.")
        lines.append("")
        print("\n".join(lines))
        return

    _format_top_pick(lines, data["top_deals"][0])
    lines.append("-" * 80)
    lines.append("📋 RANKED DEALS LIST")
    lines.append("")

    for i, deal in enumerate(data["top_deals"][:10]):
        _format_ranked_deal(lines, i + 1, deal)

    if data["filtered_scams_count"] > 0:
        lines.append("-" * 80)
        scams = data["filtered_scams_count"]
        lines.append(
            f"🛡️ Filtered Out: {scams} high-risk, shared pool, or low-trust listings."
        )
        lines.append("=" * 80)

    print("\n".join(lines))


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    desc_head = "Search and score digital subscriptions and software"
    parser = argparse.ArgumentParser(
        prog="market-hunter",
        description=f"{desc_head} across deal marketplaces",
    )
    _ = parser.add_argument(
        "query",
        nargs="+",
        help="Search keywords for AI subscription, license, or account",
    )
    _ = parser.add_argument(
        "--budget",
        type=float,
        default=None,
        help="Maximum budget in USD",
    )
    _ = parser.add_argument(
        "--type",
        choices=["all", "account", "link", "code", "invite"],
        default="all",
        help="Delivery format filter (all, account, link, code, invite)",
    )
    _ = parser.add_argument(
        "--min-score",
        type=int,
        default=50,
        help="Minimum Trust Score threshold (0-100)",
    )
    _ = parser.add_argument(
        "--markets",
        type=str,
        default=None,
        help="Comma-separated list of marketplaces (g2a, kinguin, plati, z2u, funpay)",
    )
    _ = parser.add_argument(
        "--url",
        action="append",
        default=None,
        help="Marketplace listing page to scan instead of default targets (repeat)",
    )
    _ = parser.add_argument(
        "--json",
        action="store_true",
        help="Emit raw JSON envelope only",
    )
    _ = parser.add_argument(
        "--full",
        action="store_true",
        help="Include low-trust and filtered listings in output",
    )
    _ = parser.add_argument("--version", action="version", version="1.0.0")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments, run the scan, and emit the report."""
    args = build_parser().parse_args(argv)

    query_raw: object = getattr(args, "query", [])
    query_parts = (
        [str(p) for p in query_raw] if is_object_list(query_raw) else [str(query_raw)]
    )
    query = " ".join(query_parts)

    markets_raw: object = getattr(args, "markets", None)
    markets = (
        [m.strip() for m in str(markets_raw).split(",")]
        if isinstance(markets_raw, str)
        else None
    )

    type_raw: object = getattr(args, "type", "all")
    min_score_raw: object = getattr(args, "min_score", 50)
    json_raw: object = getattr(args, "json", False)
    full_raw: object = getattr(args, "full", False)
    budget_raw: object = getattr(args, "budget", None)

    options: ScanOptions = {
        "query": query,
        "typeFilter": str(type_raw) if type_raw is not None else "all",
        "minScore": int(min_score_raw) if isinstance(min_score_raw, int) else 50,
        "jsonOnly": bool(json_raw),
        "full": bool(full_raw),
    }
    if isinstance(budget_raw, (int, float)):
        options["budget"] = float(budget_raw)
    if markets is not None:
        options["markets"] = markets
    urls_raw: object = getattr(args, "url", None)
    if is_object_list(urls_raw):
        options["urls"] = [str(u) for u in urls_raw]

    try:
        result_data = execute_scan(options)
    except EngineError as err:
        print(f"market-hunter: {err.message}", file=sys.stderr)
        return 2

    if bool(json_raw):
        emit_json(result_data)
    else:
        emit_human_report(result_data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
