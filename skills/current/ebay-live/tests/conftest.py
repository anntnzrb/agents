"""Import the skill package from its source tree."""

import sys
from pathlib import Path

_ = sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
