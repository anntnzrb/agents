# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Public entrypoint for the macOS network repair skill."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from fixnet.network import main

if __name__ == "__main__":
    raise SystemExit(main())
