# Copyright 2026 Vals-live contributors.
"""Public vals-live CLI with one compact JSON object per invocation."""

from __future__ import annotations

import argparse
import sys
from typing import TextIO

from .commands import CommandError, dispatch
from .contracts import compact, failure, success
from .diagnostics import redact

COMMANDS = (
    "catalog",
    "models",
    "model",
    "benchmark",
    "compare",
    "catalog-diff",
    "diagnose",
    "schema",
    "refresh",
    "snapshot",
)
_INTERNAL_ERRORS = (Exception,)


class UsageError(RuntimeError):
    """Represent command-line syntax and configuration errors."""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise UsageError(message)

    def exit(self, _status: int = 0, message: str | None = None) -> None:
        raise UsageError((message or "").strip() or "help requested")


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--help",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Show this help as a JSON usage response.",
    )
    parser.add_argument(
        "--snapshot",
        default=argparse.SUPPRESS,
        help="Use this explicit historical source snapshot.",
    )
    parser.add_argument(
        "--allow-stale",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Serve a matching cache artifact only after refresh failure.",
    )
    parser.add_argument(
        "--cache-dir",
        default=argparse.SUPPRESS,
        help="Override the platform/XDG cache directory.",
    )
    parser.add_argument(
        "--release",
        default=argparse.SUPPRESS,
        help="Exact source-defined Vals version or snapshot identity.",
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the parser for compact JSON command invocations."""
    parser = _Parser(
        prog="vals-live",
        add_help=False,
        description="Discover and compare official Vals benchmark data.",
    )
    _common(parser)
    sub = parser.add_subparsers(dest="command")
    commands = {
        "catalog": "Discover the runtime Vals benchmark catalog.",
        "models": "Discover Vals models and variants.",
        "model": "Show one exact Vals model.",
        "benchmark": "Show one exact Vals benchmark.",
        "compare": "Compare selected Vals model rows with conservative gates.",
        "catalog-diff": "Diff two explicit catalog snapshots.",
        "diagnose": "Inspect extraction, drift, provenance, and value statuses.",
        "schema": "Describe the stable vals-live JSON contract.",
        "refresh": "Refresh and retain immutable official source bytes.",
        "snapshot": "Materialize an explicit historical snapshot manifest.",
    }
    for name, help_text in commands.items():
        child = sub.add_parser(name, add_help=False, help=help_text)
        _common(child)
        if name == "model":
            child.add_argument("--model", required=True)
        elif name == "benchmark":
            child.add_argument("--benchmark", required=True)
        elif name == "compare":
            child.add_argument(
                "--models", required=True, help="Comma-separated exact model IDs/names."
            )
            child.add_argument(
                "--benchmarks",
                default=None,
                help="Comma-separated exact benchmark IDs/names.",
            )
        elif name == "catalog-diff":
            child.add_argument("--left", default=None)
            child.add_argument("--right", default=None)
            child.add_argument("paths", nargs="*")
    return parser


def _args(argv: list[str] | None) -> argparse.Namespace:
    parser = build_parser()
    values = parser.parse_args(argv)
    if not values.command and not getattr(values, "help", False):
        msg = "a command is required"
        raise UsageError(msg)
    # Defaults belong here so subparser SUPPRESS does not erase global options.
    for name, value in (
        ("help", False),
        ("snapshot", None),
        ("allow_stale", False),
        ("cache_dir", None),
        ("release", None),
        ("model", None),
        ("benchmark", None),
        ("models", None),
        ("benchmarks", None),
        ("left", None),
        ("right", None),
        ("paths", []),
    ):
        if not hasattr(values, name):
            setattr(values, name, value)
    return values


def _help_payload(command: str | None) -> dict[str, object]:
    selected = command if command in COMMANDS else "<command>"
    return success(
        "help",
        {
            "usage": f"vals-live {selected} [options]"
            if command in COMMANDS
            else "vals-live <command> [options]",
            "commands": list(COMMANDS),
        },
    )


def main(
    argv: list[str] | None = None,
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Run one command and emit exactly one compact JSON object."""
    del stderr
    out = stdout or sys.stdout
    command = "unknown"
    try:
        args = _args(argv)
        command = str(args.command) if args.command else "help"
        payload = _help_payload(args.command) if args.help else dispatch(args)
        print(compact(payload), file=out)
        return 0 if payload.get("ok", False) else 1
    except UsageError as exc:
        payload = failure(command, "USAGE", str(exc), {})
        print(compact(payload), file=out)
        return 2
    except CommandError as exc:
        payload = failure(command, exc.code, str(exc), redact(exc.details))
        print(compact(payload), file=out)
        return 2 if exc.code == "SNAPSHOT_INVALID" else 1
    except _INTERNAL_ERRORS as exc:
        payload = failure(
            command,
            "INTERNAL_ERROR",
            "The Vals command failed unexpectedly.",
            redact({"exception_type": type(exc).__name__, "reason": str(exc)}),
        )
        print(compact(payload), file=out)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
