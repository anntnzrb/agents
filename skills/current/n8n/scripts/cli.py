# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "httpx>=0.27",
# ]
# ///
"""Cross-platform public entrypoint for n8nctl."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"
TARGET = SCRIPTS_DIR / "n8nctl.py"


def _run_script(args: list[str]) -> int:
    sys.path.insert(0, str(SCRIPTS_DIR))
    old_argv = sys.argv[:]
    sys.argv = [str(TARGET), *args]
    try:
        _ = runpy.run_path(str(TARGET), run_name="__main__")
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        if isinstance(code, int):
            return code
        print(code, file=sys.stderr)
        return 1
    finally:
        sys.argv = old_argv
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run n8nctl with optional argument overrides."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in {"-h", "--help"}:
        print("usage: cli.py [n8nctl-args...]\n")
        print("Cross-platform:")
        print("  uv run --script <skill-dir>/scripts/cli.py list --limit 5")
        print("  uv run --script <skill-dir>/scripts/cli.py get <WORKFLOW_ID>")
        print("  uv run --script <skill-dir>/scripts/cli.py validate <WORKFLOW.json>")
        print("\nDelegates to scripts/n8nctl.py and preserves its exit behavior.")
        return 0
    return _run_script(argv)


if __name__ == "__main__":
    raise SystemExit(main())
