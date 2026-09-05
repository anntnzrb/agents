"""Command-line interface for flight-live search."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from typing import TYPE_CHECKING, TextIO, cast

if TYPE_CHECKING:
    from collections.abc import Sequence

from .models import (
    CabinClass,
    FlightLiveError,
    MissingExecutableError,
    SearchRequest,
    TripType,
)
from .protocol import get_schema_document, search_flights, serialize_results
from .rpc import run_rpc


def build_parser() -> argparse.ArgumentParser:
    """Build the flight-live command-line parser."""
    parser = argparse.ArgumentParser(
        prog="flight-live",
        description="Read-only flight search (Kiwi web scrape planner).",
    )
    _ = parser.add_argument("--origin", help="Origin city/airport term or IATA.")
    _ = parser.add_argument(
        "--destination", help="Destination city/airport term or IATA."
    )
    _ = parser.add_argument(
        "--depart-start",
        type=_iso_date,
        help="Departure window start (YYYY-MM-DD).",
    )
    _ = parser.add_argument(
        "--depart-end",
        type=_iso_date,
        help="Departure window end (YYYY-MM-DD).",
    )
    _ = parser.add_argument(
        "--trip-type",
        choices=("oneway", "roundtrip"),
        default="oneway",
    )
    _ = parser.add_argument("--stay-min", type=_non_negative_int)
    _ = parser.add_argument("--stay-max", type=_non_negative_int)
    _ = parser.add_argument("--adults", type=_positive_int, default=1)
    _ = parser.add_argument("--children", type=_non_negative_int, default=0)
    _ = parser.add_argument("--infants", type=_non_negative_int, default=0)
    _ = parser.add_argument(
        "--cabin",
        choices=("economy", "premium_economy", "business", "first"),
        default="economy",
    )
    _ = parser.add_argument("--currency", default="USD")
    _ = parser.add_argument("--locale", default="en")
    _ = parser.add_argument("--market", default="us")
    _ = parser.add_argument("--nonstop", action="store_true")
    _ = parser.add_argument("--max-budget", type=float)
    _ = parser.add_argument("--planner-limit", type=_positive_int, default=20)

    output_group = parser.add_mutually_exclusive_group()
    _ = output_group.add_argument("--json", action="store_true")
    _ = output_group.add_argument("--llm-json", action="store_true")

    _ = parser.add_argument("--schema", action="store_true")
    _ = parser.add_argument("--mode", choices=("cli", "rpc"), default="cli")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Run the flight-live command-line interface."""
    input_stream = sys.stdin if stdin is None else stdin
    output_stream = sys.stdout if stdout is None else stdout
    error_stream = sys.stderr if stderr is None else stderr

    parser = build_parser()
    args, code = _parse_args(parser, argv)
    if args is None:
        return code

    if _flag(args, "schema"):
        _print_json(get_schema_document(), stdout=output_stream)
        return 0

    if _req_str(args, "mode") == "rpc":
        return run_rpc(stdin=input_stream, stdout=output_stream)

    return _run_search(
        parser, args, output_stream=output_stream, error_stream=error_stream
    )


def _run_search(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    *,
    output_stream: TextIO,
    error_stream: TextIO,
) -> int:
    """Validate search args, run the search, and print results."""
    missing = [
        flag
        for flag, value in (
            ("--origin", _opt_str_or_none(args, "origin")),
            ("--destination", _opt_str_or_none(args, "destination")),
            ("--depart-start", _opt_date_or_none(args, "depart_start")),
            ("--depart-end", _opt_date_or_none(args, "depart_end")),
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
            origin=_req_str(args, "origin"),
            destination=_req_str(args, "destination"),
            depart_start=_req_date(args, "depart_start"),
            depart_end=_req_date(args, "depart_end"),
            trip_type=cast("TripType", _req_str(args, "trip_type")),
            stay_min=_opt_int_or_none(args, "stay_min"),
            stay_max=_opt_int_or_none(args, "stay_max"),
            adults=_req_int(args, "adults"),
            children=_req_int(args, "children"),
            infants=_req_int(args, "infants"),
            cabin=cast("CabinClass", _req_str(args, "cabin")),
            currency=_req_str(args, "currency"),
            locale=_req_str(args, "locale"),
            market=_req_str(args, "market"),
            nonstop=_flag(args, "nonstop"),
            max_budget=_opt_float_or_none(args, "max_budget"),
            planner_limit=_req_int(args, "planner_limit"),
        )
        payload = search_flights(request)
    except MissingExecutableError as exc:
        print(f"error: {exc}", file=error_stream)
        return 127
    except (FlightLiveError, ValueError, TypeError) as exc:
        print(f"error: {exc}", file=error_stream)
        return 1

    if _flag(args, "json"):
        _print_json(serialize_results(payload), stdout=output_stream)
    elif _flag(args, "llm_json"):
        _print_json(payload, stdout=output_stream)
    else:
        _print_human(payload["results"], stdout=output_stream)
    return 0


def _parse_args(
    parser: argparse.ArgumentParser, argv: Sequence[str] | None
) -> tuple[argparse.Namespace | None, int]:
    """Parse argv, mapping parser exits to return codes."""
    try:
        return parser.parse_args(list(argv) if argv is not None else None), 0
    except SystemExit as exc:
        return None, _exit_code(exc.code)


def _req_str(args: argparse.Namespace, field: str) -> str:
    """Narrow a required string argument to a typed value."""
    value = cast("object", getattr(args, field))
    if not isinstance(value, str) or value == "":
        message = f"Missing required argument: {field}."
        raise ValueError(message)
    return value


def _req_date(args: argparse.Namespace, field: str) -> date:
    """Narrow a required date argument to a typed value."""
    value = cast("object", getattr(args, field))
    if not isinstance(value, date):
        message = f"Missing required argument: {field}."
        raise TypeError(message)
    return value


def _req_int(args: argparse.Namespace, field: str) -> int:
    """Narrow a required integer argument to a typed value."""
    value = cast("object", getattr(args, field))
    if not isinstance(value, int) or isinstance(value, bool):
        message = f"Invalid integer argument: {field}."
        raise TypeError(message)
    return value


def _flag(args: argparse.Namespace, field: str) -> bool:
    """Narrow a boolean flag to a typed value."""
    value = cast("object", getattr(args, field))
    return value if isinstance(value, bool) else False


def _opt_str_or_none(args: argparse.Namespace, field: str) -> str | None:
    """Narrow an optional string argument to a typed value."""
    value = cast("object", getattr(args, field))
    return value if isinstance(value, str) else None


def _opt_date_or_none(args: argparse.Namespace, field: str) -> date | None:
    """Narrow an optional date argument to a typed value."""
    value = cast("object", getattr(args, field))
    return value if isinstance(value, date) else None


def _opt_int_or_none(args: argparse.Namespace, field: str) -> int | None:
    """Narrow an optional integer argument to a typed value."""
    value = cast("object", getattr(args, field))
    return value if isinstance(value, int) else None


def _opt_float_or_none(args: argparse.Namespace, field: str) -> float | None:
    """Narrow an optional float argument to a typed value."""
    value = cast("object", getattr(args, field))
    return value if isinstance(value, float) else None


def _iso_date(raw: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        message = "must be YYYY-MM-DD"
        raise argparse.ArgumentTypeError(message) from exc


def _positive_int(raw: str) -> int:
    value = int(raw)
    if value < 1:
        message = "must be >= 1"
        raise argparse.ArgumentTypeError(message)
    return value


def _non_negative_int(raw: str) -> int:
    value = int(raw)
    if value < 0:
        message = "must be >= 0"
        raise argparse.ArgumentTypeError(message)
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
            + f"{depart}->{ret} | {effective_price} {currency} | "
            + f"{nonstop} | score={score}",
            file=stdout,
        )


def _exit_code(code: object) -> int:
    return code if isinstance(code, int) else 1


def _parser_error(
    parser: argparse.ArgumentParser,
    message: str,
    *,
    stderr: TextIO,
) -> int:
    parser.print_usage(stderr)
    print(f"{parser.prog}: error: {message}", file=stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
