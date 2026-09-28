"""Pytest bootstrap for webpaste skill tests."""

import sys
from pathlib import Path

_ = sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
