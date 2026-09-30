# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Contributor gate runner: static checks, optionally with the test suite.

Dev-only console script (``sync-gates``); never imported by the runtime CLI.
Run from the ``sync/`` directory after ``uv sync --frozen`` so the venv
provides ruff, basedpyright, and pytest.
"""

from __future__ import annotations

import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Sequence

EXIT_OK = 0
EXIT_USAGE = 2

type Step = tuple[str, ...]
# Steps in one stage run concurrently: every step but the last runs captured in
# the background, the last streams live; captured output is replayed after it.
type Stage = tuple[Step, ...]


class GateRunner(Protocol):
    """Run one gate step; return its exit code and captured output."""

    def __call__(self, step: Sequence[str], *, capture: bool) -> tuple[int, str]:
        """Run `step`, capturing stdout and stderr only when `capture` is set."""
        ...


_RUFF_CHECK: Step = ("ruff", "check", ".")
_RUFF_FORMAT: Step = ("ruff", "format", "--check", ".")
_TYPE_CHECK: Step = ("basedpyright",)
_TEST_STEP: Step = ("pytest", "-n", "auto")

_STATIC_STAGES: tuple[Stage, ...] = ((_RUFF_CHECK,), (_RUFF_FORMAT,), (_TYPE_CHECK,))
# Single-threaded basedpyright overlaps the parallel test suite.
_TEST_STAGES: tuple[Stage, ...] = (
    (_RUFF_CHECK,),
    (_RUFF_FORMAT,),
    (_TYPE_CHECK, _TEST_STEP),
)

_USAGE = "sync-gates: usage: sync-gates [--tests]"


def _run_step(step: Sequence[str], *, capture: bool) -> tuple[int, str]:
    """Run one gate step with inherited or captured stdio."""
    output = subprocess.PIPE if capture else None
    # Fixed argv, no shell: the command list is a hardcoded constant above.
    completed = subprocess.run(  # noqa: S603
        list(step),
        check=False,
        shell=False,
        stdout=output,
        stderr=subprocess.STDOUT if capture else None,
        text=True,
    )
    return completed.returncode, completed.stdout or ""


def _echo(command: Sequence[str]) -> None:
    """Print a gate command before running it (hook-style tracing)."""
    _ = sys.stdout.write(f"+ {' '.join(command)}\n")
    _ = sys.stdout.flush()


def _run_stage(stage: Stage, runner: GateRunner) -> int:
    """Run a stage's steps concurrently; return the first failing code."""
    *background, foreground = stage
    for step in stage:
        _echo(step)
    with ThreadPoolExecutor(max_workers=max(1, len(background))) as pool:
        futures = [pool.submit(runner, step, capture=True) for step in background]
        foreground_code, _ = runner(foreground, capture=False)
        results = [future.result() for future in futures]
    for _, output in results:
        _ = sys.stdout.write(output)
    _ = sys.stdout.flush()
    codes = [code for code, _ in results] + [foreground_code]
    return next((code for code in codes if code != EXIT_OK), EXIT_OK)


def run_gates(
    stages: Sequence[Stage],
    runner: GateRunner = _run_step,
) -> int:
    """Run each stage in order, echoing its steps; stop at the first failure."""
    for stage in stages:
        code = _run_stage(stage, runner)
        if code != EXIT_OK:
            return code
    return EXIT_OK


def main(
    argv: list[str] | None = None,
    runner: GateRunner = _run_step,
) -> int:
    """Run the contributor gates; return the process exit code (never raises)."""
    raw_args: list[str] = sys.argv[1:] if argv is None else list(argv)
    stages = _STATIC_STAGES
    for arg in raw_args:
        if arg == "--tests":
            stages = _TEST_STAGES
        else:
            _ = sys.stderr.write(f"{_USAGE}\n")
            return EXIT_USAGE
    return run_gates(stages, runner)


def main_gates_entry(argv: list[str] | None = None) -> None:
    """Console-script entrypoint (``sync-gates``); raises SystemExit with code."""
    raise SystemExit(main(argv))


if __name__ == "__main__":  # pragma: no cover - manual invocation only
    main_gates_entry()
