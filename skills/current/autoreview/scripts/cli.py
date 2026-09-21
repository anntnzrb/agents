# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Command-line entrypoint for AutoReview."""

from __future__ import annotations

import sys
from pathlib import Path

# Add lib/ to sys.path for local package execution
_LIB_DIR = Path(__file__).resolve().parent.parent / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from autoreview.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
