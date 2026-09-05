# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""CLI dispatcher: ``sync [sync]`` reconciles, ``sync launch <name>`` executes.

Help text and exit codes are frozen golden contracts (see tests/golden/).
Heavy lifting lives in :mod:`sync.core.index`.
"""

from __future__ import annotations

import sys

from sync.core.index import launch_main
from sync.core.index import main as run_main

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2

_HELP_LINES = (
    (
        "sync — Reconcile AI agent configurations, skills, and harness "
        "environments from SSOT."
    ),
    "",
    "Usage:",
    "  sync [sync]",
    "  sync launch <name> [-- <args...>]",
    "  sync -h | --help | help",
    "",
    "Commands:",
    "  sync (default)",
    "    Reconciles harness configurations, instruction files (HARNESS.md),",
    "    skills, tools, secrets, and generated launch wrappers (~/.local/bin).",
    "",
    "  launch <name> [-- <args...>]",
    "    Runs best-effort reconciliation, prepares the harness or tool package,",
    "    and executes it with any forwarded arguments.",
    "",
    "Options:",
    "  -h, --help, help    Show this help message.",
)
HELP_TEXT = "\n".join(_HELP_LINES)

_LAUNCH_HELP_LINES = (
    "Usage: sync launch <name> [-- <args...>]",
    "",
    ("Launch a managed harness or tool by name with optional forwarded arguments."),
)

LAUNCH_HELP_TEXT = "\n".join(_LAUNCH_HELP_LINES)

_LAUNCH_USAGE_ERROR = "sync: usage: launch NAME -- [ARGS...]"
_SYNC_USAGE_ERROR = "sync: usage: sync\nRun 'sync --help' for available commands."


def _is_help_flag(arg: str | None) -> bool:
    """Return True for the three accepted help spellings."""
    return arg in ("-h", "--help", "help")


def _out(text: str) -> None:
    """Write a help message to stdout (``print`` is banned by T201)."""
    sys.stdout.write(text + "\n")


def _err(text: str) -> None:
    """Write a usage error to stderr."""
    sys.stderr.write(text + "\n")


def _run_launch(args: list[str]) -> int:
    """Dispatch tokens following ``launch``; return the exit code."""
    if args and _is_help_flag(args[0]):
        _out(LAUNCH_HELP_TEXT)
        return EXIT_OK
    match args:
        case [name]:
            return launch_main(name, [])
        case [name, "--", *forwarded] if name and not _is_help_flag(name):
            return launch_main(name, forwarded)
        case _:
            _err(_LAUNCH_USAGE_ERROR)
            return EXIT_USAGE


def _run_sync_command(args: list[str]) -> int:
    """Dispatch tokens following a leading ``sync``; return the exit code."""
    match args:
        case []:
            return run_main()
        case [flag] if _is_help_flag(flag):
            _out(HELP_TEXT)
            return EXIT_OK
        case _:
            _err(_SYNC_USAGE_ERROR)
            return EXIT_USAGE


def main(argv: list[str] | None = None) -> int:
    """Run the sync CLI; return the process exit code (never raises)."""
    raw_args: list[str] = sys.argv[1:] if argv is None else list(argv)
    match raw_args:
        case [flag] if _is_help_flag(flag):
            _out(HELP_TEXT)
            return EXIT_OK
        case ["launch", *rest]:
            return _run_launch(rest)
        case ["sync", *rest]:
            return _run_sync_command(rest)
        case []:
            return run_main()
        case _:
            _err(_SYNC_USAGE_ERROR)
            return EXIT_USAGE


def main_sync_entry(argv: list[str] | None = None) -> None:
    """Console-script entrypoint (``sync``); raises SystemExit with the code."""
    raise SystemExit(main(argv))


if __name__ == "__main__":  # pragma: no cover - manual invocation only
    main_sync_entry()
