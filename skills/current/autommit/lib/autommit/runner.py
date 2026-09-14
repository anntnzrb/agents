# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Deprecated direct runner. Use scripts/cli.py for the single-command workflow."""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

from autommit.errors import AutommitError
from autommit.orchestrate import RunOptions, run_orchestrated

if TYPE_CHECKING:
    from collections.abc import Sequence

DEPRECATION = "scripts/run.py is deprecated; use scripts/cli.py [options]."


@dataclass(frozen=True, slots=True)
class ParsedModel:
    """Parsed model specification matching OMP / Pi notation (<provider>/<model>:<effort>)."""

    provider: str | None
    model_id: str
    effort: Literal["low", "medium", "high", "xhigh", "max"] | None


def parse_model_string(raw: str) -> ParsedModel:
    """Parse <provider>/<model>:<effort> format."""
    trimmed = raw.strip()
    provider: str | None = None
    effort: Literal["low", "medium", "high", "xhigh", "max"] | None = None

    if "/" in trimmed:
        provider, rest = trimmed.split("/", 1)
    else:
        rest = trimmed

    if ":" in rest:
        model_id, effort_str = rest.rsplit(":", 1)
        if effort_str in ("low", "medium", "high", "xhigh", "max"):
            effort = cast(
                'Literal["low", "medium", "high", "xhigh", "max"]', effort_str
            )
        else:
            model_id = rest
    else:
        model_id = rest

    return ParsedModel(provider=provider, model_id=model_id, effort=effort)


def build_parser() -> argparse.ArgumentParser:
    """Build the legacy direct runner command-line parser."""
    parser = argparse.ArgumentParser(
        prog="autommit-run",
        description="Deprecated direct runner. Use scripts/cli.py instead.",
    )
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument(
        "--scope", choices=["auto", "staged", "all"], default="auto", type=str
    )
    parser.add_argument(
        "--ogo",
        action="store_true",
        help="Use the OpenCode Go provider (reads OPENCODE_API_KEY).",
    )
    parser.add_argument(
        "--ozen",
        action="store_true",
        help="Use the OpenCode Zen keyless tier.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Model string in <provider>/<model>:<effort> format.",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default=None,
        help="Explicit API key (overrides environment variables).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=300.0,
        help="Inference HTTP timeout in seconds (default: 300.0).",
    )
    parser.add_argument("--context", action="append", default=[])
    return parser


def _legacy_api_key(args: argparse.Namespace) -> str | None:
    if args.api_key:
        return cast("str", args.api_key)
    if args.ogo:
        return os.environ.get("OPENCODE_API_KEY")
    if args.ozen:
        return "keyless"
    return os.environ.get("AUTOMMIT_API_KEY") or os.environ.get("OPENAI_API_KEY")


def run(argv: Sequence[str] | None = None) -> int:
    """Map legacy flags onto the shared orchestrator."""
    args = build_parser().parse_args(argv)
    sys.stderr.write(DEPRECATION + "\n")
    raw_model = args.model
    if not raw_model:
        raw_model = "muse-spark-1.3-contributor" if args.ogo else "big-pickle"
    parsed_model = parse_model_string(raw_model)
    options = RunOptions(
        repo=cast("Path", args.repo).resolve(),
        scope=cast('Literal["auto", "staged", "all"]', args.scope),
        context=tuple(cast("list[str]", args.context)),
        model=parsed_model.model_id,
        api_key=_legacy_api_key(args),
        timeout=float(cast("float", args.timeout)),
    )
    try:
        return run_orchestrated(options)
    except AutommitError as error:
        sys.stderr.write(f"Error [{error.code}]: {error.message}\n")
        return error.exit_code
