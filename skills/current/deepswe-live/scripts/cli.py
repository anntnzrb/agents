# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
# ruff: noqa: CPY001
"""Run the DeepSWE metrics CLI without installing the skill package."""

from __future__ import annotations

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "lib"))

from deepswe.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
