#!/usr/bin/env -S uv run --script
# Copyright (c) 2026
# /// script
# requires-python = ">=3.14"
# dependencies = ["zstandard>=0.23,<1"]
# ///

"""Find saved sessions across supported coding harnesses."""

import argparse
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, TypeIs

if TYPE_CHECKING:
    from collections.abc import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from session_finder import (
    ALL_HARNESSES,
    ConfigurationError,
    build_config,
    search,
)


_getattr: Callable[[object, str], object] = getattr


def _is_obj_list(val: object) -> TypeIs[list[object]]:
    return isinstance(val, list)


def positive_int(value: str) -> int:
    """Parse a positive result limit."""
    message = "limit must be a positive integer"
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(message) from error
    if number < 1:
        raise argparse.ArgumentTypeError(message)
    return number


def arguments() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Find saved sessions")
    _ = parser.add_argument("query", nargs="+", metavar="QUERY")
    _ = parser.add_argument("--limit", type=positive_int, default=10, metavar="N")
    _ = parser.add_argument(
        "--harness",
        action="append",
        choices=ALL_HARNESSES,
        metavar="HARNESS",
        help="search only this harness (repeatable)",
    )
    _ = parser.add_argument(
        "--root",
        action="append",
        metavar="HARNESS=PATH",
        help="replace one harness's default roots (repeatable)",
    )
    return parser.parse_args()


def _optional_str_list(args: argparse.Namespace, field: str) -> list[str] | None:
    """Narrow a repeatable argparse option to a string list."""
    value = _getattr(args, field)
    if not _is_obj_list(value):
        return None
    return [item for item in value if isinstance(item, str)]


def main() -> int:
    """Search sessions and return the documented status."""
    args = arguments()
    query = _optional_str_list(args, "query") or []
    limit_value = _getattr(args, "limit")
    limit = limit_value if isinstance(limit_value, int) else 10
    try:
        config = build_config(
            _optional_str_list(args, "harness"), _optional_str_list(args, "root")
        )
        records = search(config, query, limit)
    except ConfigurationError as error:
        _ = sys.stderr.write(f"session-finder: {error}\n")
        return 2
    payload = json.dumps(records, ensure_ascii=False, separators=(",", ":"))
    _ = sys.stdout.write(f"{payload}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
