"""Expose the skill library to local test runners."""

from __future__ import annotations

import sys
from pathlib import Path

LIB_DIR = Path(__file__).resolve().parent.parent / "lib"
sys.path.insert(0, str(LIB_DIR))
