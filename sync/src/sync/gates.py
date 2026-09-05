# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Contributor gate runner: static checks, optionally then the test suite.

Dev-only console script (``sync-gates``); never imported by the runtime CLI.
Run from the ``sync/`` directory after ``uv sync --frozen`` so the venv
provides ruff, basedpyright, and pytest.
"""

from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

EXIT_OK = 0
EXIT_USAGE = 2

type GateRunner = Callable[[Sequence[str]], int]

_STATIC_STEPS: tuple[tuple[str, ...], ...] = (
    ("ruff", "check", "."),
    ("ruff", "format", "--check", "."),
    ("basedpyright",),
)
_TEST_STEP: tuple[str, ...] = ("pytest", "-n", "auto")

_USAGE = "sync-gates: usage: sync-gates [--tests]"


def _run_step(step: Sequence[str]) -> int:
    """Run one gate step with inherited stdio; return its exit code."""
    # Fixed argv, no shell: the command list is a hardcoded constant below.
    completed = subprocess.run(list(step), check=False, shell=False)  # noqa: S603
    return completed.returncode


def _echo(command: Sequence[str]) -> None:
    """Print a gate command before running it (hook-style tracing)."""
    _ = sys.stdout.write(f"+ {' '.join(command)}\n")
    _ = sys.stdout.flush()


def run_gates(
    steps: Sequence[Sequence[str]],
    runner: GateRunner = _run_step,
) -> int:
    """Run each step in order, echoing it first; stop at the first failure."""
    for step in steps:
        _echo(step)
        code = runner(step)
        if code != EXIT_OK:
            return code
    return EXIT_OK


def main(
    argv: list[str] | None = None,
    runner: GateRunner = _run_step,
) -> int:
    """Run the contributor gates; return the process exit code (never raises)."""
    raw_args: list[str] = sys.argv[1:] if argv is None else list(argv)
    steps: list[tuple[str, ...]] = list(_STATIC_STEPS)
    for arg in raw_args:
        if arg == "--tests":
            if _TEST_STEP not in steps:
                steps.append(_TEST_STEP)
        else:
            _ = sys.stderr.write(f"{_USAGE}\n")
            return EXIT_USAGE
    return run_gates(steps, runner)


def main_gates_entry(argv: list[str] | None = None) -> None:
    """Console-script entrypoint (``sync-gates``); raises SystemExit with code."""
    raise SystemExit(main(argv))


if __name__ == "__main__":  # pragma: no cover - manual invocation only
    main_gates_entry()
