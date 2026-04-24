#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Cross-platform dispatcher for Agent Readiness reports."""

from __future__ import annotations

import argparse
import runpy
import sys
import tempfile
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"
ANALYZE = SCRIPTS_DIR / "analyze_repo.py"
REPORT = SCRIPTS_DIR / "generate_report.py"


def _run_script(path: Path, args: list[str]) -> int:
    sys.path.insert(0, str(SCRIPTS_DIR))
    old_argv = sys.argv[:]
    sys.argv = [str(path), *args]
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        if isinstance(code, int):
            return code
        print(code, file=sys.stderr)
        return 1
    finally:
        sys.argv = old_argv
    return 0


def _run_analyze_and_report(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="cli.py run", description="Analyze a repo, then print a report.")
    parser.add_argument("--repo-path", "-r", default=".", help="Repository to analyze")
    parser.add_argument(
        "--analysis-output",
        default=str(Path(tempfile.gettempdir()) / "readiness_analysis.json"),
        help="Intermediate analysis JSON path",
    )
    parser.add_argument("--output", "-o", help="Report output file; defaults to stdout")
    parser.add_argument("--format", "-f", choices=["markdown", "brief", "json"], default="markdown")
    parser.add_argument("--quiet", "-q", action="store_true", help="Suppress analyzer progress")
    ns = parser.parse_args(args)

    analyze_args = ["--repo-path", ns.repo_path, "--output", ns.analysis_output]
    if ns.quiet:
        analyze_args.append("--quiet")
    code = _run_script(ANALYZE, analyze_args)
    if code != 0:
        return code

    report_args = ["--analysis-file", ns.analysis_output, "--format", ns.format]
    if ns.output:
        report_args.extend(["--output", ns.output])
    return _run_script(REPORT, report_args)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in {"-h", "--help"}:
        print("usage: cli.py {analyze,report,run} [args...]\n")
        print("Cross-platform:")
        print("  uv run --script <skill-dir>/scripts/cli.py analyze --repo-path .")
        print("  uv run --script <skill-dir>/scripts/cli.py report --analysis-file <temp-dir>/readiness_analysis.json")
        print("  uv run --script <skill-dir>/scripts/cli.py run --repo-path . --format brief")
        print("\nUse '<command> --help' for command-specific flags.")
        return 0

    command, rest = argv[0], argv[1:]
    if command == "analyze":
        return _run_script(ANALYZE, rest)
    if command == "report":
        return _run_script(REPORT, rest)
    if command == "run":
        return _run_analyze_and_report(rest)

    parser = argparse.ArgumentParser(prog="cli.py")
    parser.error("command must be one of: analyze, report, run")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
