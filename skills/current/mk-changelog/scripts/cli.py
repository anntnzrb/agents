# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Command-line interface for mk-changelog."""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

# Add lib directory to sys.path for internal imports
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from boundary_detector import detect_changelog_boundaries, find_nearest_changelog
from gh_resolver import (
    fetch_pr_diff,
    fetch_pr_metadata,
    is_gh_available,
    synthesize_pr_commit,
)
from git_extractor import (
    extract_commits_in_range,
    get_diff_snippet,
    get_diff_stat,
    get_staged_files,
)
from models import CommitInfo, ExistingEntries, PreparedContext
from parser import (
    format_entries_markdown,
    parse_changelog_file,
)
from patcher import (
    patch_changelog_content,
    patch_changelog_file,
)


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="mk-changelog",
        description="Deterministic Git and PR changelog context preparation and patching.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcommand: prepare
    prep_parser = subparsers.add_parser(
        "prepare",
        help="Extract git commits, boundaries, diffstats, and unreleased entries.",
    )
    prep_parser.add_argument(
        "--range",
        dest="commit_range",
        help="Git commit range, e.g. v1.0.0..HEAD or HEAD~5..HEAD",
    )
    prep_parser.add_argument(
        "--pr",
        dest="pr_identifier",
        help="GitHub Pull Request number or URL",
    )
    prep_parser.add_argument(
        "--staged",
        action="store_true",
        help="Inspect staged changes in the current working tree",
    )
    prep_parser.add_argument(
        "--repo",
        type=Path,
        default=Path(),
        help="Path to repository root (defaults to current directory)",
    )

    # Subcommand: format
    fmt_parser = subparsers.add_parser(
        "format",
        help="Format structured entries JSON into standard Keep a Changelog markdown.",
    )
    fmt_parser.add_argument(
        "--entries-file",
        type=Path,
        help="Path to JSON file containing { 'entries': { ... } }",
    )
    fmt_parser.add_argument(
        "--json",
        dest="json_str",
        help="Direct JSON string containing { 'entries': { ... } }",
    )
    fmt_parser.add_argument(
        "--header",
        action="store_true",
        help="Include ## [Unreleased] header in output",
    )

    # Subcommand: patch
    patch_parser = subparsers.add_parser(
        "patch",
        help="Patch target CHANGELOG.md idempotently with new entries.",
    )
    patch_parser.add_argument(
        "--target",
        type=Path,
        help="Path to target CHANGELOG.md file",
    )
    patch_parser.add_argument(
        "--entries-file",
        type=Path,
        help="Path to JSON file containing { 'entries': { ... } }",
    )
    patch_parser.add_argument(
        "--json",
        dest="json_str",
        help="Direct JSON string containing { 'entries': { ... } }",
    )
    patch_parser.add_argument(
        "--repo",
        type=Path,
        default=Path(),
        help="Path to repository root",
    )
    patch_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview patched content without writing to disk",
    )

    # Subcommand: status
    subparsers.add_parser(
        "status",
        help="Check tool dependencies and environment availability.",
    )

    return parser


def load_entries_payload(
    file_path: Path | None,
    json_str: str | None,
) -> dict[str, list[str]]:
    """Load entries mapping from file or string."""
    raw_dict: dict[str, object] = {}
    if file_path:
        if not file_path.is_file():
            sys.stderr.write(f"Error: Entries file not found: {file_path}\n")
            sys.exit(2)
        content = file_path.read_text(encoding="utf-8")
        raw_dict = json.loads(content)
    elif json_str:
        raw_dict = json.loads(json_str)
    else:
        sys.stderr.write("Error: Either --entries-file or --json must be provided.\n")
        sys.exit(2)

    # Handle wrapper object {"entries": {...}} or direct {...}
    if "entries" in raw_dict and isinstance(raw_dict["entries"], dict):
        raw_entries = raw_dict["entries"]
    else:
        raw_entries = raw_dict

    result: dict[str, list[str]] = {}
    for k, v in raw_entries.items():
        if isinstance(v, list):
            result[str(k)] = [str(item) for item in v]
    return result


def handle_prepare(args: argparse.Namespace) -> int:
    """Execute prepare subcommand."""
    repo_path: Path = args.repo.resolve()
    if not repo_path.is_dir():
        sys.stderr.write(f"Error: Repository path does not exist: {repo_path}\n")
        return 2

    source_type = "unknown"
    spec = ""
    commits: list[CommitInfo] = []
    affected_files: list[str] = []
    diff_stat = ""
    diff_snippet = ""
    contributors: dict[str, str] = {}

    try:
        if args.pr_identifier:
            source_type = "pr"
            spec = args.pr_identifier
            pr_meta = fetch_pr_metadata(args.pr_identifier, repo_path)
            synth_commit = synthesize_pr_commit(pr_meta)
            commits = [synth_commit]
            affected_files = pr_meta.files
            diff_snippet = fetch_pr_diff(args.pr_identifier, repo_path)
            diff_stat = f"{len(pr_meta.files)} files changed in PR #{pr_meta.number}"
            contributors[pr_meta.author] = pr_meta.url
        elif args.commit_range:
            source_type = "range"
            spec = args.commit_range
            parsed_commits = extract_commits_in_range(args.commit_range, repo_path)
            commits = list(parsed_commits)
            for c in parsed_commits:
                affected_files.extend(c.affected_files)
                if not c.is_bot:
                    contributors[c.author_name] = c.author_email
            diff_stat = get_diff_stat(repo_path, range_spec=args.commit_range)
            diff_snippet = get_diff_snippet(repo_path, range_spec=args.commit_range)
        elif args.staged:
            source_type = "staged"
            spec = "staged"
            staged_list = get_staged_files(repo_path)
            affected_files = staged_list
            diff_stat = get_diff_stat(repo_path, staged=True)
            diff_snippet = get_diff_snippet(repo_path, staged=True)
        else:
            sys.stderr.write("Error: Specify --range, --pr, or --staged for prepare.\n")
            return 2
    except RuntimeError as err:
        sys.stderr.write(f"Runtime error: {err}\n")
        return 1

    # Deduplicate affected files
    unique_files = sorted(set(affected_files))

    # Detect monorepo boundaries
    boundaries = detect_changelog_boundaries(unique_files, repo_path)

    # Parse existing unreleased sections
    existing_map: dict[str, ExistingEntries] = {}
    for b in boundaries:
        cl_file = Path(b.changelog_path)
        existing = parse_changelog_file(cl_file)
        existing_map[b.relative_path] = existing

    # If no boundaries found, check root CHANGELOG.md
    if not boundaries:
        root_cl = repo_path / "CHANGELOG.md"
        existing = parse_changelog_file(root_cl)
        existing_map["CHANGELOG.md"] = existing

    context = PreparedContext(
        source_type=source_type,
        spec=spec,
        commits=commits,
        boundaries=boundaries,
        existing_entries=existing_map,
        contributors=contributors,
        diff_stat=diff_stat,
        diff_snippet=diff_snippet,
    )

    sys.stdout.write(json.dumps(context.to_dict(), indent=2) + "\n")
    return 0


def handle_format(args: argparse.Namespace) -> int:
    """Execute format subcommand."""
    entries = load_entries_payload(args.entries_file, args.json_str)
    output = format_entries_markdown(entries, include_header=args.header)
    sys.stdout.write(output + "\n")
    return 0


def handle_patch(args: argparse.Namespace) -> int:
    """Execute patch subcommand."""
    repo_path: Path = args.repo.resolve()
    entries = load_entries_payload(args.entries_file, args.json_str)

    target_path: Path
    if args.target:
        target_path = (
            args.target
            if args.target.is_absolute()
            else (repo_path / args.target).resolve()
        )
    else:
        nearest = find_nearest_changelog(".", repo_path)
        target_path = nearest or (repo_path / "CHANGELOG.md").resolve()

    if args.dry_run:
        original = (
            target_path.read_text(encoding="utf-8") if target_path.is_file() else ""
        )
        patched, changed = patch_changelog_content(original, entries)
        sys.stdout.write(
            json.dumps(
                {
                    "ok": True,
                    "target": str(target_path),
                    "changed": changed,
                    "preview": patched,
                },
                indent=2,
            )
            + "\n"
        )
        return 0

    changed = patch_changelog_file(target_path, entries)
    sys.stdout.write(
        json.dumps(
            {
                "ok": True,
                "target": str(target_path),
                "changed": changed,
            },
            indent=2,
        )
        + "\n"
    )
    return 0


def handle_status() -> int:
    """Execute status subcommand."""
    gh_ok = is_gh_available()
    status_data = {
        "ok": True,
        "tools": {
            "git": True,
            "gh": gh_ok,
        },
        "python_version": sys.version,
    }
    sys.stdout.write(json.dumps(status_data, indent=2) + "\n")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Execute main CLI entrypoint."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "prepare":
        return handle_prepare(args)
    if args.command == "format":
        return handle_format(args)
    if args.command == "patch":
        return handle_patch(args)
    if args.command == "status":
        return handle_status()

    parser.print_help(sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
