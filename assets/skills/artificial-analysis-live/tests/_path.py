"""Make the local skill library importable by tests."""

# ruff: noqa: CPY001, INP001
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
