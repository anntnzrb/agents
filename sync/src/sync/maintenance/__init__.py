# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Scheduled maintenance jobs and external service controls."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import TYPE_CHECKING

from sync.maintenance.amp_runner import update_amp_runner
from sync.maintenance.npm_cache import clean_npm_cache
from sync.maintenance.paseo import update_paseo
from sync.maintenance.t3 import run_t3

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    "clean_npm_cache",
    "run_job",
    "run_t3",
    "update_amp_runner",
    "update_paseo",
]


def build_job_parser() -> argparse.ArgumentParser:
    """Build argument parser for sync job subcommands."""
    parser = argparse.ArgumentParser(
        prog="sync job",
        description=(
            "Run scheduled maintenance jobs driven by the machine configuration."
        ),
    )
    sub = parser.add_subparsers(dest="job", required=True)

    amp_p = sub.add_parser(
        "amp-runner-update",
        help="Restart Amp runner onto newest cached release when behind and idle.",
    )
    _ = amp_p.add_argument(
        "--service", required=True, help="Service unit name or launchd label"
    )
    _ = amp_p.add_argument(
        "--log-file", required=True, type=Path, help="Path to runner log file"
    )

    paseo_p = sub.add_parser(
        "paseo-update",
        help="Restart Paseo daemon onto newest release when behind and idle.",
    )
    _ = paseo_p.add_argument(
        "--service", required=True, help="Service unit name or launchd label"
    )

    _ = sub.add_parser(
        "npm-cache-clean",
        help="Empty npm cache while respecting npm-tools locks.",
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
        case "amp-runner-update":
            service_attr: object = getattr(args, "service", "")
            log_attr: object = getattr(args, "log_file", "")
            service = str(service_attr)
            log_file = Path(str(log_attr))
            return update_amp_runner(service, log_file)
        case "paseo-update":
            service_attr = getattr(args, "service", "")
            return update_paseo(str(service_attr))
        case "npm-cache-clean":
            return clean_npm_cache()
        case _:
            return 2
