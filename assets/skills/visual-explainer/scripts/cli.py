#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Cross-platform helpers for visual-explainer."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

HELP = """visual-explainer helper

Usage:
  uv run --script <skill-dir>/scripts/cli.py share <html-file>

Commands:
  share <html-file>  Copy the HTML file as index.html and deploy via vercel-deploy.
"""

PREVIEW_RE = re.compile(r"https://[^\s\"']+\.vercel\.app")
CLAIM_RE = re.compile(r"https://vercel\.com/claim-deployment[^\s\"']+")


@dataclass(frozen=True)
class Deployer:
    path: Path
    command: list[str]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="visual-explainer",
        description="Cross-platform helpers for visual-explainer.",
    )
    subparsers = parser.add_subparsers(dest="command")

    share = subparsers.add_parser(
        "share",
        help="Deploy an HTML file via vercel-deploy and print a live URL.",
    )
    share.add_argument("html_file", type=Path)

    return parser


def candidate_script_dirs() -> list[Path]:
    dirs: list[Path] = []

    env_script = os.environ.get("VERCEL_DEPLOY_SCRIPT")
    if env_script:
        dirs.append(Path(env_script).expanduser().parent)

    skills_dir = os.environ.get("SKILLS_DIR")
    if skills_dir:
        dirs.append(Path(skills_dir).expanduser() / "vercel-deploy" / "scripts")

    skill_dir = Path(__file__).resolve().parents[1]
    skills_root = skill_dir.parent
    dirs.append(skills_root / "vercel-deploy" / "scripts")
    dirs.append(Path.home() / ".pi" / "agent" / "skills" / "vercel-deploy" / "scripts")
    dirs.append(Path("/mnt/skills/user/vercel-deploy/scripts"))

    unique: list[Path] = []
    seen: set[Path] = set()
    for directory in dirs:
        resolved = directory.expanduser()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(resolved)
    return unique


def command_for_script(script: Path) -> tuple[list[str] | None, str | None]:
    suffix = script.suffix.lower()
    name = script.name.lower()

    if suffix == ".py":
        uv = shutil.which("uv")
        if uv is None:
            return None, "required executable not found: uv"
        return [uv, "run", "--script", str(script)], None

    if name == "deploy":
        return [str(script)], None

    return None, f"unsupported vercel-deploy script type: {script}"


def resolve_deployer() -> tuple[Deployer | None, str | None]:
    env_script = os.environ.get("VERCEL_DEPLOY_SCRIPT")
    explicit = Path(env_script).expanduser() if env_script else None
    script_names = ["cli.py", "deploy.py", "deploy"]

    candidates: list[Path] = []
    if explicit:
        candidates.append(explicit)
    for directory in candidate_script_dirs():
        candidates.extend(directory / name for name in script_names)

    errors: list[str] = []
    for candidate in candidates:
        if not candidate.is_file():
            continue
        command, error = command_for_script(candidate)
        if command is None:
            if error:
                errors.append(error)
            continue
        return Deployer(path=candidate, command=command), None

    if errors:
        return None, "; ".join(errors)
    return None, "vercel-deploy skill not found; install it with: pi install npm:vercel-deploy"


def extract_json_line(output: str) -> str | None:
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            json.loads(stripped)
        except json.JSONDecodeError:
            continue
        return stripped
    return None


def share(html_file: Path) -> int:
    source = html_file.expanduser().resolve()
    if not source.is_file():
        print(f"error: file not found: {html_file}", file=sys.stderr)
        return 2

    deployer, error = resolve_deployer()
    if deployer is None:
        print(f"error: {error}", file=sys.stderr)
        return 127

    with tempfile.TemporaryDirectory(prefix="visual-explainer-share-") as temp_name:
        temp_dir = Path(temp_name)
        shutil.copy2(source, temp_dir / "index.html")

        print(f"Sharing {source.name}...", file=sys.stderr)
        completed = subprocess.run(
            [*deployer.command, str(temp_dir)],
            shell=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

        result = completed.stdout or ""
        if completed.returncode != 0:
            print("error: deployment failed", file=sys.stderr)
            if result:
                print(result.rstrip(), file=sys.stderr)
            return completed.returncode

        preview_match = PREVIEW_RE.search(result)
        if preview_match is None:
            print("error: deployment completed but no Vercel preview URL was found", file=sys.stderr)
            if result:
                print(result.rstrip(), file=sys.stderr)
            return 2

        preview_url = preview_match.group(0)
        claim_match = CLAIM_RE.search(result)
        claim_url = claim_match.group(0) if claim_match else ""

        print("", file=sys.stderr)
        print("Shared successfully!", file=sys.stderr)
        print("", file=sys.stderr)
        print(f"Live URL:  {preview_url}", file=sys.stderr)
        if claim_url:
            print(f"Claim URL: {claim_url}", file=sys.stderr)
        print("", file=sys.stderr)

        json_line = extract_json_line(result)
        if json_line is not None:
            print(json_line)
        else:
            print(json.dumps({"previewUrl": preview_url, "claimUrl": claim_url}))
        return 0


def run(argv: Sequence[str]) -> int:
    if argv and argv[0] == "--":
        argv = argv[1:]

    if argv and argv[0] in {"-h", "--help"}:
        print(HELP)
        return 0

    parser = build_parser()
    args = parser.parse_args(list(argv))
    if args.command == "share":
        return share(args.html_file)

    parser.print_help(sys.stderr)
    return 2


def main() -> int:
    return run(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
