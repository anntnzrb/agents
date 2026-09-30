# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the contributor gate runner."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Final

from sync.gates import EXIT_USAGE, main, run_gates

if TYPE_CHECKING:
    from collections.abc import Sequence

    import pytest

_FAIL_CODE: Final[int] = 3
_PYTEST_FAIL_CODE: Final[int] = 5
_OVERLAP_WAIT_SECONDS: Final[float] = 5.0


def test_run_gates_passes_all_stages_in_order() -> None:
    """All passing single-step stages run in order and return zero."""
    seen: list[list[str]] = []

    def fake_runner(step: Sequence[str], *, capture: bool) -> tuple[int, str]:
        assert capture is False
        seen.append(list(step))
        return 0, ""

    code = run_gates([(("aaa",),), (("b", "c"),)], fake_runner)
    assert code == 0
    assert seen == [["aaa"], ["b", "c"]]


def test_run_gates_stops_at_first_failing_stage() -> None:
    """A failing stage aborts the run and its code is returned."""
    seen: list[list[str]] = []

    def fake_runner(step: Sequence[str], *, capture: bool) -> tuple[int, str]:
        del capture
        seen.append(list(step))
        return (_FAIL_CODE if step == ("b",) else 0), ""

    code = run_gates([(("aaa",),), (("b",),), (("c",),)], fake_runner)
    assert code == _FAIL_CODE
    assert seen == [["aaa"], ["b"]]


def test_run_gates_overlaps_stage_steps_and_replays_captured_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Background steps run captured alongside the live last step of a stage."""
    foreground_started = threading.Event()

    def fake_runner(step: Sequence[str], *, capture: bool) -> tuple[int, str]:
        if step == ("bg",):
            assert capture is True
            # Deadlocks (then fails) if the stage ran its steps sequentially.
            assert foreground_started.wait(_OVERLAP_WAIT_SECONDS)
            return _FAIL_CODE, "bg report\n"
        assert capture is False
        foreground_started.set()
        return 0, ""

    code = run_gates([(("bg",), ("fg",))], fake_runner)
    assert code == _FAIL_CODE
    assert capsys.readouterr().out == "+ bg\n+ fg\nbg report\n"


def test_main_runs_static_steps_without_tests_flag() -> None:
    """Default run executes exactly the static gates, live and in order."""
    seen: list[list[str]] = []

    def fake_runner(step: Sequence[str], *, capture: bool) -> tuple[int, str]:
        assert capture is False
        seen.append(list(step))
        return 0, ""

    assert main([], fake_runner) == 0
    assert seen == [
        ["ruff", "check", "."],
        ["ruff", "format", "--check", "."],
        ["basedpyright"],
    ]


def test_main_overlaps_type_check_with_test_suite_with_tests_flag() -> None:
    """The tests flag runs basedpyright captured beside a live pytest run."""
    seen: list[tuple[str, bool]] = []
    lock = threading.Lock()

    def fake_runner(step: Sequence[str], *, capture: bool) -> tuple[int, str]:
        with lock:
            seen.append((" ".join(step), capture))
        return (_PYTEST_FAIL_CODE if step[0] == "pytest" else 0), ""

    assert main(["--tests"], fake_runner) == _PYTEST_FAIL_CODE
    assert seen[:2] == [("ruff check .", False), ("ruff format --check .", False)]
    assert sorted(seen[2:]) == [("basedpyright", True), ("pytest -n auto", False)]


def test_main_rejects_unknown_flag() -> None:
    """An unknown flag prints usage, runs nothing, and returns two."""
    seen: list[list[str]] = []

    def fake_runner(step: Sequence[str], *, capture: bool) -> tuple[int, str]:
        del capture
        seen.append(list(step))
        return 0, ""

    assert main(["--bogus"], fake_runner) == EXIT_USAGE
    assert seen == []
