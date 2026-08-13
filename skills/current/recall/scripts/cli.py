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

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from session_finder import (  # pyright: ignore[reportMissingImports]
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
    parser.add_argument("query", nargs="+", metavar="QUERY")
    parser.add_argument("--limit", type=positive_int, default=10, metavar="N")
    parser.add_argument(
        "--harness",
        action="append",
        choices=ALL_HARNESSES,
        metavar="HARNESS",
        help="search only this harness (repeatable)",
    )
    parser.add_argument(
        "--root",
        action="append",
        metavar="HARNESS=PATH",
        help="replace one harness's default roots (repeatable)",
    )
    return parser.parse_args()


def main() -> int:
    """Search sessions and return the documented status."""
    args = arguments()
    try:
        config = build_config(args.harness, args.root)
        records = search(config, args.query, args.limit)
    except ConfigurationError as error:
        sys.stderr.write(f"session-finder: {error}\n")
        return 2
    payload = json.dumps(records, ensure_ascii=False, separators=(",", ":"))
    sys.stdout.write(f"{payload}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
