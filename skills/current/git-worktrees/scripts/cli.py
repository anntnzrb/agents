#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""Run the local raw-Git worktree lifecycle CLI."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from git_worktrees.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
