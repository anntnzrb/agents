"""Validate the public findings contract and locations in reviewed source states."""

from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath
from typing import TypedDict, TypeIs

from autoreview.models import CATEGORIES, PRIORITIES, PRIORITY_ORDER
from autoreview.targets import ReviewBundle


class Report(TypedDict):
    summary: str
    overall_correctness: str
    findings: list[dict[str, object]]


def _is_dict(obj: object) -> TypeIs[dict[str, object]]:
    return isinstance(obj, dict)


def _is_list(obj: object) -> TypeIs[list[object]]:
    return isinstance(obj, list)


def validate_finding_structure(finding: Mapping[str, object], index: int) -> None:
    """Reject missing fields, invalid text, enums, and locations."""
    for key, limit in (("title", 140), ("body", 2000)):
        value = finding.get(key)
        if not isinstance(value, str) or not 1 <= len(value) <= limit:
            raise ValueError(f"finding {index}: invalid {key}")
    if finding.get("priority") not in PRIORITIES:
        raise ValueError(f"finding {index}: invalid priority")
    if finding.get("category") not in CATEGORIES:
        raise ValueError(f"finding {index}: invalid category")
    confidence = finding.get("confidence")
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not 0 <= confidence <= 1
    ):
        raise ValueError(f"finding {index}: invalid confidence")
    loc = finding.get("code_location")
    if not _is_dict(loc):
        raise ValueError(f"finding {index}: invalid code_location")
    path, line = loc.get("file_path"), loc.get("line")
    if (
        not isinstance(path, str)
        or not path
        or PurePosixPath(path).is_absolute()
        or ".." in PurePosixPath(path).parts
        or "\\" in path
    ):
        raise ValueError(f"finding {index}: invalid file_path")
    if isinstance(line, bool) or not isinstance(line, int) or line < 1:
        raise ValueError(f"finding {index}: invalid line")
    if "excerpt" in loc and not isinstance(loc["excerpt"], str):
        raise ValueError(f"finding {index}: invalid excerpt")
    if "state" in loc and not isinstance(loc["state"], str):
        raise ValueError(f"finding {index}: invalid state")


def verify_physical_line_exists(
    content: str, line_number: int, excerpt: str | None = None
) -> bool:
    """Check a physical source line and optional exact excerpt, preserving whitespace."""
    lines = content.splitlines() or [""]
    if not 1 <= line_number <= len(lines):
        return False
    return excerpt is None or excerpt == lines[line_number - 1]


def validate_report(payload: object, bundle: ReviewBundle) -> tuple[Report, list[str]]:
    """Collect per-finding errors before applying any reporting threshold."""
    empty: Report = {"summary": "", "overall_correctness": "", "findings": []}
    if not _is_dict(payload):
        return empty, ["report: expected a JSON object"]
    summary, verdict, raw = (
        payload.get("summary"),
        payload.get("overall_correctness"),
        payload.get("findings"),
    )
    if not isinstance(summary, str) or not summary:
        return empty, ["report: summary must be nonempty text"]
    if not isinstance(verdict, str) or verdict not in {
        "patch is correct",
        "patch is incorrect",
    }:
        return empty, ["report: invalid overall_correctness"]
    if not _is_list(raw):
        return empty, ["report: findings must be an array"]
    findings: list[dict[str, object]] = []
    errors: list[str] = []
    for index, finding in enumerate(raw):
        try:
            if not _is_dict(finding):
                raise ValueError(f"finding {index}: expected an object")
            validate_finding_structure(finding, index)
            loc = finding["code_location"]
            if not _is_dict(loc):
                raise ValueError(f"finding {index}: invalid location")
            path, line, excerpt, state = (
                loc["file_path"],
                loc["line"],
                loc.get("excerpt"),
                loc.get("state"),
            )
            if not isinstance(path, str) or not isinstance(line, int):
                raise TypeError(f"finding {index}: invalid location")
            sources = bundle.snapshots.get(path, {})
            candidates = (
                {state: sources[state]}
                if isinstance(state, str) and state in sources
                else {}
                if state is not None
                else sources
            )
            quote = excerpt if isinstance(excerpt, str) else None
            if not any(
                verify_physical_line_exists(text, line, quote)
                for text in candidates.values()
            ):
                raise ValueError(
                    f"finding {index}: file, state, line, or excerpt does not exist in reviewed snapshot: {path}:{line}"
                )
            findings.append(finding)
        except (ValueError, TypeError) as err:
            errors.append(str(err))
    return {
        "summary": summary,
        "overall_correctness": verdict,
        "findings": findings,
    }, errors


def filter_findings_by_priority(
    findings: Sequence[dict[str, object]],
    max_priority: str,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Partition validated findings by the requested priority threshold."""
    limit = PRIORITY_ORDER[max_priority]
    kept = [f for f in findings if PRIORITY_ORDER[str(f["priority"])] <= limit]
    filtered = [f for f in findings if PRIORITY_ORDER[str(f["priority"])] > limit]
    return kept, filtered
