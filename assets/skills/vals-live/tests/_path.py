# Copyright 2026 Vals-live contributors.
# ruff: noqa: INP001
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
FIXTURES = ROOT / "tests" / "fixtures"
