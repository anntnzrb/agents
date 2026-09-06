"""Git history, commit parsing, and diff extraction engine."""

import re
import subprocess
from collections.abc import Sequence
from pathlib import Path

from models import CONVENTIONAL_TYPE_MAP, CommitInfo

BOT_USERS: frozenset[str] = frozenset(
    {
        "actions-user",
        "dependabot[bot]",
        "github-actions[bot]",
        "opencode",
        "opencode-agent[bot]",
        "renovate[bot]",
    }
)

PR_REGEX: re.Pattern[str] = re.compile(r"\(#(\d+)\)|pull request #(\d+)", re.IGNORECASE)
CONVENTIONAL_REGEX: re.Pattern[str] = re.compile(
    r"^(?P<type>[a-zA-Z]+)(?:\((?P<scope>[^)]+)\))?(?P<breaking>!)?:\s*(?P<desc>.+)$"
)

MIN_RECORD_PARTS: int = 7


def run_git_command(args: Sequence[str], repo_path: Path) -> str:
    """Run a git command safely returning stripped stdout."""
    result = subprocess.run(
        ["git", *args],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        msg = result.stderr.strip() or f"git {' '.join(args)} failed"
        raise RuntimeError(msg)
    return result.stdout.strip()


def parse_commit_record(record: str, repo_path: Path) -> CommitInfo | None:
    """Parse one raw delimited commit record into CommitInfo."""
    if not record.strip():
        return None

    parts = record.split("\x00")
    if len(parts) < MIN_RECORD_PARTS:
        return None

    c_hash, s_hash, aname, aemail, date_str, subject, body = parts[:7]
    c_hash = c_hash.strip()
    s_hash = s_hash.strip()
    aname = aname.strip()
    aemail = aemail.strip()
    date_str = date_str.strip()
    subject = subject.strip()
    body = body.strip()

    is_bot = aname.lower() in BOT_USERS or aemail.lower() in BOT_USERS
    is_revert = subject.lower().startswith("revert") or 'revert "' in subject.lower()

    pr_number: int | None = None
    pr_match = PR_REGEX.search(subject)
    if pr_match:
        pr_str = pr_match.group(1) or pr_match.group(2)
        if pr_str and pr_str.isdigit():
            pr_number = int(pr_str)

    category = "Changed"
    conv_match = CONVENTIONAL_REGEX.match(subject)
    if conv_match:
        c_type = conv_match.group("type").lower()
        is_breaking = bool(conv_match.group("breaking"))
        if is_breaking or "BREAKING CHANGE" in body:
            category = "Breaking Changes"
        elif c_type in CONVENTIONAL_TYPE_MAP:
            category = CONVENTIONAL_TYPE_MAP[c_type]
    elif is_revert:
        category = "Changed"

    affected_files: list[str] = []
    try:
        files_out = run_git_command(
            ["show", "--name-only", "--format=", c_hash],
            repo_path,
        )
        if files_out:
            affected_files = [f.strip() for f in files_out.splitlines() if f.strip()]
    except RuntimeError:
        affected_files = []

    return CommitInfo(
        commit_hash=c_hash,
        short_hash=s_hash,
        author_name=aname,
        author_email=aemail,
        date=date_str,
        subject=subject,
        body=body,
        category=category,
        pr_number=pr_number,
        is_revert=is_revert,
        is_bot=is_bot,
        affected_files=affected_files,
    )


def extract_commits_in_range(range_spec: str, repo_path: Path) -> list[CommitInfo]:
    """Extract and parse all commits in a git revision range."""
    delimiter = "%x00"
    record_end = "%x1e"
    fmt = f"%H{delimiter}%h{delimiter}%an{delimiter}%ae{delimiter}%ad{delimiter}%s{delimiter}%b{record_end}"

    cmd = ["log", f"--format={fmt}", range_spec]
    raw_output = run_git_command(cmd, repo_path)
    if not raw_output:
        return []

    commits: list[CommitInfo] = []
    raw_records = raw_output.split("\x1e")
    for raw in raw_records:
        parsed = parse_commit_record(raw, repo_path)
        if parsed is not None:
            commits.append(parsed)

    return commits


def get_diff_stat(
    repo_path: Path,
    range_spec: str | None = None,
    staged: bool = False,
) -> str:
    """Get diffstat output for a range or staged changes."""
    args = ["diff", "--stat"]
    if staged:
        args.append("--staged")
    elif range_spec:
        args.append(range_spec)
    return run_git_command(args, repo_path)


def get_diff_snippet(
    repo_path: Path,
    range_spec: str | None = None,
    staged: bool = False,
    max_lines: int = 150,
) -> str:
    """Get truncated diff snippet for semantic prompt context."""
    args = ["diff"]
    if staged:
        args.append("--staged")
    elif range_spec:
        args.append(range_spec)
    raw_diff = run_git_command(args, repo_path)
    lines = raw_diff.splitlines()
    if len(lines) <= max_lines:
        return raw_diff
    truncated = lines[:max_lines]
    truncated.append(f"... (truncated {len(lines) - max_lines} diff lines)")
    return "\n".join(truncated)


def get_staged_files(repo_path: Path) -> list[str]:
    """List all currently staged files."""
    out = run_git_command(["diff", "--name-only", "--staged"], repo_path)
    return [line.strip() for line in out.splitlines() if line.strip()]
