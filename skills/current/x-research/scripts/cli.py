# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Run x-research without installing the skill package."""
# ruff: noqa: CPY001

from __future__ import annotations

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "lib"))

from x_research.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
