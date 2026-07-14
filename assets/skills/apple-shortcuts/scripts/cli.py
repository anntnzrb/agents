#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Cross-platform dispatcher for Apple Shortcuts helpers."""

from __future__ import annotations

import argparse
import runpy
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"

COMMANDS = {
    "search": SCRIPTS_DIR / "search_expert_chunks.py",
    "blueprint": SCRIPTS_DIR / "make_blueprint.py",
    "inspect": SCRIPTS_DIR / "inspect_local_shortcuts.py",
}


def _run_script(path: Path, args: list[str]) -> int:
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
    parser = argparse.ArgumentParser(
        prog="cli.py",
        description="Apple Shortcuts helper dispatcher.",
        add_help=False,
    )
    parser.add_argument("command", nargs="?", choices=sorted(COMMANDS), help="Helper to run")
    parser.add_argument("args", nargs=argparse.REMAINDER, help="Arguments passed to the helper")
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in {"-h", "--help"}:
        print("usage: cli.py {search,blueprint,inspect} [args...]\n")
        print("Cross-platform:")
        print("  uv run --script <skill-dir>/scripts/cli.py search --query 'ask for input action'")
        print("  uv run --script <skill-dir>/scripts/cli.py blueprint --goal '...' --devices 'iPhone,Mac'")
        print("  uv run --script <skill-dir>/scripts/cli.py inspect --visible-only")
        print("\nUse '<command> --help' for helper-specific flags.")
        return 0

    parser = build_parser()
    ns = parser.parse_args(argv)
    if ns.command is None:
        parser.error("missing command")
    return _run_script(COMMANDS[ns.command], ns.args)


if __name__ == "__main__":
    raise SystemExit(main())
