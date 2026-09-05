# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Run the LiveBench CLI without installing the skill package."""

from __future__ import annotations

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "lib"))

from livebench.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
