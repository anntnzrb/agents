#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14,<3.15"
# dependencies = [
#   "httpx>=0.28.1",
#   "selectolax>=0.3.26",
# ]
# ///
from __future__ import annotations

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "lib"))

from amz_live.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
