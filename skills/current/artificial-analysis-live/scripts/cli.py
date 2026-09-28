# /// script
# requires-python = ">=3.14"
# dependencies = ["cryptography>=44"]
# ///
"""Run the Artificial Analysis CLI without installing the skill package."""

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "lib"))

from artificial_analysis.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
