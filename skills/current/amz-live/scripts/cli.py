# /// script
# requires-python = ">=3.14"
# dependencies = [
#   "httpx2>=2.13.1",
#   "selectolax>=0.3.26",
#   "hypothesis>=6",
# ]
# ///
"""Thin PEP 723 entrypoint for the amz-live CLI."""

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
_ = sys.path.insert(0, str(SKILL_DIR / "lib"))

from amz_live.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
