"""Target selection, Git diff extraction, and bundle preparation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from autoreview.git_ops import git_run, is_dirty, validate_git_ref
from autoreview.redaction import filter_diff_paths, redact_sensitive_text


@dataclass(frozen=True, slots=True)
class ReviewBundle:
    mode: str
    base_ref: str | None
    commit_sha: str | None
    changed_files: list[str]
    redacted_files: list[str]
    diff_text: str


def choose_review_target(
    repo: Path,
    mode: str,
    base_ref: str | None,
    commit_ref: str | None,
) -> tuple[str, str | None, str | None]:
    """Resolve review mode and exact commit references."""
    resolved_mode = "local" if mode == "uncommitted" else mode

    if resolved_mode == "auto":
        resolved_mode = "local" if is_dirty(repo) else "branch"

    if resolved_mode == "local":
        pinned_base = (
            validate_git_ref(repo, base_ref, "base") if base_ref is not None else None
        )
        return "local", pinned_base, None

    if resolved_mode == "commit":
        target_commit = commit_ref or "HEAD"
        resolved_commit = validate_git_ref(repo, target_commit, "commit")
        return "commit", None, resolved_commit

    if resolved_mode == "branch":
        target_base = base_ref or "origin/main"
        pinned_base = validate_git_ref(repo, target_base, "base")
        return "branch", pinned_base, None

    raise SystemExit(f"unsupported review mode: {mode}")


def capture_diff_bundle(
    repo: Path,
    mode: str,
    base_ref: str | None = None,
    commit_sha: str | None = None,
) -> ReviewBundle:
    """Extract and sanitize unified diffs for the selected review target."""
    diff_args: list[str] = ["diff", "--no-color", "--no-ext-diff"]

    if mode == "local":
        if base_ref:
            diff_args.extend([f"{base_ref}...HEAD"])
        else:
            diff_args.append("HEAD")
    elif mode == "branch":
        base = base_ref or "origin/main"
        diff_args.extend([f"{base}...HEAD"])
    elif mode == "commit":
        sha = commit_sha or "HEAD"
        diff_args.extend([f"{sha}~1..{sha}"])

    proc = git_run(repo, diff_args, check=False)
    raw_diff = proc.stdout

    # Extract changed filenames from git status or diff numstat
    stat_proc = git_run(
        repo,
        ["diff", "--name-only", *diff_args[1:]],
        check=False,
    )
    raw_paths = [line.strip() for line in stat_proc.stdout.splitlines() if line.strip()]

    kept_paths, redacted_paths = filter_diff_paths(raw_paths)
    sanitized_diff = redact_sensitive_text(raw_diff)

    return ReviewBundle(
        mode=mode,
        base_ref=base_ref,
        commit_sha=commit_sha,
        changed_files=kept_paths,
        redacted_files=redacted_paths,
        diff_text=sanitized_diff,
    )
