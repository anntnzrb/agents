#!/usr/bin/env -S uv run --script
# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
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

SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"
COMMANDS = {
    "aggregate-benchmark": SCRIPTS_DIR / "aggregate_benchmark.py",
    "gates": SCRIPTS_DIR / "gates.py",
    "generate-review": SKILL_DIR / "eval-viewer" / "generate_review.py",
    "package": SCRIPTS_DIR / "package_skill.py",
    "quick-validate": SCRIPTS_DIR / "quick_validate.py",
    "improve-description": SCRIPTS_DIR / "improve_description.py",
    "run-eval": SCRIPTS_DIR / "run_eval.py",
    "run-loop": SCRIPTS_DIR / "run_loop.py",
    "generate-report": SCRIPTS_DIR / "generate_report.py",
}

# Example invocations shown by --help; the dispatcher prefix is added there.
_HELP_EXAMPLES = (
    "aggregate-benchmark <workspace>/iteration-N --skill-name <name>",
    "gates <path-to-skill-folder> [--tests]",
    "generate-review <workspace> --skill-name <name>",
    "package <path-to-skill-folder>",
)


def _run_script(path: Path, args: list[str]) -> int:
    sys.path.insert(0, str(SKILL_DIR))
    sys.path.insert(0, str(SCRIPTS_DIR))
    old_argv = sys.argv[:]
    sys.argv = [str(path), *args]
    try:
        runpy.run_path(str(path), run_name="__main__")
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
    """Build the dispatcher argument parser."""
    parser = argparse.ArgumentParser(
        prog="cli.py",
        description="Skill Creator utility dispatcher.",
        add_help=False,
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=sorted(COMMANDS),
        help="Utility to run",
    )
    parser.add_argument(
        "args",
        nargs=argparse.REMAINDER,
        help="Arguments passed to the utility",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Dispatch one skill-creator utility; return its exit code."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in {"-h", "--help"}:
        commands = ",".join(sorted(COMMANDS))
        print(f"usage: cli.py {{{commands}}} [args...]\n")
        print("Cross-platform:")
        for example in _HELP_EXAMPLES:
            print(f"  uv run --script <skill-dir>/scripts/cli.py {example}")
        print("\nUse '<command> --help' for utility-specific flags.")
        return 0
    parser = build_parser()
    ns = parser.parse_args(argv)
    if ns.command is None:
        parser.error("missing command")
    return _run_script(COMMANDS[ns.command], ns.args)


if __name__ == "__main__":
    raise SystemExit(main())
