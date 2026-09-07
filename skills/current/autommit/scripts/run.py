# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Executable entrypoint for direct autommit runner."""

from __future__ import annotations

import sys
from pathlib import Path

LIB_PATH = Path(__file__).resolve().parent.parent / "lib"
if str(LIB_PATH) not in sys.path:
    sys.path.insert(0, str(LIB_PATH))

# ruff: noqa: E402
from autommit.runner import run

if __name__ == "__main__":
    sys.exit(run())
