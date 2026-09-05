# Copyright (c) 2026
"""Executable contracts for the ui-ux-pro-max search CLI."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import cast

SKILL: Path = Path(__file__).resolve().parents[1]
SEARCH: Path = SKILL / "scripts" / "search.py"


def run_search(*args: str) -> subprocess.CompletedProcess[str]:
    """Invoke the search CLI with the given arguments."""
    return subprocess.run(
        ["uv", "run", "--quiet", "--script", str(SEARCH), *args],
        cwd=SKILL,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )


def json_result(args: list[str]) -> dict[str, object]:
    """Run a JSON search and decode a successful payload."""
    result = run_search(*args)
    assert result.returncode == 0, result.stderr
    return cast("dict[str, object]", json.loads(result.stdout))


def test_domain_search_returns_ranked_results() -> None:
    payload = json_result(
        ["button", "--domain", "style", "--max-results", "2", "--json"]
    )
    assert payload["domain"] == "style"
    assert payload["query"] == "button"
    results = cast("list[object]", payload["results"])
    assert len(results) == 2
    first = cast("dict[str, object]", results[0])
    assert first["Style Category"] == "3D Product Preview"


def test_auto_domain_detection() -> None:
    payload = json_result(["hex color palette", "--max-results", "1", "--json"])
    assert payload["domain"] == "color"


def test_stack_search() -> None:
    payload = json_result(
        ["server components", "--stack", "nextjs", "--max-results", "1", "--json"]
    )
    assert payload["stack"] == "nextjs"


def test_human_output() -> None:
    result = run_search("dark mode", "--domain", "style", "--max-results", "1")
    assert result.returncode == 0
    assert "UI Pro Max Search Results" in result.stdout


def test_design_system_generation() -> None:
    result = run_search("saas dashboard", "--design-system", "-p", "Contract")
    assert result.returncode == 0
    assert "Contract" in result.stdout
