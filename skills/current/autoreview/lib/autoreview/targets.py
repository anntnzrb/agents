"""Target selection, Git diff extraction, multi-state capture, and bundle preparation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from autoreview.git_ops import git_run, is_dirty, validate_git_ref
from autoreview.models import SAFE_DIFF_FLAGS
from autoreview.redaction import (
    filter_diff_paths,
    is_sensitive_path,
    redact_sensitive_text,
)


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
    """Extract and sanitize unified diffs for the selected review target with path exclusion."""
    diff_cmd_base = ["diff", *SAFE_DIFF_FLAGS]

    # First discover changed paths across the scope
    if mode == "local":
        stat_args = (
            ["diff", "--name-only", *SAFE_DIFF_FLAGS, base_ref]
            if base_ref
            else ["diff", "--name-only", *SAFE_DIFF_FLAGS, "HEAD"]
        )
    elif mode == "branch":
        base = base_ref or "origin/main"
        stat_args = ["diff", "--name-only", *SAFE_DIFF_FLAGS, f"{base}...HEAD"]
    elif mode == "commit":
        sha = commit_sha or "HEAD"
        stat_args = ["diff-tree", "--name-only", "--no-commit-id", "-r", sha]
    else:
        stat_args = ["diff", "--name-only", *SAFE_DIFF_FLAGS, "HEAD"]
    stat_proc = git_run(repo, stat_args, check=False)
    raw_paths = [line.strip() for line in stat_proc.stdout.splitlines() if line.strip()]

    # Include untracked text files in local mode
    if mode == "local":
        untracked_proc = git_run(
            repo,
            ["ls-files", "--others", "--exclude-standard"],
            check=False,
        )
        raw_paths.extend(
            [
                line.strip()
                for line in untracked_proc.stdout.splitlines()
                if line.strip()
            ]
        )

    # De-duplicate
    raw_paths = sorted(set(raw_paths))
    kept_paths, redacted_paths = filter_diff_paths(raw_paths)

    # Build the path-filtered diff
    diff_text_parts: list[str] = []

    if mode == "local":
        if base_ref:
            # Base to Index + Working Tree
            if kept_paths:
                proc = git_run(
                    repo,
                    [*diff_cmd_base, base_ref, "--", *kept_paths],
                    check=False,
                )
                if proc.stdout:
                    diff_text_parts.append(proc.stdout)
        else:
            # Staged (Index) + Unstaged (Working Tree)
            if kept_paths:
                staged_proc = git_run(
                    repo,
                    [*diff_cmd_base, "--cached", "HEAD", "--", *kept_paths],
                    check=False,
                )
                if staged_proc.stdout:
                    diff_text_parts.append(staged_proc.stdout)

                unstaged_proc = git_run(
                    repo,
                    [*diff_cmd_base, "--", *kept_paths],
                    check=False,
                )
                if unstaged_proc.stdout:
                    diff_text_parts.append(unstaged_proc.stdout)

        # Include untracked files as synthetic diffs
        for untracked in kept_paths:
            p = repo / untracked
            if p.is_file() and not is_sensitive_path(untracked):
                try:
                    content = p.read_text(encoding="utf-8", errors="replace")
                    lines = content.splitlines()
                    joined_lines = "".join(f"+{line}\n" for line in lines)
                    synthetic_diff = (
                        f"diff --git a/{untracked} b/{untracked}\n"
                        f"new file mode 100644\n"
                        f"--- /dev/null\n"
                        f"+++ b/{untracked}\n"
                        f"@@ -0,0 +1,{len(lines)} @@\n"
                        f"{joined_lines}"
                    )
                    diff_text_parts.append(synthetic_diff)
                except OSError:
                    pass
        base = base_ref or "origin/main"
        if kept_paths:
            proc = git_run(
                repo,
                [*diff_cmd_base, f"{base}...HEAD", "--", *kept_paths],
                check=False,
            )
            if proc.stdout:
                diff_text_parts.append(proc.stdout)

    elif mode == "commit":
        sha = commit_sha or "HEAD"
        if kept_paths:
            proc = git_run(
                repo,
                [*diff_cmd_base, f"{sha}~1..{sha}", "--", *kept_paths],
                check=False,
            )
            if proc.stdout:
                diff_text_parts.append(proc.stdout)

    combined_diff = "\n".join(diff_text_parts)
    sanitized_diff = redact_sensitive_text(combined_diff)

    return ReviewBundle(
        mode=mode,
        base_ref=base_ref,
        commit_sha=commit_sha,
        changed_files=kept_paths,
        redacted_files=redacted_paths,
        diff_text=sanitized_diff,
    )
