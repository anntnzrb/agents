# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the skill code-gate runner."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.gates import EXIT_USAGE, GateRunner, _pep723_deps, main, run_gates

_FAIL_CODE: Final[int] = 3


def _fake_runner(
    seen: list[tuple[Sequence[str], Path]], fail_on: str | None = None
) -> GateRunner:
    """Build a recording runner that fails steps starting with fail_on."""

    def fake_runner(step: Sequence[str], cwd: Path) -> int:
        seen.append((step, cwd))
        if fail_on is not None and step[0] == fail_on:
            return _FAIL_CODE
        return 0

    return fake_runner


def _skill_dir(tmp_path: Path, *, with_python: bool = True) -> Path:
    """Create a minimal skill directory layout under tmp_path."""
    skill = tmp_path / "demo-skill"
    (skill / "scripts").mkdir(parents=True)
    if with_python:
        (skill / "scripts" / "cli.py").write_text(
            "# /// script\n"
            '# requires-python = ">=3.12"\n'
            '# dependencies = ["PyYAML>=6.0"]\n'
            "# ///\n",
            encoding="utf-8",
        )
    return skill


def test_run_gates_passes_all_steps_in_order(tmp_path: Path) -> None:
    """All passing steps run in order and return zero."""
    seen: list[tuple[Sequence[str], Path]] = []
    code = run_gates([("aaa",), ("b",), ("c",)], tmp_path, _fake_runner(seen))
    assert code == 0
    assert [list(step) for step, _ in seen] == [["aaa"], ["b"], ["c"]]


def test_run_gates_stops_at_first_failure(tmp_path: Path) -> None:
    """A failing step aborts the run and its code is returned."""
    seen: list[tuple[Sequence[str], Path]] = []
    code = run_gates(
        [("aaa",), ("b",), ("c",)], tmp_path, _fake_runner(seen, fail_on="b")
    )
    assert code == _FAIL_CODE
    assert [list(step) for step, _ in seen] == [["aaa"], ["b"]]


def test_main_runs_static_gates_only_by_default(tmp_path: Path) -> None:
    """Default run executes exactly the static steps, no pytest."""
    skill = _skill_dir(tmp_path)
    seen: list[tuple[Sequence[str], Path]] = []
    assert main([str(skill)], _fake_runner(seen)) == 0
    tools = [step[1] if step[1] != "--with" else step[-1] for step, _ in seen]
    assert tools == ["ruff", "ruff", "basedpyright"]
    assert all(cwd == skill for _, cwd in seen)


def test_main_appends_pytest_with_tests_flag(tmp_path: Path) -> None:
    """The tests flag appends pytest with the skill dependency environment."""
    skill = _skill_dir(tmp_path)
    (skill / "tests").mkdir()
    seen: list[tuple[Sequence[str], Path]] = []
    assert main([str(skill), "--tests"], _fake_runner(seen)) == 0
    tools = [step[1] if step[1] != "--with" else step[-1] for step, _ in seen]
    assert tools == ["ruff", "ruff", "basedpyright", "tests"]
    pytest_step = list(seen[-1][0])
    assert "--with" in pytest_step
    assert "PyYAML>=6.0" in pytest_step


def test_main_skips_pytest_without_tests_dir(tmp_path: Path) -> None:
    """The tests flag without a tests/ directory runs static gates only."""
    skill = _skill_dir(tmp_path)
    seen: list[tuple[Sequence[str], Path]] = []
    assert main([str(skill), "--tests"], _fake_runner(seen)) == 0
    assert "pytest" not in [step[1] for step, _ in seen]


def test_main_skips_static_gates_without_python(tmp_path: Path) -> None:
    """A skill without Python files runs no static steps."""
    skill = _skill_dir(tmp_path, with_python=False)
    seen: list[tuple[Sequence[str], Path]] = []
    assert main([str(skill)], _fake_runner(seen)) == 0
    assert seen == []


def test_main_rejects_unknown_flag(tmp_path: Path) -> None:
    """An unknown flag prints usage, runs nothing, and returns two."""
    skill = _skill_dir(tmp_path)
    seen: list[tuple[Sequence[str], Path]] = []
    assert main([str(skill), "--bogus"], _fake_runner(seen)) == EXIT_USAGE
    assert seen == []


def test_main_requires_skill_directory() -> None:
    """Missing or nonexistent skill directory returns two."""
    seen: list[tuple[Sequence[str], Path]] = []
    assert main([], _fake_runner(seen)) == EXIT_USAGE
    assert main(["/nonexistent-skill-dir"], _fake_runner(seen)) == EXIT_USAGE
    assert seen == []


def test_main_propagates_gate_failure_code(tmp_path: Path) -> None:
    """A failing static step surfaces its exit code from main."""
    skill = _skill_dir(tmp_path)
    seen: list[tuple[Sequence[str], Path]] = []
    assert main([str(skill)], _fake_runner(seen, fail_on="uvx")) == _FAIL_CODE
    assert len(seen) == 1


def test_pep723_deps_without_block_returns_empty(tmp_path: Path) -> None:
    """A cli.py without a PEP 723 block contributes no dependencies."""
    skill = _skill_dir(tmp_path, with_python=False)
    (skill / "scripts" / "cli.py").write_text('"""Plain script."""\n', encoding="utf-8")
    assert _pep723_deps(skill) == []


def test_pep723_deps_missing_cli_returns_empty(tmp_path: Path) -> None:
    """A skill without scripts/cli.py contributes no dependencies."""
    skill = tmp_path / "bare-skill"
    skill.mkdir()
    assert _pep723_deps(skill) == []
