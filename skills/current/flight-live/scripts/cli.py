# /// script
# requires-python = ">=3.11,<3.15"
# dependencies = []
# ///
from __future__ import annotations

import os
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "lib"))


def _load_simple_env(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if not key or any(char.isspace() for char in key):
            continue
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_simple_env(SKILL_DIR / ".env")

from flight_live.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
