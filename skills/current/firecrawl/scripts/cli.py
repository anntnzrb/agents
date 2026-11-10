# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""Run the pinned Firecrawl CLI release through bun."""

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

PIN = Path(__file__).resolve().parents[1] / "UPSTREAM.json"


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
    """Delegate arguments to the pinned CLI and preserve its exit code."""
    if argv and argv[0] == "--":
        argv = argv[1:]
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
        [bun, "x", f"firecrawl-cli@{version}", *argv], shell=False, check=False
    )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
