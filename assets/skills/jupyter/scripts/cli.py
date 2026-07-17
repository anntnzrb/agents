# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "nbformat>=5.9",
#   "nbclient>=0.8",
#   "nbconvert>=7.0",
# ]
# ///
"""Cross-platform dispatcher for Jupyter notebook helpers."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"
NB = SCRIPTS_DIR / "nb.py"
VALIDATE = SCRIPTS_DIR / "validate.py"


def _run_script(path: Path, args: list[str]) -> int:
    sys.path.insert(0, str(SCRIPTS_DIR))
    old_argv = sys.argv[:]
    sys.argv = [str(path), *args]
    try:
        runpy.run_path(str(path), run_name="__main__")
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
    """Dispatch to the selected notebook helper."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in {"-h", "--help"}:
        print(
            "usage: cli.py "
            "{inspect,show,execute,validate,convert,clear,grep} [args...]\n",
        )
        print("Cross-platform:")
        print("  uv run --script <skill-dir>/scripts/cli.py inspect notebook.ipynb")
        print("  uv run --script <skill-dir>/scripts/cli.py execute notebook.ipynb -i")
        print("  uv run --script <skill-dir>/scripts/cli.py validate notebook.ipynb")
        print("\nAll commands except 'validate' delegate to scripts/nb.py.")
        return 0

    if argv[0] == "validate":
        return _run_script(VALIDATE, argv[1:])
    return _run_script(NB, argv)


if __name__ == "__main__":
    raise SystemExit(main())
