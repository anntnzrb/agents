# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Run OMP search and emit an agent-shaped JSON envelope."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

# Add lib directory to sys.path for internal imports
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from config import discover_active_omp_providers
from executor import (
    SingleSearchExecutionOptions,
    execute_single_search,
    resolve_omp,
)
from merge import merge_parallel_results
from models import OmpBinaryNotFoundError, SearchResult


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser matching the omp-search command surface."""
    parser = argparse.ArgumentParser(
        prog="omp-search",
        description="Run OMP search and emit an agent-shaped JSON envelope.",
    )
    parser.add_argument(
        "query",
        nargs="+",
        metavar="query",
        help="Search query words",
    )
    parser.add_argument(
        "--provider",
        help="Explicit single OMP provider name",
    )
    parser.add_argument(
        "--providers",
        help=(
            "Comma-separated list of providers to query concurrently "
            "(defaults to OMP's configured active providers)"
        ),
    )
    parser.add_argument(
        "--single",
        action="store_true",
        help=("Force single-provider auto-fallback chain instead of parallel fan-out"),
    )
    parser.add_argument(
        "--recency",
        choices=["day", "week", "month", "year"],
        help="Recency filter (day, week, month, year)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=2,
        help="Number of sources per provider (minimum 2; defaults to 2)",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Request the complete OMP answer instead of compact output",
    )
    parser.add_argument(
        "--include-raw",
        action="store_true",
        help="Include ANSI-stripped raw OMP output for debugging",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=300.0,
        help="Outer timeout in seconds (default: 300)",
    )
    parser.add_argument(
        "--omp-bin",
        help="OMP executable path; defaults to OMP_BIN or omp on PATH",
    )
    parser.add_argument("--version", action="version", version="1.0.0")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Execute the omp-search command; return the process exit code."""
    parser = build_parser()
    args = parser.parse_intermixed_args(argv)

    try:
        binary = resolve_omp(args.omp_bin)
    except OmpBinaryNotFoundError as err:
        sys.stderr.write(f"omp-search: {err.message}\n")
        return 127

    fallback_query = " ".join(args.query)
    explicit_provider: str | None = args.provider
    explicit_providers: str | None = args.providers

    provider_list: list[str | None]
    if explicit_provider:
        provider_list = [explicit_provider]
    elif explicit_providers:
        provider_list = [
            p for p in (part.strip() for part in explicit_providers.split(",")) if p
        ]
    elif args.single:
        provider_list = [None]
    else:
        discovered = discover_active_omp_providers()
        provider_list = list(discovered) if discovered else [None]

    base_options = SingleSearchExecutionOptions(
        query_words=list(args.query),
        recency=args.recency,
        limit=args.limit,
        full=args.full,
        include_raw=args.include_raw,
        timeout_seconds=args.timeout,
        omp_bin=args.omp_bin,
    )

    final_payload: SearchResult
    if len(provider_list) == 1:
        final_payload = execute_single_search(
            replace(base_options, provider=provider_list[0]),
            binary,
        )
    else:
        with ThreadPoolExecutor(max_workers=max(len(provider_list), 1)) as pool:
            results = list(
                pool.map(
                    lambda provider: execute_single_search(
                        replace(base_options, provider=provider),
                        binary,
                    ),
                    provider_list,
                )
            )
        final_payload = merge_parallel_results(fallback_query, results, not args.full)

    sys.stdout.write(
        json.dumps(final_payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    )
    return final_payload["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
