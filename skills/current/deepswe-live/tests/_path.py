"""Keep tests runnable from the repository root or this skill directory."""
# ruff: noqa: CPY001, INP001

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
LIB_DIR = SKILL_DIR / "lib"
if str(LIB_DIR) not in sys.path:
    sys.path.insert(0, str(LIB_DIR))
