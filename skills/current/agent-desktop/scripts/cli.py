# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""Run the agent-desktop release pinned in this skill's UPSTREAM.json."""

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

PIN = Path(__file__).resolve().parents[1] / "UPSTREAM.json"
PACKAGE = "agent-desktop"

HELP = f"""agent-desktop wrapper

Usage:
  uv run --script <skill-dir>/scripts/cli.py <agent-desktop-args>...

Delegates to:
  bun x {PACKAGE}@<version> <agent-desktop-args>...

<version> is the `release` in {PIN.name}, without its leading `v`.
Use `help` or `<command> --help` for agent-desktop's own help.

Examples:
  uv run --script <skill-dir>/scripts/cli.py status
  uv run --script <skill-dir>/scripts/cli.py skills get desktop
  uv run --script <skill-dir>/scripts/cli.py snapshot --app Finder -i
"""


def pinned_version() -> str | None:
    """Return the npm version for the pinned release, or None if unreadable."""
    try:
        raw: object = json.loads(PIN.read_text(encoding="utf-8"))  # pyright: ignore[reportAny] - narrowed by match
    except OSError, ValueError:
        return None
    match raw:
        case {"release": str(release)} if release.removeprefix("v"):
            return release.removeprefix("v")
        case _:
            return None


def run(argv: Sequence[str]) -> int:
    """Delegate to the pinned agent-desktop through bun, preserving its exit code."""
    if argv and argv[0] == "--":
        argv = argv[1:]
    if not argv or argv[0] in {"-h", "--help"}:
        print(HELP)
        return 0
    version = pinned_version()
    if version is None:
        print(f"error: no string `release` in {PIN}", file=sys.stderr)
        return 2
    bun = shutil.which("bun")
    if bun is None:
        print("error: required executable not found: bun", file=sys.stderr)
        print("Install bun: https://bun.sh", file=sys.stderr)
        return 127
    completed = subprocess.run(
        [bun, "x", f"{PACKAGE}@{version}", *argv], shell=False, check=False
    )
    return completed.returncode


def main() -> int:
    """Run agent-desktop with the process arguments."""
    return run(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
