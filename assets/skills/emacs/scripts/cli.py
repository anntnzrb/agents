#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Cross-platform public entrypoint for emacsctl."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"
TARGET = SCRIPTS_DIR / "emacsctl.py"


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
        print("usage: cli.py [emacsctl-args...]\n")
        print("Cross-platform:")
        print("  uv run --script <skill-dir>/scripts/cli.py ping")
        print("  uv run --script <skill-dir>/scripts/cli.py face default")
        print("  uv run --script <skill-dir>/scripts/cli.py eval-file query.el --json")
        print("\nDelegates to scripts/emacsctl.py. Use 'help' for emacsctl subcommands if needed.")
        return 0
    return _run_script(argv)


if __name__ == "__main__":
    raise SystemExit(main())
