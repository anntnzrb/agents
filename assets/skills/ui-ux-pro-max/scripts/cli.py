# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Cross-platform public entrypoint for UI/UX Pro Max search."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
TARGET_MODULE = "search"


def main(argv: list[str] | None = None) -> int:
    """Delegate to the bundled search CLI while preserving its exit behavior."""
    args = sys.argv[1:] if argv is None else argv
    sys.path.insert(0, str(SCRIPTS_DIR))
    previous = sys.argv[:]
    sys.argv = ["cli.py", *args]
    try:
        runpy.run_module(TARGET_MODULE, run_name="__main__")
    except SystemExit as exc:
        if exc.code is None:
            return 0
        if isinstance(exc.code, int):
            return exc.code
        sys.stderr.write(f"{exc.code}\n")
        return 1
    finally:
        sys.argv = previous
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
