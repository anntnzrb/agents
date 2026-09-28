# Copyright 2026 Vals-live contributors.
"""Public vals-live CLI with one compact JSON object per invocation."""

import argparse
import sys
from collections.abc import Mapping
from typing import NoReturn, TextIO, TypeIs, override

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


def _is_mapping(value: object) -> TypeIs[Mapping[str, object]]:
    return isinstance(value, Mapping)


class UsageError(RuntimeError):
    """Represent command-line syntax and configuration errors."""


class _Parser(argparse.ArgumentParser):
    @override
    def error(self, message: str) -> NoReturn:
        raise UsageError(message)

    @override
    def exit(
        self, status: int | str | None = 0, message: str | None = None
    ) -> NoReturn:
        del status
        raise UsageError((message or "").strip() or "help requested")


def _common(parser: argparse.ArgumentParser) -> None:
    _ = parser.add_argument(
        "--help",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Show this help as a JSON usage response.",
    )
    _ = parser.add_argument(
        "--snapshot",
        default=argparse.SUPPRESS,
        help="Use this explicit historical source snapshot.",
    )
    _ = parser.add_argument(
        "--allow-stale",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Serve a matching cache artifact only after refresh failure.",
    )
    _ = parser.add_argument(
        "--cache-dir",
        default=argparse.SUPPRESS,
        help="Override the platform/XDG cache directory.",
    )
    _ = parser.add_argument(
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
            _ = child.add_argument("--model", required=True)
        elif name == "benchmark":
            _ = child.add_argument("--benchmark", required=True)
        elif name == "compare":
            _ = child.add_argument(
                "--models", required=True, help="Comma-separated exact model IDs/names."
            )
            _ = child.add_argument(
                "--benchmarks",
                default=None,
                help="Comma-separated exact benchmark IDs/names.",
            )
        elif name == "catalog-diff":
            _ = child.add_argument("--left", default=None)
            _ = child.add_argument("--right", default=None)
            _ = child.add_argument("paths", nargs="*")
    return parser


def _args(argv: list[str] | None) -> argparse.Namespace:
    parser = build_parser()
    values = parser.parse_args(argv)
    cmd = getattr(values, "command", None)
    help_flag = getattr(values, "help", False)
    if not cmd and not help_flag:
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
        ("paths", list[str]()),
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
        raw_cmd = getattr(args, "command", None)
        cmd_str = str(raw_cmd) if isinstance(raw_cmd, str) and raw_cmd else None
        command = cmd_str or "help"
        wants_help = bool(getattr(args, "help", False))
        payload = _help_payload(cmd_str) if wants_help else dispatch(args)
        print(compact(payload), file=out)
        return 0 if payload.get("ok", False) else 1
    except UsageError as exc:
        payload = failure(command, "USAGE", str(exc), {})
        print(compact(payload), file=out)
        return 2
    except CommandError as exc:
        redacted_details = redact(exc.details)
        payload = failure(
            command,
            exc.code,
            str(exc),
            redacted_details if _is_mapping(redacted_details) else None,
        )
        print(compact(payload), file=out)
        return 2 if exc.code == "SNAPSHOT_INVALID" else 1
    except Exception as exc:  # noqa: BLE001 - process boundary catch to format JSON failure envelope
        redacted = redact({"exception_type": type(exc).__name__, "reason": str(exc)})
        payload = failure(
            command,
            "INTERNAL_ERROR",
            "The Vals command failed unexpectedly.",
            redacted if _is_mapping(redacted) else {},
        )
        print(compact(payload), file=out)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
