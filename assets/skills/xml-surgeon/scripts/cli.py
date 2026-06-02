#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "lxml>=5.3.0",
# ]
# ///
"""Cross-platform public entrypoint for xml-surgeon."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"
TARGET = SCRIPTS_DIR / "main.py"


def _run_script(args: list[str]) -> int:
    sys.path.insert(0, str(SCRIPTS_DIR))
    old_argv = sys.argv[:]
    sys.argv = [str(TARGET), *args]
    try:
        runpy.run_path(str(TARGET), run_name="__main__")
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


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in {"-h", "--help"}:
        print("usage: cli.py [xml-surgeon-args...]\n")
        print("Cross-platform:")
        print(
            "  uv run --script <skill-dir>/scripts/cli.py select --xpath \"//field[@name='arch']\" path/to/file.xml"
        )
        print(
            '  uv run --script <skill-dir>/scripts/cli.py set-attr --xpath "//field" --name string --value label --diff path/to/file.xml'
        )
        print(
            "\nDelegates to scripts/main.py. Use a subcommand with --help for XML CLI flags."
        )
        return 0
    return _run_script(argv)


if __name__ == "__main__":
    raise SystemExit(main())
