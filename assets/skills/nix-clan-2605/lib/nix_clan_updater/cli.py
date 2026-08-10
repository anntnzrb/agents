"""Command-line interface for the Clan documentation snapshot updater."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .core import UpdaterError, render_summary, update

DEFAULT_REPO = "https://git.clan.lol/clan/clan-core"


def _parser(skill_root: Path) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nix-clan-updater",
        description="Fetch and stage a pinned Clan documentation snapshot.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    update_parser = commands.add_parser(
        "update", help="plan or apply a release snapshot update"
    )
    update_parser.add_argument(
        "--to-branch", required=True, help="target release branch in YY.MM form"
    )
    update_parser.add_argument(
        "--repo", default=DEFAULT_REPO, help="Clan clan-core repository URL"
    )
    update_parser.add_argument(
        "--source-dir", type=Path, default=skill_root, help="current skill directory"
    )
    update_parser.add_argument(
        "--target-dir", type=Path, help="sibling output directory"
    )
    update_parser.add_argument(
        "--apply",
        action="store_true",
        help="write the staged sibling; default is dry-run",
    )
    update_parser.add_argument(
        "--json", action="store_true", help="emit a machine-readable summary"
    )
    return parser


def main(argv: list[str] | None = None, *, skill_root: Path | None = None) -> int:
    """Parse arguments, run one update, and return its process exit code."""
    root = (skill_root or Path(__file__).resolve().parents[2]).resolve()
    parser = _parser(root)
    args = parser.parse_args(argv)
    if args.command != "update":
        parser.error(f"unknown command: {args.command}")
    try:
        summary = update(
            repo=args.repo,
            branch=args.to_branch,
            source_dir=args.source_dir,
            target_dir=args.target_dir,
            apply=args.apply,
        )
    except UpdaterError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code
    print(render_summary(summary, args.json))
    return 0
