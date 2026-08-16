#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///

"""Native Codex PreToolUse(Bash) bridge that rewrites commands through rtk.

Reads one Codex hook JSON payload from stdin and, when `rtk rewrite`
produces a changed command, emits the documented PreToolUse rewrite
shape (`permissionDecision: "allow"` plus `updatedInput.command`).
Every other case fails open: no stdout and exit 0, so Codex runs the
original command unchanged.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys

REWRITE_TIMEOUT_SECONDS = 3.0
SUCCESS_EXIT_CODES = (0, 3)


def read_input() -> object:
    try:
        raw = sys.stdin.read().strip()
        if not raw:
            return None
        return json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def rewrite(command: str) -> str | None:
    if shutil.which("rtk") is None:
        return None

    try:
        result = subprocess.run(
            ["rtk", "rewrite", command],
            capture_output=True,
            text=True,
            timeout=REWRITE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, UnicodeDecodeError, subprocess.TimeoutExpired):
        return None

    if result.returncode not in SUCCESS_EXIT_CODES:
        return None

    rewritten = result.stdout.strip()
    if not rewritten or rewritten == command:
        return None
    return rewritten


def main() -> None:
    payload = read_input()
    if not isinstance(payload, dict):
        return

    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return

    command = tool_input.get("command")
    if not isinstance(command, str) or not command:
        return

    rewritten = rewrite(command)
    if rewritten is None:
        return

    sys.stdout.write(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "allow",
                    "updatedInput": {"command": rewritten},
                }
            },
            separators=(",", ":"),
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
