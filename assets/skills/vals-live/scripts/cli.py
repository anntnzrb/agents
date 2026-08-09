# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
# Copyright 2026 Vals-live contributors.
"""Run vals-live without installing a package."""

from __future__ import annotations

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "lib"))

from vals_live.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
