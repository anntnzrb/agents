"""Public command-line parser and output selection."""

import argparse
import json
import sys
from typing import TYPE_CHECKING, cast

from .models import CONDITIONS, SORTS, EbayLiveError
from .protocol import SearchRequest, get_schema_document
from .rpc import run_rpc

if TYPE_CHECKING:
    from collections.abc import Sequence


# CamelCase destinations are the same request fields used by JSONL RPC.
def build_parser() -> argparse.ArgumentParser:
    """Build readable flags without duplicating request validation."""
    parser = argparse.ArgumentParser(
        prog="ebay-live", description="Read-only live eBay catalog search."
    )
    _ = parser.add_argument("query", nargs="?")
    _ = parser.add_argument("--sort", choices=list(SORTS), default="best-match")
    _ = parser.add_argument("--condition", choices=list(CONDITIONS))
    _ = parser.add_argument("--min-price", dest="minPrice", type=float)
    _ = parser.add_argument("--max-price", dest="maxPrice", type=float)
    formats = parser.add_mutually_exclusive_group()
    _ = formats.add_argument("--buy-it-now", dest="buyItNow", action="store_true")
    _ = formats.add_argument("--auction", action="store_true")
    _ = parser.add_argument("--page", type=int, default=1)
    _ = parser.add_argument("--pages", type=int, default=1)
    _ = parser.add_argument(
        "--per-page", dest="perPage", type=int, choices=(60, 120, 240), default=60
    )
    _ = parser.add_argument(
        "--zip", dest="zipCode", help="Best-effort US ZIP localization."
    )
    _ = parser.add_argument("--include", action="append", default=[])
    _ = parser.add_argument("--exclude", action="append", default=[])
    _ = parser.add_argument("--title-contains", dest="titleContains")
    _ = parser.add_argument(
        "--min-seller-feedback",
        dest="minSellerFeedback",
        type=float,
        help="Minimum positive seller feedback percentage (0 to 100).",
    )
    _ = parser.add_argument("--free-shipping", dest="freeShipping", action="store_true")
    _ = parser.add_argument("--limit", type=int)
    _ = parser.add_argument("--details", action="store_true")
    _ = parser.add_argument("--detail-limit", dest="detailLimit", type=int)
    _ = parser.add_argument("--scoring", action="store_true")
    _ = parser.add_argument(
        "--transport", choices=("auto", "direct", "firecrawl"), default="auto"
    )
    outputs = parser.add_mutually_exclusive_group()
    _ = outputs.add_argument("--json", action="store_true")
    _ = outputs.add_argument("--llm-json", dest="llmJson", action="store_true")
    _ = parser.add_argument("--schema", action="store_true")
    _ = parser.add_argument("--mode", choices=("cli", "rpc"), default="cli")
    _ = parser.add_argument(
        "--html",
        dest="htmlPath",
        help="Parse saved search HTML without a search fetch.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Return 0 for success, 1 for runtime errors, or 2 for usage errors."""
    parser = build_parser()
    args = cast("dict[str, object]", vars(parser.parse_args(argv)))
    if args["schema"]:
        print(json.dumps(get_schema_document()))  # noqa: T201 - public CLI output.
        return 0
    if args["mode"] == "rpc":
        return run_rpc(stdin=sys.stdin, stdout=sys.stdout)
    try:
        request = SearchRequest.from_mapping(args)
    except (ValueError, TypeError) as exc:
        parser.error(str(exc))
    try:
        payload = request.execute()
    except (EbayLiveError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)  # noqa: T201 - public CLI error.
        return 1
    if args["json"] or args["llmJson"]:
        print(  # noqa: T201 - public CLI output.
            json.dumps(
                payload["results"] if args["json"] else payload, ensure_ascii=False
            )
        )
    else:
        for result in cast("list[dict[str, object]]", payload["results"]):
            row = f"{result['item_id']} | {result['currency']} {result['price']}"
            shipping = f" + shipping {result['shipping_cost']} | {result['title']}"
            print(f"{row}{shipping}\n{result['url']}")  # noqa: T201 - CLI output.
        for warning in cast("list[str]", payload.get("warnings", [])):
            print(f"warning: {warning}", file=sys.stderr)  # noqa: T201 - public CLI warning.
    return 0
