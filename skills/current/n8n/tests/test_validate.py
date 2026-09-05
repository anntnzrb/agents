# Copyright (c) 2026
"""Executable contracts for the n8nctl offline validate command."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import cast

SKILL: Path = Path(__file__).resolve().parents[1]
VALIDATE: Path = SKILL / "scripts" / "n8nctl.py"


def run_validate(target: Path) -> subprocess.CompletedProcess[str]:
    """Invoke the offline validate subcommand on one file."""
    return subprocess.run(
        ["uv", "run", "--quiet", "--script", str(VALIDATE), "validate", str(target)],
        cwd=SKILL,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def validate_payload(tmp_path: Path, name: str, payload: object) -> dict[str, object]:
    """Write payload JSON, validate it, and decode a successful report."""
    target = tmp_path / name
    _ = target.write_text(json.dumps(payload), encoding="utf-8")
    result = run_validate(target)
    assert result.returncode == 0, result.stderr
    return cast("dict[str, object]", json.loads(result.stdout))


def errors_of(report: dict[str, object]) -> list[str]:
    """Project the report error list to strings."""
    return [str(item) for item in cast("list[object]", report["errors"])]


def warnings_of(report: dict[str, object]) -> list[str]:
    """Project the report warning list to strings."""
    return [str(item) for item in cast("list[object]", report["warnings"])]


def test_valid_workflow_passes(tmp_path: Path) -> None:
    report = validate_payload(
        tmp_path,
        "valid.json",
        {
            "name": "demo",
            "nodes": [{"name": "Start", "type": "n8n-nodes-base.start"}],
            "connections": {},
            "settings": {},
        },
    )
    assert report["valid"] is True
    assert errors_of(report) == []
    assert warnings_of(report) == []


def test_missing_keys_are_reported(tmp_path: Path) -> None:
    report = validate_payload(tmp_path, "empty.json", {})
    assert report["valid"] is False
    errors = errors_of(report)
    assert "missing key: name" in errors
    assert "missing key: nodes" in errors


def test_non_list_nodes_are_rejected(tmp_path: Path) -> None:
    report = validate_payload(
        tmp_path,
        "nodes.json",
        {"name": "demo", "nodes": {}, "connections": {}, "settings": {}},
    )
    assert report["valid"] is False
    assert "nodes must be a list" in errors_of(report)


def test_duplicate_node_names_are_rejected(tmp_path: Path) -> None:
    node = {"name": "Start", "type": "n8n-nodes-base.start"}
    report = validate_payload(
        tmp_path,
        "duplicate.json",
        {
            "name": "demo",
            "nodes": [node, dict(node)],
            "connections": {},
            "settings": {},
        },
    )
    assert report["valid"] is False
    assert "duplicate node name: Start" in errors_of(report)


def test_dangling_connection_target_is_rejected(tmp_path: Path) -> None:
    report = validate_payload(
        tmp_path,
        "dangling.json",
        {
            "name": "demo",
            "nodes": [{"name": "Start", "type": "n8n-nodes-base.start"}],
            "connections": {
                "Start": {"main": [[{"node": "Missing"}]]},
            },
            "settings": {},
        },
    )
    assert report["valid"] is False
    assert "connection from Start to missing node: Missing" in errors_of(report)


def test_unknown_connection_source_warns_without_failing(tmp_path: Path) -> None:
    report = validate_payload(
        tmp_path,
        "warning.json",
        {
            "name": "demo",
            "nodes": [{"name": "Start", "type": "n8n-nodes-base.start"}],
            "connections": {"Ghost": {"main": []}},
            "settings": {"availableInMCP": "yes"},
        },
    )
    assert report["valid"] is True
    warnings = warnings_of(report)
    assert "connection source not in nodes: Ghost" in warnings
    assert "settings.availableInMCP should be boolean" in warnings


def test_invalid_json_exits_2(tmp_path: Path) -> None:
    target = tmp_path / "broken.json"
    _ = target.write_text("{broken\n", encoding="utf-8")
    result = run_validate(target)
    assert result.returncode == 2
    assert result.stderr.startswith("n8nctl: invalid JSON")


def test_missing_file_exits_2(tmp_path: Path) -> None:
    result = run_validate(tmp_path / "absent.json")
    assert result.returncode == 2
    assert result.stderr.startswith("n8nctl: failed to read")
