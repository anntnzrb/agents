# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""Run the pinned agent-browser release via bun."""

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
    """Read the npm version from the release pin."""
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
    """Pass arguments to the pinned executable and return its exit code."""
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
    # The postinstall downloads the platform binary when it is not bundled.
    return subprocess.run(
        [bun, "x", "--trust", f"agent-browser@{version}", *argv],
        shell=False,
        check=False,
    ).returncode


def main() -> int:
    """Run agent-browser with the process arguments."""
    return run(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
