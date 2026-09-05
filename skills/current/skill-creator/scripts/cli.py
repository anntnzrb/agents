#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["PyYAML>=6.0"]
# ///
"""Cross-platform dispatcher for skill-creator utilities."""

from __future__ import annotations

import argparse
import runpy
import sys
from pathlib import Path
from typing import cast

SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"

COMMANDS = {
    "aggregate-benchmark": SCRIPTS_DIR / "aggregate_benchmark.py",
    "generate-review": SKILL_DIR / "eval-viewer" / "generate_review.py",
    "package": SCRIPTS_DIR / "package_skill.py",
    "quick-validate": SCRIPTS_DIR / "quick_validate.py",
    "improve-description": SCRIPTS_DIR / "improve_description.py",
    "run-eval": SCRIPTS_DIR / "run_eval.py",
    "run-loop": SCRIPTS_DIR / "run_loop.py",
    "generate-report": SCRIPTS_DIR / "generate_report.py",
}


def _run_script(path: Path, args: list[str]) -> int:
    """Run one utility script with forwarded arguments."""
    sys.path.insert(0, str(SKILL_DIR))
    sys.path.insert(0, str(SCRIPTS_DIR))
    old_argv = sys.argv[:]
    sys.argv = [str(path), *args]
    try:
        _ = runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        if isinstance(code, int):
            return code
        print(code, file=sys.stderr)
        return 1
    finally:
        sys.argv = old_argv
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the dispatcher command-line parser."""
    parser = argparse.ArgumentParser(
        prog="cli.py",
        description="Skill Creator utility dispatcher.",
        add_help=False,
    )
    _ = parser.add_argument(
        "command",
        nargs="?",
        choices=sorted(COMMANDS),
        help="Utility to run",
    )
    _ = parser.add_argument(
        "args",
        nargs=argparse.REMAINDER,
        help="Arguments passed to the utility",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Dispatch one skill-creator utility."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in {"-h", "--help"}:
        print(
            "usage: cli.py {aggregate-benchmark,generate-review,package,"
            + "quick-validate,improve-description,run-eval,run-loop,generate-report}"
            + " [args...]\n",
        )
        print("Cross-platform:")
        print(
            "  uv run --script <skill-dir>/scripts/cli.py "
            + "aggregate-benchmark <workspace>/iteration-N --skill-name <name>",
        )
        print(
            "  uv run --script <skill-dir>/scripts/cli.py "
            + "generate-review <workspace> --skill-name <name>",
        )
        print(
            "  uv run --script <skill-dir>/scripts/cli.py "
            + "package <path-to-skill-folder>",
        )
        print("\nUse '<command> --help' for utility-specific flags.")
        return 0

    parser = build_parser()
    ns = parser.parse_args(argv)
    command = cast("object", ns.command)
    if not isinstance(command, str) or command not in COMMANDS:
        parser.error("missing command")
    return _run_script(COMMANDS[command], _script_args(ns))


def _script_args(ns: argparse.Namespace) -> list[str]:
    """Narrow the forwarded remainder arguments to a string list."""
    value = cast("object", ns.args)
    if not isinstance(value, list):
        message = "Dispatcher misconfiguration: remainder is not a list."
        raise TypeError(message)
    items = cast("list[object]", cast("object", value))
    return [item for item in items if isinstance(item, str)]


if __name__ == "__main__":
    raise SystemExit(main())
