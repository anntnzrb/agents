# Copyright (c) 2026
"""Executable contracts for the ui-ux-pro-max search CLI."""

import json
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TypeIs

_json_loads: Callable[[str | bytes | bytearray], object] = json.loads

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


def _is_str_mapping(val: object) -> TypeIs[Mapping[str, object]]:
    return isinstance(val, Mapping)


def _is_object_list(val: object) -> TypeIs[list[object]]:
    return isinstance(val, list)


def json_result(args: list[str]) -> Mapping[str, object]:
    """Run a JSON search and decode a successful payload."""
    result = run_search(*args)
    assert result.returncode == 0, result.stderr
    raw = _json_loads(result.stdout)
    if not _is_str_mapping(raw):
        raise TypeError("expected JSON object")
    return raw


def test_domain_search_returns_ranked_results() -> None:
    payload = json_result(
        ["button", "--domain", "style", "--max-results", "2", "--json"]
    )
    assert payload["domain"] == "style"
    assert payload["query"] == "button"
    results = payload["results"]
    if not _is_object_list(results):
        raise TypeError("expected results list")
    assert len(results) == 2
    first = results[0]
    if not _is_str_mapping(first):
        raise TypeError("expected result object")
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
