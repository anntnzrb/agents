"""Deterministic review preparation and findings verification."""

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import cast

from autoreview.git_ops import git_run
from autoreview.models import PRIORITIES
from autoreview.targets import ReviewBundle, capture_diff_bundle, choose_review_target
from autoreview.verification import filter_findings_by_priority, validate_report

STDOUT_LIMIT = 10000


class CliArgs(argparse.Namespace):
    command: str = "bundle"
    mode: str = "auto"
    base: str | None = None
    commit: str = "HEAD"
    max_priority: str = "P0"
    findings: str | None = None
    output: str | None = None


def build_arg_parser() -> argparse.ArgumentParser:
    """Construct the public command parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument(
        "command", nargs="?", choices=["bundle", "verify"], default="bundle"
    )
    _ = parser.add_argument(
        "--mode",
        choices=["auto", "local", "uncommitted", "branch", "commit"],
        default="auto",
    )
    _ = parser.add_argument("--base", help="Branch base or pinned local base ref.")
    _ = parser.add_argument("--commit", default="HEAD", help="Commit target ref.")
    _ = parser.add_argument(
        "--output", help="Write the full review bundle to this file."
    )
    _ = parser.add_argument("--findings", help="JSON findings file for verify.")
    _ = parser.add_argument(
        "--max-priority",
        choices=PRIORITIES,
        default="P0",
        help="Verify reporting threshold (default: P0).",
    )
    return parser


def render_bundle(bundle: ReviewBundle) -> str:
    """Describe the resolved target and include the complete sanitized patch."""
    files = "\n".join(bundle.file_stats)
    return (
        f"Target: {bundle.mode}\nBase: {bundle.base_ref}\nHead: {bundle.commit_sha}\n"
        f"Changed files ({len(bundle.changed_files)}), additions/deletions by state:\n{files}\n"
        f"Redacted files: {', '.join(bundle.redacted_files) or 'None'}\n\n"
        f"{bundle.diff_text or 'Empty diff. No reviewable changes.'}\n"
    )


def publish_bundle(bundle: ReviewBundle, output: str | None) -> None:
    """Keep stdout bounded without truncating the saved bundle."""
    text = render_bundle(bundle)
    path = Path(output).resolve() if output else None
    if len(text) > STDOUT_LIMIT and path is None:
        with tempfile.NamedTemporaryFile(
            prefix="autoreview-", suffix=".txt", delete=False
        ) as handle:
            path = Path(handle.name)
    if path is not None:
        _ = path.write_text(text, encoding="utf-8", errors="surrogateescape")
    if len(text) > STDOUT_LIMIT:
        print(
            f"Target: {bundle.mode}\nBase: {bundle.base_ref}\nHead: {bundle.commit_sha}"
        )
        print(
            f"Changed files: {len(bundle.changed_files)}; redacted: {len(bundle.redacted_files)}"
        )
        print(f"Bundle size: {len(text)} characters. Read the full file in chunks.")
    else:
        print(text, end="")
    if path is not None:
        print(f"Full bundle: {path}")


def main(argv: list[str] | None = None) -> int:
    """Run only Git collection and local validation, never a reviewer process."""
    parser = build_arg_parser()
    args = parser.parse_args(argv, namespace=CliArgs())
    if args.command == "verify" and not args.findings:
        parser.error("verify requires --findings")
    if args.command == "bundle" and args.findings:
        parser.error("--findings is only valid for verify")
    if args.command == "verify" and args.output:
        parser.error("--output is only valid for bundle")
    try:
        repo = Path(git_root())
        mode, base, head = choose_review_target(repo, args.mode, args.base, args.commit)
        bundle = capture_diff_bundle(repo, mode, base, head)
        if args.command == "bundle":
            publish_bundle(bundle, args.output)
            return 0
        payload = cast(
            "object", json.loads(Path(args.findings or "").read_text(encoding="utf-8"))
        )
        report, reasons = validate_report(payload, bundle)
        if reasons:
            for reason in reasons:
                print(reason, file=sys.stderr)
            return 1
        kept, filtered = filter_findings_by_priority(
            report["findings"], args.max_priority
        )
        print(json.dumps({**report, "findings": kept}, indent=2))
        print(f"Verified: {len(kept)}; Filtered: {len(filtered)}", file=sys.stderr)
    except (OSError, ValueError) as err:
        print(str(err), file=sys.stderr)
        return 1
    return 0


def git_root() -> str:
    """Resolve the repository root, including invocation from a subdirectory."""
    return git_run(Path.cwd(), ["rev-parse", "--show-toplevel"]).stdout.strip()
