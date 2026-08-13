#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11,<3.15"
# dependencies = [
#   "audioread>=3.0.1",
#   "librosa>=0.11.0",
#   "matplotlib>=3.8.0",
#   "numpy>=2.0.0",
#   "soundfile>=0.12.1",
# ]
# ///
from __future__ import annotations

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "lib"))

from vox_interpres.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
