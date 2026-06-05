#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Public entrypoint for the Hammerspoon skill CLI.

Cross-platform:
    uv run --script <skill-dir>/scripts/cli.py status
    uv run --script <skill-dir>/scripts/cli.py docs search hs.window

Delegates to scripts/hsctl.py.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"
TARGET = SCRIPTS_DIR / "hsctl.py"


def _run_script(args: list[str]) -> int:
    sys.path.insert(0, str(SCRIPTS_DIR))
    old_argv = sys.argv[:]
    sys.argv = [str(TARGET), *args]
    try:
        runpy.run_path(str(TARGET), run_name="__main__")
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
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in {"-h", "--help"}:
        print("usage: cli.py <subcommand> [args...]")
        print()
        print("Runtime commands:")
        print("  status [--json]              Hammerspoon health, version, config dir")
        print("  doctor [--json]              status + Accessibility/MJConfigFile checks")
        print("  eval [--json] <lua>          evaluate Lua via hs CLI")
        print("  eval-file [--json] <path>    evaluate a Lua file via hs CLI")
        print("  reload [--json]              trigger hs.reload()")
        print("  windows [--json]             list all windows")
        print("  apps [--json]                list running applications")
        print("  screens [--json]             list displays")
        print("  hotkeys [--json]             list registered hotkeys")
        print("  spoons [--json]              list loaded Spoons")
        print("  config [--json]              show config directory")
        print()
        print("Docs commands:")
        print("  docs search <query> [--json]")
        print("  docs module <name> [--json]")
        print("  docs api <symbol> [--json]")
        print("  docs refresh [--if-needed]")
        print()
        print("Source commands:")
        print("  source search <pattern> [--json]")
        print("  source fetch [--if-needed]")
        print("  spoon search <query> [--json]")
        print("  spoon source <name> [--json]")
        print()
        print("Lua quality commands:")
        print("  lint <path> [--json]")
        print("  fmt --check <path> [--json]")
        print("  fmt --write <path> [--json]")
        print("  test <path> [--json]")
        print("  annotations status [--json]")
        print("  lsp-config print")
        print()
        print(
            "Delegates to scripts/hsctl.py. Use 'help' for hsctl subcommand details."
        )
        return 0
    return _run_script(argv)


if __name__ == "__main__":
    raise SystemExit(main())
