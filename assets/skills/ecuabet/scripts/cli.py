#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "httpx>=0.27,<1.0",
#   "understatapi>=0.6.1,<1.0",
# ]
# ///
"""Cross-platform dispatcher for Ecuabet match-intel helpers."""

from __future__ import annotations

import argparse
import runpy
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"

FEEDS = {
    "ecuabet": SCRIPTS_DIR / "ecuabet.py",
    "sofascore": SCRIPTS_DIR / "sofascore.py",
    "espn": SCRIPTS_DIR / "espn.py",
    "open-meteo": SCRIPTS_DIR / "open_meteo.py",
    "understat": SCRIPTS_DIR / "understat.py",
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


def _print_help() -> None:
    print(
        "usage: cli.py run [args...] | feed {ecuabet,sofascore,espn,open-meteo,understat} [args...]\n"
    )
    print("Cross-platform:")
    print(
        "  uv run --script <skill-dir>/scripts/cli.py run <match_id_or_url> --ecuabet <id> --no-raw --compact"
    )
    print(
        "  uv run --script <skill-dir>/scripts/cli.py feed ecuabet <match_id_or_url> --no-raw --compact"
    )
    print("\nUse 'run --help' or 'feed <name> --help' for helper-specific flags.")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in {"-h", "--help"}:
        _print_help()
        return 0

    command, rest = argv[0], argv[1:]
    if command == "run":
        return _run_script(SCRIPTS_DIR / "main.py", rest)
    if command == "feed":
        if not rest or rest[0] in {"-h", "--help"}:
            print(
                "usage: cli.py feed {ecuabet,sofascore,espn,open-meteo,understat} [args...]"
            )
            return 0
        feed, feed_args = rest[0], rest[1:]
        if feed not in FEEDS:
            print(f"error: unknown feed '{feed}'", file=sys.stderr)
            return 2
        return _run_script(FEEDS[feed], feed_args)

    parser = argparse.ArgumentParser(prog="cli.py")
    parser.error("command must be 'run' or 'feed'")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
