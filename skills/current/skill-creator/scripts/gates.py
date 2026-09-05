# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Python skill code gates: ruff, basedpyright, optionally pytest.

Dispatched via ``scripts/cli.py gates <skill-dir> [--tests]``; never imported
by other skills. Tools always resolve latest via ``uvx`` (unpinned by policy).
Dependency truth is the PEP 723 block in the skill's ``scripts/cli.py``; the
basedpyright and pytest steps derive their ``--with`` environments from it.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from collections.abc import Callable, Sequence
from pathlib import Path

EXIT_OK = 0
EXIT_USAGE = 2

type GateRunner = Callable[[Sequence[str], Path], int]

_USAGE = "usage: cli.py gates <skill-dir> [--tests]"


class _GatesError(Exception):
    """Raised when the skill directory or its PEP 723 block is unusable."""


def _run_step(step: Sequence[str], cwd: Path) -> int:
    """Run one gate step with inherited stdio in cwd; return its exit code."""
    print(f"+ {' '.join(step)}")
    # Fixed argv, no shell: every step is a hardcoded command list below.
    completed = subprocess.run(list(step), check=False, shell=False, cwd=cwd)  # noqa: S603
    return completed.returncode


def run_gates(
    steps: Sequence[Sequence[str]], cwd: Path, runner: GateRunner = _run_step
) -> int:
    """Run gate steps in order; stop at the first failure and return its code."""
    for step in steps:
        code = runner(step, cwd)
        if code != EXIT_OK:
            return code
    return EXIT_OK


def _has_python(skill_dir: Path) -> bool:
    """Return True when the skill directory contains any Python file."""
    return any(skill_dir.rglob("*.py"))


def _pep723_deps(skill_dir: Path) -> list[str]:
    """Read runtime dependencies from the scripts/cli.py PEP 723 block."""
    cli = skill_dir / "scripts" / "cli.py"
    if not cli.is_file():
        return []
    lines = cli.read_text(encoding="utf-8").splitlines()
    try:
        start = lines.index("# /// script")
    except ValueError:
        return []
    try:
        end = lines.index("# ///", start + 1)
    except ValueError:
        msg = f"unclosed PEP 723 block in {cli}"
        raise _GatesError(msg) from None
    body = "\n".join(
        line[2:] if line.startswith("# ") else line[1:]
        for line in lines[start + 1 : end]
    )
    try:
        data = tomllib.loads(body)
    except tomllib.TOMLDecodeError as exc:
        msg = f"malformed PEP 723 block in {cli}: {exc}"
        raise _GatesError(msg) from exc
    deps = data.get("dependencies", [])
    if not isinstance(deps, list) or not all(isinstance(dep, str) for dep in deps):
        msg = f"PEP 723 dependencies in {cli} must be a list of strings"
        raise _GatesError(msg)
    return list(deps)


def _with_prefix(deps: Sequence[str]) -> tuple[str, ...]:
    """Build the uvx prefix carrying the skill's dependency environment."""
    prefix: list[str] = ["uvx"]
    for dep in deps:
        prefix.extend(["--with", dep])
    return tuple(prefix)


def _static_steps(deps: Sequence[str]) -> list[tuple[str, ...]]:
    """Return the static gate steps; only basedpyright needs the skill env."""
    prefix = _with_prefix(deps)
    return [
        ("uvx", "ruff", "format", "--check", "."),
        ("uvx", "ruff", "check", "."),
        (*prefix, "basedpyright"),
    ]


def _pytest_step(deps: Sequence[str]) -> tuple[str, ...]:
    """Return the pytest step with pytest plus the skill env added."""
    return (*_with_prefix(["pytest", *deps]), "pytest", "tests")


def main(argv: list[str] | None = None, runner: GateRunner = _run_step) -> int:
    """Run the skill gates; return the process exit code (never raises)."""
    raw_args: list[str] = sys.argv[1:] if argv is None else list(argv)
    skill_dir: Path | None = None
    with_tests = False
    for arg in raw_args:
        if arg == "--tests":
            with_tests = True
        elif arg in {"-h", "--help"}:
            print(_USAGE)
            return EXIT_OK
        elif skill_dir is None and not arg.startswith("-"):
            skill_dir = Path(arg)
        else:
            print(_USAGE, file=sys.stderr)
            return EXIT_USAGE
    if skill_dir is None or not skill_dir.is_dir():
        print(_USAGE, file=sys.stderr)
        return EXIT_USAGE
    try:
        deps = _pep723_deps(skill_dir)
    except _GatesError as exc:
        print(f"gates: {exc}", file=sys.stderr)
        return EXIT_USAGE
    steps: list[tuple[str, ...]] = []
    if _has_python(skill_dir):
        steps.extend(_static_steps(deps))
    else:
        print("(no Python files, skipping static gates)")
    if with_tests:
        if (skill_dir / "tests").is_dir():
            steps.append(_pytest_step(deps))
        else:
            print("(no tests/ directory, skipping pytest)")
    return run_gates(steps, skill_dir, runner)


if __name__ == "__main__":  # pragma: no cover - dispatched via cli.py
    raise SystemExit(main())
