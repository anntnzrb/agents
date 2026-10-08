# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Scheduled maintenance jobs."""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

from sync.maintenance.npm_cache import clean_npm_cache
from sync.maintenance.refresh_packages import refresh_packages

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["build_job_parser", "clean_npm_cache", "run_job"]


def build_job_parser() -> argparse.ArgumentParser:
    """Build argument parser for sync job subcommands."""
    parser = argparse.ArgumentParser(
        prog="sync job",
        description=(
            "Run scheduled maintenance jobs driven by the machine configuration."
        ),
    )
    sub = parser.add_subparsers(dest="job", required=True)
    _ = sub.add_parser(
        "npm-cache-clean",
        help="Empty npm cache while respecting npm-tools locks.",
    )
    _ = sub.add_parser(
        "refresh-packages",
        help="Refresh cached harness and tool packages without waiting on busy locks.",
    )
    return parser


def run_job(argv: Sequence[str]) -> int:
    """Dispatch scheduled maintenance jobs."""
    parser = build_job_parser()
    try:
        args = parser.parse_args(list(argv))
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2

    job: object = getattr(args, "job", None)
    match job:
        case "npm-cache-clean":
            return clean_npm_cache()
        case "refresh-packages":
            return refresh_packages()
        case _:
            return 2
