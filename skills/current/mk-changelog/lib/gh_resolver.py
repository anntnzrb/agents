"""GitHub Pull Request inspection and metadata resolution."""

import json
import re
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from git_extractor import CONVENTIONAL_REGEX
from models import CONVENTIONAL_TYPE_MAP, CommitInfo

PR_URL_REGEX: re.Pattern[str] = re.compile(
    r"github\.com/([^/]+)/([^/]+)/pull/(\d+)",
    re.IGNORECASE,
)


@dataclass(slots=True)
class PRMetadata:
    """Structured representation of GitHub PR details."""

    number: int
    title: str
    body: str
    author: str
    url: str
    base_ref: str
    head_ref: str
    files: list[str]


def is_gh_available() -> bool:
    """Check if the gh CLI is available on PATH."""
    return shutil.which("gh") is not None


def run_gh_command(args: Sequence[str], repo_path: Path) -> str:
    """Execute gh CLI command returning stdout."""
    if not is_gh_available():
        msg = "GitHub CLI 'gh' is required for PR resolution but not found on PATH."
        raise RuntimeError(msg)

    result = subprocess.run(
        ["gh", *args],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        err = result.stderr.strip() or f"gh {' '.join(args)} failed"
        raise RuntimeError(err)
    return result.stdout.strip()


def parse_pr_identifier(pr_input: str) -> str:
    """Normalize PR number or URL into a clean PR string."""
    pr_str = pr_input.strip()
    if pr_str.startswith("#"):
        return pr_str[1:]
    return pr_str


def fetch_pr_metadata(pr_identifier: str, repo_path: Path) -> PRMetadata:
    """Fetch structured PR metadata using gh pr view."""
    pr_clean = parse_pr_identifier(pr_identifier)
    fields = "number,title,body,author,url,files,baseRefName,headRefName"
    output = run_gh_command(
        ["pr", "view", pr_clean, f"--json={fields}"],
        repo_path,
    )
    data: dict[str, Any] = json.loads(output)

    author_val = data.get("author", {})
    author_login = (
        author_val.get("login", "unknown")
        if isinstance(author_val, dict)
        else "unknown"
    )

    files_list: list[str] = []
    raw_files = data.get("files", [])
    if isinstance(raw_files, list):
        for f in raw_files:
            if isinstance(f, dict) and "path" in f:
                files_list.append(str(f["path"]))

    return PRMetadata(
        number=int(data.get("number", 0)),
        title=str(data.get("title", "")),
        body=str(data.get("body", "")),
        author=author_login,
        url=str(data.get("url", "")),
        base_ref=str(data.get("baseRefName", "")),
        head_ref=str(data.get("headRefName", "")),
        files=files_list,
    )


def fetch_pr_diff(pr_identifier: str, repo_path: Path) -> str:
    """Fetch diff for a GitHub PR."""
    pr_clean = parse_pr_identifier(pr_identifier)
    return run_gh_command(["pr", "diff", pr_clean], repo_path)


def synthesize_pr_commit(pr_meta: PRMetadata) -> CommitInfo:
    """Create a synthesized CommitInfo from PR metadata."""
    category = "Changed"
    if match := CONVENTIONAL_REGEX.match(pr_meta.title):
        c_type = match.group("type").lower()
        is_breaking = bool(match.group("breaking"))
        if is_breaking or "BREAKING CHANGE" in pr_meta.body:
            category = "Breaking Changes"
        elif c_type in CONVENTIONAL_TYPE_MAP:
            category = CONVENTIONAL_TYPE_MAP[c_type]

    return CommitInfo(
        commit_hash=f"PR-{pr_meta.number}",
        short_hash=f"#{pr_meta.number}",
        author_name=pr_meta.author,
        author_email=f"{pr_meta.author}@users.noreply.github.com",
        date="",
        subject=pr_meta.title,
        body=pr_meta.body,
        category=category,
        pr_number=pr_meta.number,
        pr_url=pr_meta.url,
        is_revert=pr_meta.title.lower().startswith("revert"),
        is_bot=pr_meta.author.endswith("[bot]"),
        affected_files=pr_meta.files,
    )
