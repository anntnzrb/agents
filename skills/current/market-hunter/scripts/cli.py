# /// script
# requires-python = ">=3.12"
# dependencies = ["firecrawl-py>=4"]
# ///
"""Search and score digital subscriptions and software across deal marketplaces."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

# Add lib directory to sys.path for internal imports
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from engine import execute_scan
from models import (
    SCHEMA_VERSION,
    DealHunterEnvelope,
    ScanOptions,
    ScanResultData,
    js_number_to_str,
    js_to_fixed2,
    js_to_locale_string,
)


def _sanitize_json(value: Any) -> Any:
    """Match JSON.stringify semantics: NaN/Infinity serialize to null."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: _sanitize_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
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


def emit_human_report(data: ScanResultData) -> None:
    """Emit the human-readable terminal report."""
    lines: list[str] = []

    lines.append("=" * 80)
    lines.append(f"🎯 MARKET HUNTER: {data['query'].upper()}")
    lines.append(
        f"Scanned: {data['total_scanned']} total offers across "
        f"[{', '.join(data['markets_queried'])}]"
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
            lines.append(
                f"Filtered out {data['filtered_scams_count']} "
                "low-trust or high-risk listings."
            )
        lines.append("")
        print("\n".join(lines))
        return

    top_pick = data["top_deals"][0]
    seller = top_pick["seller"]
    total_sales = seller.get("totalSalesCount")
    sales_suffix = f", {js_to_locale_string(total_sales)} sales" if total_sales else ""

    lines.append("👑 TOP VERIFIED RECOMMENDATION")
    lines.append(f"- Product: {top_pick['title']}")
    lines.append(f"- Marketplace: {top_pick['marketplace'].upper()}")
    lines.append(
        f"- Price: ${js_to_fixed2(top_pick['priceUsd'])} USD "
        f"({js_number_to_str(top_pick['discountVsMsrpPercent'])}% "
        "discount vs retail)"
    )
    lines.append(
        f"- Trust & Deal Score: {js_number_to_str(top_pick['trustScore'])}/100 "
        f"[{top_pick['trustTier']}]"
    )
    lines.append(f"- Delivery Format: {top_pick['deliveryFormat']}")
    lines.append(
        f"- Seller: {seller['name']} "
        f"({js_number_to_str(seller['positiveFeedbackPercent'])}% positive"
        f"{sales_suffix})"
    )
    warranty_days = top_pick.get("warrantyDays")
    if warranty_days:
        lines.append(
            f"- Warranty: {js_number_to_str(warranty_days)} days replacement guarantee"
        )
    lines.append(f"- Direct URL: {top_pick['url']}")
    if len(top_pick["detectedRedFlags"]) > 0:
        lines.append(f"- ⚠️ Warnings: {', '.join(top_pick['detectedRedFlags'])}")
    lines.append("")
    lines.append("-" * 80)
    lines.append("📋 RANKED DEALS LIST")
    lines.append("")

    display_deals = data["top_deals"][:10]
    for i, deal in enumerate(display_deals):
        rank = i + 1
        lines.append(
            f"{rank}. [Score: {js_number_to_str(deal['trustScore'])}/100 - "
            f"{deal['trustTier']}] ${js_to_fixed2(deal['priceUsd'])} | "
            f"{deal['marketplace'].upper()}"
        )
        lines.append(f"   Title: {deal['title']}")
        lines.append(
            f"   Format: {deal['deliveryFormat']} | Seller: "
            f"{deal['seller']['name']} "
            f"({js_number_to_str(deal['seller']['positiveFeedbackPercent'])}%)"
        )
        lines.append(f"   Link: {deal['url']}")
        if len(deal["detectedRedFlags"]) > 0:
            lines.append(f"   Flags: {', '.join(deal['detectedRedFlags'])}")
        lines.append("")

    if data["filtered_scams_count"] > 0:
        lines.append("-" * 80)
        lines.append(
            f"🛡️ Filtered Out: {data['filtered_scams_count']} high-risk, "
            "shared pool, or low-trust listings."
        )
        lines.append("=" * 80)

    print("\n".join(lines))


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="market-hunter",
        description=(
            "Search and score digital subscriptions and software "
            "across deal marketplaces"
        ),
    )
    parser.add_argument(
        "query",
        nargs="+",
        help="Search keywords for AI subscription, license, or account",
    )
    parser.add_argument(
        "--budget",
        type=float,
        default=None,
        help="Maximum budget in USD",
    )
    parser.add_argument(
        "--type",
        choices=["all", "account", "link", "code", "invite"],
        default="all",
        help="Delivery format filter (all, account, link, code, invite)",
    )
    parser.add_argument(
        "--min-score",
        type=int,
        default=50,
        help="Minimum Trust Score threshold (0-100)",
    )
    parser.add_argument(
        "--markets",
        type=str,
        default=None,
        help="Comma-separated list of marketplaces (g2a, kinguin, plati, z2u, funpay)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit raw JSON envelope only",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Include low-trust and filtered listings in output",
    )
    parser.add_argument("--version", action="version", version="1.0.0")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments, run the scan, and emit the report."""
    args = build_parser().parse_args(argv)

    query = " ".join(args.query)
    markets = [m.strip() for m in args.markets.split(",")] if args.markets else None

    options: ScanOptions = {
        "query": query,
        "typeFilter": args.type,
        "minScore": args.min_score,
        "jsonOnly": args.json,
        "full": args.full,
    }
    if args.budget is not None:
        options["budget"] = args.budget
    if markets is not None:
        options["markets"] = markets

    result_data = execute_scan(options)

    if args.json:
        emit_json(result_data)
    else:
        emit_human_report(result_data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
