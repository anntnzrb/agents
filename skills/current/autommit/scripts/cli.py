# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "expression>=5.7.0",
# ]
# ///
"""Run the harness-agnostic autommit CLI."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from autommit.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
