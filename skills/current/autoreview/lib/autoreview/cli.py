"""Main command-line interface logic and coordinator for AutoReview."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from autoreview.engines import invoke_engine_review
from autoreview.models import ENGINES, PRIORITIES
from autoreview.targets import capture_diff_bundle, choose_review_target
from autoreview.verification import (
    filter_findings_by_priority,
    validate_finding_structure,
    verify_physical_line_exists,
)


def build_arg_parser() -> argparse.ArgumentParser:
    """Construct the standard CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Bundle-driven AI code review harness."
    )
    parser.add_argument(
        "--mode",
        choices=["auto", "local", "uncommitted", "branch", "commit"],
        default="auto",
        help="Git review target scope.",
    )
    parser.add_argument(
        "--base",
        help="Branch base ref, or explicit commit to compare against in local mode.",
    )
    parser.add_argument(
        "--commit",
        default="HEAD",
        help="Target commit SHA when reviewing a single commit.",
    )
    parser.add_argument(
        "--engine",
        choices=ENGINES,
        default="codex",
        help="Underlying review model engine.",
    )
    parser.add_argument(
        "--max-priority",
        choices=PRIORITIES,
        default="P0",
        help="Widest finding priority to accept (P0, P1, P2, P3).",
    )
    parser.add_argument(
        "--json-output",
        help="File path to write structured JSON report.",
    )
    parser.add_argument(
        "--output",
        help="File path to write human-readable review transcript.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Capture and display bundle metadata without triggering LLM inference.",
    )
    return parser


def format_human_report(report: dict[str, Any]) -> str:
    """Render findings into a clean, human-readable terminal report."""
    lines: list[str] = []
    lines.append("=== AutoReview Summary ===")
    lines.append(f"Verdict: {report.get('overall_correctness', 'Unknown')}")
    lines.append(f"Explanation: {report.get('overall_explanation', '')}\n")

    findings = report.get("findings", [])
    if not findings:
        lines.append("No findings matching the requested priority threshold.")
        return "\n".join(lines)

    lines.append(f"Findings ({len(findings)}):")
    for idx, f in enumerate(findings, 1):
        loc = f.get("code_location", {})
        lines.append(
            f"[{idx}] [{f.get('priority')}] {f.get('title')} ({f.get('category')})"
        )
        lines.append(f"    Location: {loc.get('file_path')}:{loc.get('line')}")
        lines.append(f"    Confidence: {f.get('confidence')}")
        lines.append(f"    Details: {f.get('body')}\n")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Execute the AutoReview workflow."""
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    repo_root = Path.cwd()

    mode, base_ref, commit_sha = choose_review_target(
        repo_root,
        args.mode,
        args.base,
        args.commit,
    )

    bundle = capture_diff_bundle(repo_root, mode, base_ref, commit_sha)

    if args.dry_run:
        print(f"AutoReview [Dry Run] Mode: {bundle.mode}")
        print(f"Changed Files ({len(bundle.changed_files)}): {bundle.changed_files}")
        if bundle.redacted_files:
            print(
                f"Redacted Files ({len(bundle.redacted_files)}): {bundle.redacted_files}"
            )
        print(f"Diff Size: {len(bundle.diff_text)} bytes")
        return 0

    # Dispatch to review engine
    report = invoke_engine_review(bundle, engine=args.engine)

    # Filter and verify findings against real physical disk files
    raw_findings = report.get("findings", [])
    verified_findings: list[dict[str, Any]] = []

    for idx, f in enumerate(raw_findings):
        try:
            validate_finding_structure(f, idx)
            loc = f["code_location"]
            if verify_physical_line_exists(repo_root, loc["file_path"], loc["line"]):
                verified_findings.append(f)
        except ValueError as err:
            sys.stderr.write(f"Warning: discarding malformed finding: {err}\n")

    kept, _ = filter_findings_by_priority(verified_findings, args.max_priority)
    report["findings"] = kept

    if kept:
        report["overall_correctness"] = "patch is incorrect"

    # Human-readable output
    human_text = format_human_report(report)
    print(human_text)

    if args.output:
        Path(args.output).write_text(human_text, encoding="utf-8")

    if args.json_output:
        Path(args.json_output).write_text(
            json.dumps(report, indent=2) + "\n",
            encoding="utf-8",
        )

    # Return non-zero if blocker findings exist
    return 1 if any(f.get("priority") == "P0" for f in kept) else 0
