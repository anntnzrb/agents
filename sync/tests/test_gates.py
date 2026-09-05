# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the contributor gate runner."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from sync.gates import EXIT_USAGE, main, run_gates

if TYPE_CHECKING:
    from collections.abc import Sequence

_FAIL_CODE: Final[int] = 3
_PYTEST_FAIL_CODE: Final[int] = 5


def test_run_gates_passes_all_steps_in_order() -> None:
    """All passing steps run in order and return zero."""
    seen: list[list[str]] = []

    def fake_runner(step: Sequence[str]) -> int:
        seen.append(list(step))
        return 0

    code = run_gates([("aaa",), ("b", "c")], fake_runner)
    assert code == 0
    assert seen == [["aaa"], ["b", "c"]]


def test_run_gates_stops_at_first_failure() -> None:
    """A failing step aborts the run and its code is returned."""
    seen: list[list[str]] = []

    def fake_runner(step: Sequence[str]) -> int:
        seen.append(list(step))
        return _FAIL_CODE if step == ("b",) else 0

    code = run_gates([("aaa",), ("b",), ("c",)], fake_runner)
    assert code == _FAIL_CODE
    assert seen == [["aaa"], ["b"]]


def test_main_runs_static_steps_without_tests_flag() -> None:
    """Default run executes exactly the static gates and returns their code."""
    seen: list[list[str]] = []

    def fake_runner(step: Sequence[str]) -> int:
        seen.append(list(step))
        return 0

    assert main([], fake_runner) == 0
    assert seen == [
        ["ruff", "check", "."],
        ["ruff", "format", "--check", "."],
        ["basedpyright"],
    ]


def test_main_appends_test_suite_with_tests_flag() -> None:
    """The tests flag appends pytest and propagates a failure code."""
    seen: list[list[str]] = []

    def fake_runner(step: Sequence[str]) -> int:
        seen.append(list(step))
        return _PYTEST_FAIL_CODE if step[0] == "pytest" else 0

    assert main(["--tests"], fake_runner) == _PYTEST_FAIL_CODE
    assert seen[-1] == ["pytest", "-n", "auto"]


def test_main_rejects_unknown_flag() -> None:
    """An unknown flag prints usage, runs nothing, and returns two."""
    seen: list[list[str]] = []

    def fake_runner(step: Sequence[str]) -> int:
        seen.append(list(step))
        return 0

    assert main(["--bogus"], fake_runner) == EXIT_USAGE
    assert seen == []
