"""Command-line interface for live Amazon search."""

from __future__ import annotations

import argparse
import json
import sys
from typing import TYPE_CHECKING, TextIO, cast

if TYPE_CHECKING:
    from collections.abc import Sequence

from .models import AmazonLiveSearchError, SearchResult
from .protocol import (
    build_llm_json,
    get_schema_document,
    search_and_filter,
    serialize_results,
)
from .rpc import run_rpc


def build_parser() -> argparse.ArgumentParser:
    """Construct the amz-live argument parser."""
    parser = argparse.ArgumentParser(
        prog="amz-live",
        description="Read-only live Amazon search.",
    )
    _ = parser.add_argument("query", nargs="?", help="Free-form Amazon search query.")
    _ = parser.add_argument(
        "--page",
        type=_positive_int,
        default=1,
        help="Starting Amazon results page.",
    )
    _ = parser.add_argument(
        "--pages",
        type=_positive_int,
        default=1,
        help="How many pages to fetch.",
    )
    _ = parser.add_argument("--amazon-sort", help="Raw Amazon-side sort value, e.g. review-rank.")
    _ = parser.add_argument(
        "--zip", help="Set delivery zip code for localized results (e.g. 33101)."
    )
    _ = parser.add_argument("--min-rating", type=float, help="Minimum rating, e.g. 4.5.")
    _ = parser.add_argument("--max-price", type=float, help="Maximum primary price.")
    _ = parser.add_argument("--badge", help="Require a badge match, e.g. Best Seller.")
    _ = parser.add_argument("--title-contains", help="Case-insensitive title substring filter.")
    _ = parser.add_argument(
        "--include",
        action="append",
        default=[],
        help="Repeatable term that must appear.",
    )
    _ = parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Repeatable term to reject.",
    )
    _ = parser.add_argument(
        "--limit",
        type=_non_negative_int,
        help="Maximum number of results to print.",
    )
    _ = parser.add_argument(
        "--details",
        action="store_true",
        help="Fetch product detail pages for filtered results.",
    )
    _ = parser.add_argument(
        "--scoring",
        action="store_true",
        help="Rank results for agent usefulness and attach score + reasons.",
    )
    _ = parser.add_argument(
        "--detail-limit",
        type=_non_negative_int,
        help="Maximum number of filtered results to enrich with product details.",
    )
    output_group = parser.add_mutually_exclusive_group()
    _ = output_group.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of human text.",
    )
    _ = output_group.add_argument(
        "--llm-json",
        action="store_true",
        help="Emit a rich LLM-first JSON envelope.",
    )
    _ = parser.add_argument(
        "--schema",
        action="store_true",
        help="Print the machine-readable schema/capabilities document.",
    )
    _ = parser.add_argument(
        "--mode",
        choices=("cli", "rpc"),
        default="cli",
        help="Run normal CLI output or pi-inspired JSONL RPC.",
    )
    _ = parser.add_argument(
        "--html",
        help="Parse a local Amazon search HTML file instead of fetching live results.",
    )
    return parser


def _config_str(args: argparse.Namespace, field: str) -> str:
    """Extract a required str option from parsed args."""
    return cast("str", getattr(args, field))


def _optional_str(args: argparse.Namespace, field: str) -> str | None:
    """Extract an optional str option from parsed args."""
    return cast("str | None", getattr(args, field))


def _config_int(args: argparse.Namespace, field: str) -> int:
    """Extract a required int option from parsed args."""
    return cast("int", getattr(args, field))


def _optional_int(args: argparse.Namespace, field: str) -> int | None:
    """Extract an optional int option from parsed args."""
    return cast("int | None", getattr(args, field))


def _optional_float(args: argparse.Namespace, field: str) -> float | None:
    """Extract an optional float option from parsed args."""
    return cast("float | None", getattr(args, field))


def _config_str_list(args: argparse.Namespace, field: str) -> list[str]:
    """Extract a required string-list option from parsed args."""
    return cast("list[str]", getattr(args, field))


def _config_bool(args: argparse.Namespace, field: str) -> bool:
    """Extract a required bool flag from parsed args."""
    return cast("bool", getattr(args, field))


def main(
    argv: Sequence[str] | None = None,
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Run the amz-live CLI and return a process exit code."""
    input_stream: TextIO = sys.stdin if stdin is None else stdin
    output_stream: TextIO = sys.stdout if stdout is None else stdout
    error_stream: TextIO = sys.stderr if stderr is None else stderr

    parser = build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:
        return _exit_code(exc.code)
    query = _optional_str(args, "query")
    schema = _config_bool(args, "schema")
    mode = _config_str(args, "mode")
    html_path = _optional_str(args, "html")
    page = _config_int(args, "page")
    pages = _config_int(args, "pages")
    amazon_sort = _optional_str(args, "amazon_sort")
    zip_code = _optional_str(args, "zip")
    min_rating = _optional_float(args, "min_rating")
    max_price = _optional_float(args, "max_price")
    badge = _optional_str(args, "badge")
    title_contains = _optional_str(args, "title_contains")
    include = _config_str_list(args, "include")
    exclude = _config_str_list(args, "exclude")
    limit = _optional_int(args, "limit")
    details = _config_bool(args, "details")
    detail_limit = _optional_int(args, "detail_limit")
    scoring = _config_bool(args, "scoring")
    json_output = _config_bool(args, "json")
    llm_json = _config_bool(args, "llm_json")

    if schema:
        _print_json(get_schema_document(), stdout=output_stream)
        return 0

    if mode == "rpc":
        return run_rpc(stdin=input_stream, stdout=output_stream)

    if not query:
        return _parser_error(
            parser,
            "the following arguments are required: query",
            stderr=error_stream,
        )

    try:
        raw_results, filtered_results, details_by_asin, detail_attempted, scores_by_asin = (
            search_and_filter(
                query=query,
                html_path=html_path,
                page=page,
                pages=pages,
                amazon_sort=amazon_sort,
                zip_code=zip_code,
                min_rating=min_rating,
                max_price=max_price,
                badge=badge,
                title_contains=title_contains,
                include=include,
                exclude=exclude,
                limit=limit,
                details=details,
                detail_limit=detail_limit,
                scoring=scoring,
            )
        )
    except (AmazonLiveSearchError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=error_stream)
        return 1

    if json_output:
        _print_json(
            serialize_results(
                filtered_results,
                details=details,
                details_by_asin=details_by_asin,
                scores_by_asin=scores_by_asin,
            ),
            stdout=output_stream,
        )
    elif llm_json:
        _print_json(
            build_llm_json(
                query=query,
                html_path=html_path,
                page=page,
                pages=pages,
                amazon_sort=amazon_sort,
                zip_code=zip_code,
                min_rating=min_rating,
                max_price=max_price,
                badge=badge,
                title_contains=title_contains,
                include=include,
                exclude=exclude,
                limit=limit,
                raw_results=raw_results,
                filtered_results=filtered_results,
                details=details,
                detail_limit=detail_limit,
                details_by_asin=details_by_asin,
                detail_attempted=detail_attempted,
                scoring=scoring,
                scores_by_asin=scores_by_asin,
            ),
            stdout=output_stream,
        )
    else:
        _print_human(filtered_results, stdout=output_stream)
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
        msg = "must be >= 1"
        raise argparse.ArgumentTypeError(msg)
    return parsed


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        msg = "must be >= 0"
        raise argparse.ArgumentTypeError(msg)
    return parsed


def _exit_code(code: object) -> int:
    return code if isinstance(code, int) else 1


def _parser_error(parser: argparse.ArgumentParser, message: str, *, stderr: TextIO) -> int:
    parser.print_usage(stderr)
    print(f"{parser.prog}: error: {message}", file=stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
