#!/usr/bin/env -S uv run --script
# Copyright (c) 2026
# /// script
# requires-python = ">=3.12"
# dependencies = ["zstandard>=0.23,<1"]
# ///

"""Find saved sessions across supported coding harnesses."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import cast

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from session_finder import (
    ALL_HARNESSES,
    ConfigurationError,
    build_config,
    search,
)


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
    value = cast("object", getattr(args, field))
    if value is None:
        return None
    items = cast("list[object]", value)
    return [item for item in items if isinstance(item, str)]


def main() -> int:
    """Search sessions and return the documented status."""
    args = arguments()
    query = _optional_str_list(args, "query") or []
    limit_value = cast("object", args.limit)
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
