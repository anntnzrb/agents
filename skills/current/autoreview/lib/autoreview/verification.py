"""Validation and physical verification of review findings against actual disk files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from autoreview.models import CATEGORIES, PRIORITIES, PRIORITY_ORDER


def validate_finding_structure(finding: dict[str, Any], index: int) -> None:
    """Check that a finding matches the expected schema and type constraints."""
    required_keys = {
        "title",
        "body",
        "priority",
        "confidence",
        "category",
        "code_location",
    }
    missing = required_keys - set(finding.keys())
    if missing:
        raise ValueError(f"finding {index} missing required fields: {sorted(missing)}")

    if finding["priority"] not in PRIORITIES:
        raise ValueError(f"finding {index} has invalid priority: {finding['priority']}")

    if finding["category"] not in CATEGORIES:
        raise ValueError(f"finding {index} has invalid category: {finding['category']}")

    confidence = finding["confidence"]
    if (
        not isinstance(confidence, (int, float))
        or isinstance(confidence, bool)
        or not (0.0 <= confidence <= 1.0)
    ):
        raise ValueError(f"finding {index} has invalid confidence: {confidence}")

    loc = finding["code_location"]
    if not isinstance(loc, dict) or "file_path" not in loc or "line" not in loc:
        raise ValueError(f"finding {index} has invalid code_location structure: {loc}")

    if not isinstance(loc["line"], int) or loc["line"] < 1:
        raise ValueError(f"finding {index} has invalid line number: {loc.get('line')}")


def verify_physical_line_exists(repo: Path, file_path: str, line_number: int) -> bool:
    """Verify that the referenced file and line physically exist in the working checkout."""
    target = repo / file_path
    if not target.is_file():
        return False

    try:
        content = target.read_text(encoding="utf-8", errors="replace")
        total_lines = len(content.splitlines())
        return 1 <= line_number <= max(1, total_lines)
    except OSError:
        return False


def filter_findings_by_priority(
    findings: list[dict[str, Any]],
    max_priority: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Partition findings into accepted (>= max_priority) and filtered lower-severity findings."""
    limit_rank = PRIORITY_ORDER.get(max_priority, 0)
    kept: list[dict[str, Any]] = []
    filtered: list[dict[str, Any]] = []

    for finding in findings:
        rank = PRIORITY_ORDER.get(finding.get("priority", "P3"), 3)
        if rank <= limit_rank:
            kept.append(finding)
        else:
            filtered.append(finding)

    return kept, filtered
