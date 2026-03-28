from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import TextIO

from .models import AmazonLiveSearchError, SearchResult
from .protocol import (
    build_llm_json,
    get_schema_document,
    search_and_filter,
    serialize_results,
)
from .rpc import run_rpc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="amz-live",
        description="Read-only live Amazon search.",
    )
    parser.add_argument("query", nargs="?", help="Free-form Amazon search query.")
    parser.add_argument(
        "--page",
        type=_positive_int,
        default=1,
        help="Starting Amazon results page.",
    )
    parser.add_argument(
        "--pages",
        type=_positive_int,
        default=1,
        help="How many pages to fetch.",
    )
    parser.add_argument("--amazon-sort", help="Raw Amazon-side sort value, e.g. review-rank.")
    parser.add_argument("--zip", help="Set delivery zip code for localized results (e.g. 33101).")
    parser.add_argument("--min-rating", type=float, help="Minimum rating, e.g. 4.5.")
    parser.add_argument("--max-price", type=float, help="Maximum primary price.")
    parser.add_argument("--badge", help="Require a badge match, e.g. Best Seller.")
    parser.add_argument("--title-contains", help="Case-insensitive title substring filter.")
    parser.add_argument(
        "--include",
        action="append",
        default=[],
        help="Repeatable term that must appear.",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Repeatable term to reject.",
    )
    parser.add_argument(
        "--limit",
        type=_non_negative_int,
        help="Maximum number of results to print.",
    )
    parser.add_argument(
        "--details",
        action="store_true",
        help="Fetch product detail pages for filtered results.",
    )
    parser.add_argument(
        "--scoring",
        action="store_true",
        help="Rank results for agent usefulness and attach score + reasons.",
    )
    parser.add_argument(
        "--detail-limit",
        type=_non_negative_int,
        help="Maximum number of filtered results to enrich with product details.",
    )
    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of human text.",
    )
    output_group.add_argument(
        "--llm-json",
        action="store_true",
        help="Emit a rich LLM-first JSON envelope.",
    )
    parser.add_argument(
        "--schema",
        action="store_true",
        help="Print the machine-readable schema/capabilities document.",
    )
    parser.add_argument(
        "--mode",
        choices=("cli", "rpc"),
        default="cli",
        help="Run normal CLI output or pi-inspired JSONL RPC.",
    )
    parser.add_argument(
        "--html",
        help="Parse a local Amazon search HTML file instead of fetching live results.",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr

    parser = build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:
        return _exit_code(exc.code)

    if args.schema:
        _print_json(get_schema_document(), stdout=stdout)
        return 0

    if args.mode == "rpc":
        return run_rpc(stdin=stdin, stdout=stdout)

    if not args.query:
        return _parser_error(parser, "the following arguments are required: query", stderr=stderr)

    try:
        raw_results, filtered_results, details_by_asin, detail_attempted, scores_by_asin = (
            search_and_filter(
                query=args.query,
                html_path=args.html,
                page=args.page,
                pages=args.pages,
                amazon_sort=args.amazon_sort,
                zip_code=args.zip,
                min_rating=args.min_rating,
                max_price=args.max_price,
                badge=args.badge,
                title_contains=args.title_contains,
                include=args.include,
                exclude=args.exclude,
                limit=args.limit,
                details=args.details,
                detail_limit=args.detail_limit,
                scoring=args.scoring,
            )
        )
    except (AmazonLiveSearchError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=stderr)
        return 1

    if args.json:
        _print_json(
            serialize_results(
                filtered_results,
                details=args.details,
                details_by_asin=details_by_asin,
                scores_by_asin=scores_by_asin,
            ),
            stdout=stdout,
        )
    elif args.llm_json:
        _print_json(
            build_llm_json(
                query=args.query,
                html_path=args.html,
                page=args.page,
                pages=args.pages,
                amazon_sort=args.amazon_sort,
                zip_code=args.zip,
                min_rating=args.min_rating,
                max_price=args.max_price,
                badge=args.badge,
                title_contains=args.title_contains,
                include=args.include,
                exclude=args.exclude,
                limit=args.limit,
                raw_results=raw_results,
                filtered_results=filtered_results,
                details=args.details,
                detail_limit=args.detail_limit,
                details_by_asin=details_by_asin,
                detail_attempted=detail_attempted,
                scoring=args.scoring,
                scores_by_asin=scores_by_asin,
            ),
            stdout=stdout,
        )
    else:
        _print_human(filtered_results, stdout=stdout)
    return 0


def _print_human(results: Sequence[SearchResult], *, stdout: TextIO) -> None:
    for result in results:
        price = f"${result.price}" if result.price is not None else "-"
        rating = f"{result.rating}★" if result.rating is not None else "-"
        badges = f" [{', '.join(result.badges)}]" if result.badges else ""
        print(f"{result.asin} | {price} | {rating} | {result.title}{badges}", file=stdout)


def _print_json(payload: object, *, stdout: TextIO) -> None:
    print(json.dumps(payload, ensure_ascii=False), file=stdout)


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return parsed


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be >= 0")
    return parsed


def _exit_code(code: object) -> int:
    return code if isinstance(code, int) else 1


def _parser_error(parser: argparse.ArgumentParser, message: str, *, stderr: TextIO) -> int:
    parser.print_usage(stderr)
    print(f"{parser.prog}: error: {message}", file=stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
