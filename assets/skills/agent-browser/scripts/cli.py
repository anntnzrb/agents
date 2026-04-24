#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Cross-platform wrapper for agent-browser via nix flake."""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Sequence

FLAKE_REF = "github:numtide/llm-agents.nix#agent-browser"

HELP = f"""agent-browser wrapper

Usage:
  uv run --script <skill-dir>/scripts/cli.py <agent-browser-args>...

Delegates to:
  nix run {FLAKE_REF} -- <agent-browser-args>...

Examples:
  uv run --script <skill-dir>/scripts/cli.py open https://example.com
  uv run --script <skill-dir>/scripts/cli.py snapshot -i
  uv run --script <skill-dir>/scripts/cli.py close

Use `--` before an underlying argument that starts with `--` if your runner parses it.
"""


def missing_tool(name: str, install_hint: str) -> int:
    print(f"error: required executable not found: {name}", file=sys.stderr)
    print(install_hint, file=sys.stderr)
    return 127


def run(argv: Sequence[str]) -> int:
    if argv and argv[0] == "--":
        argv = argv[1:]

    if not argv or argv[0] in {"-h", "--help"}:
        print(HELP)
        return 0

    if shutil.which("nix") is None:
        return missing_tool(
            "nix",
            "Install Nix or run this skill on a host where `nix run github:numtide/llm-agents.nix#agent-browser -- ...` works.",
        )

    completed = subprocess.run(
        ["nix", "run", FLAKE_REF, "--", *argv],
        shell=False,
    )
    return completed.returncode


def main() -> int:
    return run(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
