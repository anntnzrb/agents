from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import date
from typing import TextIO

from .models import FlightLiveError, SearchRequest
from .protocol import get_schema_document, search_flights, serialize_results
from .rpc import run_rpc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="flight-live",
        description="Read-only flight search (Kiwi web scrape planner).",
    )
    parser.add_argument("--origin", help="Origin city/airport term or IATA.")
    parser.add_argument("--destination", help="Destination city/airport term or IATA.")
    parser.add_argument("--depart-start", type=_iso_date, help="Departure window start (YYYY-MM-DD).")
    parser.add_argument("--depart-end", type=_iso_date, help="Departure window end (YYYY-MM-DD).")
    parser.add_argument(
        "--trip-type",
        choices=("oneway", "roundtrip"),
        default="oneway",
    )
    parser.add_argument("--stay-min", type=_non_negative_int)
    parser.add_argument("--stay-max", type=_non_negative_int)
    parser.add_argument("--adults", type=_positive_int, default=1)
    parser.add_argument("--children", type=_non_negative_int, default=0)
    parser.add_argument("--infants", type=_non_negative_int, default=0)
    parser.add_argument(
        "--cabin",
        choices=("economy", "premium_economy", "business", "first"),
        default="economy",
    )
    parser.add_argument("--currency", default="USD")
    parser.add_argument("--locale", default="en")
    parser.add_argument("--market", default="us")
    parser.add_argument("--nonstop", action="store_true")
    parser.add_argument("--max-budget", type=float)
    parser.add_argument("--planner-limit", type=_positive_int, default=20)

    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument("--json", action="store_true")
    output_group.add_argument("--llm-json", action="store_true")

    parser.add_argument("--schema", action="store_true")
    parser.add_argument("--mode", choices=("cli", "rpc"), default="cli")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    input_stream = sys.stdin if stdin is None else stdin
    output_stream = sys.stdout if stdout is None else stdout
    error_stream = sys.stderr if stderr is None else stderr

    parser = build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:
        return _exit_code(exc.code)

    if args.schema:
        _print_json(get_schema_document(), stdout=output_stream)
        return 0

    if args.mode == "rpc":
        return run_rpc(stdin=input_stream, stdout=output_stream)

    missing = [
        flag
        for flag, value in (
            ("--origin", args.origin),
            ("--destination", args.destination),
            ("--depart-start", args.depart_start),
            ("--depart-end", args.depart_end),
        )
        if value is None
    ]
    if missing:
        return _parser_error(
            parser,
            f"missing required args for search: {', '.join(missing)}",
            stderr=error_stream,
        )

    try:
        request = SearchRequest(
            origin=args.origin,
            destination=args.destination,
            depart_start=args.depart_start,
            depart_end=args.depart_end,
            trip_type=args.trip_type,
            stay_min=args.stay_min,
            stay_max=args.stay_max,
            adults=args.adults,
            children=args.children,
            infants=args.infants,
            cabin=args.cabin,
            currency=args.currency,
            locale=args.locale,
            market=args.market,
            nonstop=args.nonstop,
            max_budget=args.max_budget,
            planner_limit=args.planner_limit,
        )
        payload = search_flights(request)
    except (FlightLiveError, ValueError) as exc:
        print(f"error: {exc}", file=error_stream)
        return 1

    if args.json:
        _print_json(serialize_results(payload), stdout=output_stream)
    elif args.llm_json:
        _print_json(payload, stdout=output_stream)
    else:
        _print_human(payload["results"], stdout=output_stream)
    return 0


def _iso_date(raw: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be YYYY-MM-DD") from exc


def _positive_int(raw: str) -> int:
    value = int(raw)
    if value < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return value


def _non_negative_int(raw: str) -> int:
    value = int(raw)
    if value < 0:
        raise argparse.ArgumentTypeError("must be >= 0")
    return value


def _print_json(payload: object, *, stdout: TextIO) -> None:
    print(json.dumps(payload, ensure_ascii=False), file=stdout)


def _print_human(results: Sequence[dict[str, object]], *, stdout: TextIO) -> None:
    for item in results:
        depart = item.get("depart_date")
        ret = item.get("return_date")
        effective_price = item.get("effective_price")
        currency = item.get("currency")
        score = item.get("score")
        nonstop = "nonstop" if item.get("nonstop") else "stops"
        print(
            f"{item.get('origin')}->{item.get('destination')} | "
            f"{depart}->{ret} | {effective_price} {currency} | {nonstop} | score={score}",
            file=stdout,
        )


def _exit_code(code: object) -> int:
    return code if isinstance(code, int) else 1


def _parser_error(parser: argparse.ArgumentParser, message: str, *, stderr: TextIO) -> int:
    parser.print_usage(stderr)
    print(f"{parser.prog}: error: {message}", file=stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
