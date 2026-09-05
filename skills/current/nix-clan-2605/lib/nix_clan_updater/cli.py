"""Command-line interface for the Clan documentation snapshot updater."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import cast

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
    _ = update_parser.add_argument(
        "--to-branch", required=True, help="target release branch in YY.MM form"
    )
    _ = update_parser.add_argument(
        "--repo", default=DEFAULT_REPO, help="Clan clan-core repository URL"
    )
    _ = update_parser.add_argument(
        "--source-dir", type=Path, default=skill_root, help="current skill directory"
    )
    _ = update_parser.add_argument(
        "--target-dir", type=Path, help="sibling output directory"
    )
    _ = update_parser.add_argument(
        "--apply",
        action="store_true",
        help="write the staged sibling; default is dry-run",
    )
    _ = update_parser.add_argument(
        "--json", action="store_true", help="emit a machine-readable summary"
    )
    return parser


def main(argv: list[str] | None = None, *, skill_root: Path | None = None) -> int:
    """Parse arguments, run one update, and return its process exit code."""
    root = (skill_root or Path(__file__).resolve().parents[2]).resolve()
    parser = _parser(root)
    args = parser.parse_args(argv)
    command = _required_str(args, "command")
    if command != "update":
        parser.error(f"unknown command: {command}")
    try:
        summary = update(
            repo=_required_str(args, "repo"),
            branch=_required_str(args, "to_branch"),
            source_dir=_required_path(args, "source_dir"),
            target_dir=_optional_path(args, "target_dir"),
            apply=_flag(args, "apply"),
        )
    except UpdaterError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code
    print(render_summary(summary, _flag(args, "json")))
    return 0


def _required_str(args: argparse.Namespace, field: str) -> str:
    """Narrow a required string argument to a typed value."""
    value = cast("object", getattr(args, field))
    if not isinstance(value, str):
        message = f"Missing required argument: {field}."
        raise TypeError(message)
    return value


def _required_path(args: argparse.Namespace, field: str) -> Path:
    """Narrow a required path argument to a typed value."""
    value = cast("object", getattr(args, field))
    if not isinstance(value, Path):
        message = f"Missing required argument: {field}."
        raise TypeError(message)
    return value


def _optional_path(args: argparse.Namespace, field: str) -> Path | None:
    """Narrow an optional path argument to a typed value."""
    value = cast("object", getattr(args, field))
    return value if isinstance(value, Path) else None


def _flag(args: argparse.Namespace, field: str) -> bool:
    """Narrow a boolean flag to a typed value."""
    value = cast("object", getattr(args, field))
    return value if isinstance(value, bool) else False
