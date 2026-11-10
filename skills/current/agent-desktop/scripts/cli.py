# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""Run the pinned agent-desktop release headless and unattended by default."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, TypeIs

if TYPE_CHECKING:
    from collections.abc import Sequence

PIN = Path(__file__).resolve().parents[1] / "UPSTREAM.json"
PACKAGE = "agent-desktop"
ATTENDED_ENV = "AGENT_DESKTOP_ATTENDED"
POLICY_EXIT = 2

# Global options that take a value, so their value is not the command name.
VALUE_OPTIONS = frozenset(
    {
        "--agent-id",
        "--screenshot",
        "--session",
        "--trace",
        "--wait-for",
        "--wait-for-gone",
        "--wait-timeout",
    }
)
# Commands that take focus or the foreground, or bypass this wrapper's checks.
ATTENDED_COMMANDS = frozenset({"focus-window", "mcp", "open-system-surface"})
# Per-command flags that bring an app forward or open a prompt.
ATTENDED_FLAGS = {
    "launch": frozenset({"activate"}),
    "permissions": frozenset({"guide", "request"}),
}
# Commands that send synthetic keystrokes to whatever app has focus unless scoped.
SCOPED_COMMANDS = frozenset({"press"})
SCOPE_FLAGS = frozenset({"app", "window-id"})

HELP = f"""agent-desktop wrapper

Usage:
  uv run --script <skill-dir>/scripts/cli.py <agent-desktop-args>...

Delegates to:
  bun x --trust {PACKAGE}@<version> <agent-desktop-args>...

<version> is the `release` in {PIN.name}, without its leading `v`.
Use `help` or `<command> --help` for agent-desktop's own help.

Unattended policy:
  Refuses --headed, {", ".join(sorted(ATTENDED_COMMANDS))},
  launch --activate, permissions --guide or --request, and press without
  --app or --window-id, including inside batch, with a POLICY_DENIED envelope
  and exit {POLICY_EXIT}. Set {ATTENDED_ENV}=1 only when the user allows
  interruptions for the current task.

Examples:
  uv run --script <skill-dir>/scripts/cli.py status
  uv run --script <skill-dir>/scripts/cli.py skills get desktop
  uv run --script <skill-dir>/scripts/cli.py snapshot --app Finder -i
"""


def pinned_version() -> str | None:
    """Return the npm version for the pinned release, or None if unreadable."""
    try:
        raw: object = json.loads(PIN.read_text(encoding="utf-8"))  # pyright: ignore[reportAny] - narrowed by match
    except OSError, ValueError:
        return None
    match raw:
        case {"release": str(release)} if release.removeprefix("v"):
            return release.removeprefix("v")
        case _:
            return None


def is_record(value: object) -> TypeIs[dict[str, object]]:
    """Narrow decoded JSON to an object; JSON object keys are always strings."""
    return isinstance(value, dict)


def is_list(value: object) -> TypeIs[list[object]]:
    """Narrow decoded JSON to an array."""
    return isinstance(value, list)


def split_command(argv: Sequence[str]) -> tuple[str | None, list[str], bool]:
    """Return the command, its arguments, and whether `--headed` was given."""
    command: str | None = None
    rest: list[str] = []
    headed = False
    skip_value = False
    for arg in argv:
        if arg == "--":
            break
        if skip_value:
            skip_value = False
        elif arg == "--headed" or arg.startswith("--headed="):
            headed = True
        elif command is None and arg in VALUE_OPTIONS:
            skip_value = True
        elif command is None and not arg.startswith("-"):
            command = arg
        elif command is not None:
            rest.append(arg)
    return command, rest, headed


def attended_reason(command: str, flags: frozenset[str]) -> str | None:
    """Name the attended behavior one command would trigger, if any."""
    if command in ATTENDED_COMMANDS:
        return command
    if command in SCOPED_COMMANDS and not flags & SCOPE_FLAGS:
        return f"{command} without --app or --window-id"
    hit = sorted(ATTENDED_FLAGS.get(command, frozenset()) & flags)
    return f"{command} --{hit[0]}" if hit else None


def entry_reason(entry: object) -> str | None:
    """Name the attended behavior one decoded batch entry would trigger."""
    if not is_record(entry):
        return None
    command, args = entry.get("command"), entry.get("args", {})
    if not isinstance(command, str) or not is_record(args):
        return None
    # Batch args use snake_case keys; a flag is set when its value is not off.
    flags = frozenset(
        key.replace("_", "-")
        for key, value in args.items()
        if value not in (None, False, "")
    )
    return attended_reason(command, flags)


def batch_reason(rest: Sequence[str]) -> str | None:
    """Name the first attended entry in a batch JSON argument, if any."""
    payload = next((arg for arg in rest if not arg.startswith("-")), None)
    if payload is None:
        return None
    try:
        entries: object = json.loads(payload)  # pyright: ignore[reportAny] - narrowed by is_list
    except ValueError:
        return None
    if not is_list(entries):
        return None
    reason = next(filter(None, map(entry_reason, entries)), None)
    return f"batch entry {reason}" if reason else None


def policy_violation(argv: Sequence[str]) -> tuple[str, str] | None:
    """Return the command and the attended behavior the arguments request."""
    command, rest, headed = split_command(argv)
    if headed:
        return command or "", "--headed"
    if command is None:
        return None
    if command == "batch":
        reason = batch_reason(rest)
    else:
        flags = frozenset(
            arg.removeprefix("--").partition("=")[0]
            for arg in rest
            if arg.startswith("--")
        )
        reason = attended_reason(command, flags)
    return (command, reason) if reason else None


def deny(command: str, reason: str) -> int:
    """Print a POLICY_DENIED envelope like agent-desktop's own refusals."""
    envelope = {
        "ok": False,
        "command": command,
        "error": {
            "code": "POLICY_DENIED",
            "message": f"{reason} can take focus or interrupt the user",
            "suggestion": (
                "Use a headless path: click menu items by ref instead of press, "
                "and launch without --activate. "
                f"Set {ATTENDED_ENV}=1 only if the user allows interruptions."
            ),
            "details": {"kind": "unattended_policy", "blocked": reason},
            "disposition": {"delivery": "not_delivered", "retry": "safe"},
        },
    }
    print(json.dumps(envelope))
    return POLICY_EXIT


def run(argv: Sequence[str]) -> int:
    """Delegate to the pinned agent-desktop through bun, preserving its exit code."""
    if argv and argv[0] == "--":
        argv = argv[1:]
    if not argv or argv[0] in {"-h", "--help"}:
        print(HELP)
        return 0
    if os.environ.get(ATTENDED_ENV) != "1" and (violation := policy_violation(argv)):
        return deny(*violation)
    version = pinned_version()
    if version is None:
        print(f"error: no string `release` in {PIN}", file=sys.stderr)
        return 2
    bun = shutil.which("bun")
    if bun is None:
        print("error: required executable not found: bun", file=sys.stderr)
        print("Install bun: https://bun.sh", file=sys.stderr)
        return 127
    # --trust runs the package postinstall, which links the native binary and
    # installs the macOS clipboard helper under the name the binary verifies.
    completed = subprocess.run(
        [bun, "x", "--trust", f"{PACKAGE}@{version}", *argv], shell=False, check=False
    )
    return completed.returncode


def main() -> int:
    """Run agent-desktop with the process arguments."""
    return run(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
