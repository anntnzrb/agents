# /// script
# requires-python = ">=3.10"
# ///
"""Cross-platform dispatcher for bundled OpenAI documentation helpers."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
COMMANDS = {
    "codex-manual": SCRIPTS_DIR / "fetch-codex-manual.mjs",
    "latest-model": SCRIPTS_DIR / "resolve-latest-model-info.cjs",
}


def _print_help() -> None:
    print("usage: cli.py {codex-manual,latest-model} [args...]")
    print(
        "  uv run --script <skill-dir>/scripts/cli.py codex-manual",
    )
    print(
        "  uv run --script <skill-dir>/scripts/cli.py latest-model",
    )


def main(argv: list[str] | None = None) -> int:
    """Run the selected Node.js helper and preserve its exit code."""
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help"}:
        _print_help()
        return 0

    script = COMMANDS.get(args[0])
    if script is None:
        print(f"unknown command: {args[0]}", file=sys.stderr)
        _print_help()
        return 2

    node = shutil.which("node")
    if node is None:
        print("node executable not found", file=sys.stderr)
        return 127

    result = subprocess.run(  # noqa: S603
        [node, str(script), *args[1:]],
        check=False,
        shell=False,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
