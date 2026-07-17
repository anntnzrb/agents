# ruff: noqa: S101
"""Regression checks for league inference defaults in scripts/main.py."""

from __future__ import annotations

from pathlib import Path

__all__: list[str] = []


def load_main_source() -> str:
    path = Path(__file__).resolve().parents[1] / "main.py"
    return path.read_text(encoding="utf-8")


def test_understat_default_not_forced_to_la_liga() -> None:
    source = load_main_source()
    assert "DEFAULT_UNDERSTAT_LEAGUE: str | None = None" in source


def test_espn_hints_include_portuguese_league() -> None:
    source = load_main_source()
    assert '("primeira liga", "por.1")' in source
    assert '("liga portugal", "por.1")' in source
