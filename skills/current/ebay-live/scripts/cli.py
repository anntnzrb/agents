# /// script
# requires-python = ">=3.14"
# dependencies = [
#   "curl-cffi>=0.13",
#   "firecrawl-py>=4",
#   "selectolax>=0.3.26",
#   "hypothesis>=6",
#   "jsonschema>=4.23",
# ]
# ///
"""Thin PEP 723 launcher for eBay live search."""

import sys
from pathlib import Path

_ = sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from ebay_live.cli import main  # noqa: E402 - lib path precedes local imports.

if __name__ == "__main__":
    raise SystemExit(main())
