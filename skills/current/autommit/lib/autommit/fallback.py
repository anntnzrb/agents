"""Escalating patch application for one commit inside the temporary worktree."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from autommit.errors import AutommitError
from autommit.git import (
    GIT_ENVIRONMENT,
    GIT_ENVIRONMENT_DROPS,
    GIT_SAFE_ARGS,
    try_git,
)
from autommit.proposal import AllSelector, CommitGroup, build_commit_patch

if TYPE_CHECKING:
    from autommit.proposal import CommitChange

DEFAULT_MODE = "100644"
_RUNG_PATCH = "patch"
_RUNG_PER_FILE = "per-file"
_RUNG_PLUMBING = "plumbing"


@dataclass(frozen=True, slots=True)
class CommitWork:
    """Everything one commit application needs."""

    repo: Path
    worktree: Path
    patch_dir: Path
    index_tree: str
    ref: str
    before: str
    staged_diff: str
    zero_diff: str


def _raw_git(
    cwd: Path, *args: str, input_bytes: bytes | None = None
) -> subprocess.CompletedProcess[bytes]:
    """Run Git with byte I/O so binary blobs survive intact."""
    env = {**os.environ, **GIT_ENVIRONMENT}
    for dropped in GIT_ENVIRONMENT_DROPS:
        env.pop(dropped, None)
    return subprocess.run(
        ["git", *GIT_SAFE_ARGS, *args],
        cwd=cwd,
        check=False,
        capture_output=True,
        input=input_bytes if input_bytes is not None else b"",
        env=env,
    )


def _stderr(result: subprocess.CompletedProcess[bytes]) -> str:
    return result.stderr.decode("utf-8", "replace").strip()


def _apply_patch(worktree: Path, patch_path: Path) -> str:
    """Apply one patch file; return an empty string on success."""
    result = try_git(worktree, "apply", "--index", "--unidiff-zero", str(patch_path))
    if result.returncode != 0:
        return result.stderr.strip() or result.stdout.strip() or "git apply failed"
    return ""


def _reset_worktree(worktree: Path) -> None:
    """Discard the temporary worktree state between rungs. Never runs in the user repo."""
    _ = try_git(worktree, "reset", "--hard", "HEAD")


def _rung_patch(work: CommitWork, group: CommitGroup) -> str:
    target = work.patch_dir / "commit.patch"
    target.write_text(
        build_commit_patch(group.changes, work.staged_diff, work.zero_diff),
        encoding="utf-8",
    )
    return _apply_patch(work.worktree, target)


def _rung_per_file(work: CommitWork, group: CommitGroup) -> str:
    target = work.patch_dir / "change.patch"
    for position, change in enumerate(group.changes):
        target.write_text(
            build_commit_patch((change,), work.staged_diff, work.zero_diff),
            encoding="utf-8",
        )
        detail = _apply_patch(work.worktree, target)
        if detail:
            return f"change {position + 1} ({change.path}): {detail}"
    return ""


def _supports_plumbing(group: CommitGroup) -> bool:
    return all(isinstance(change.hunks, AllSelector) for change in group.changes)


def _file_mode(repo: Path, path: str) -> str:
    result = try_git(repo, "ls-files", "-s", "--", path)
    tokens = result.stdout.split()
    if result.returncode != 0 or not tokens:
        return DEFAULT_MODE
    return tokens[0]


def _staged_blob(repo: Path, index_tree: str, path: str) -> bytes | None:
    result = _raw_git(repo, "cat-file", "blob", f"{index_tree}:{path}")
    if result.returncode != 0:
        return None
    return result.stdout


def _rung_plumbing(work: CommitWork, group: CommitGroup) -> str:
    for change in group.changes:
        detail = _stage_change(work, change)
        if detail:
            return detail
    return ""


def _stage_change(work: CommitWork, change: CommitChange) -> str:
    blob = _staged_blob(work.repo, work.index_tree, change.path)
    target = work.worktree / change.path
    if blob is None:
        removed = _raw_git(
            work.worktree, "update-index", "--force-remove", "--", change.path
        )
        if removed.returncode != 0:
            return f"delete {change.path}: {_stderr(removed)}"
        if target.exists():
            target.unlink()
        return ""
    written = _raw_git(work.worktree, "hash-object", "-w", "--stdin", input_bytes=blob)
    if written.returncode != 0:
        return f"hash {change.path}: {_stderr(written)}"
    sha = written.stdout.decode("utf-8", "replace").strip()
    mode = _file_mode(work.repo, change.path)
    staged = _raw_git(
        work.worktree,
        "update-index",
        "--add",
        "--cacheinfo",
        f"{mode},{sha},{change.path}",
    )
    if staged.returncode != 0:
        return f"stage {change.path}: {_stderr(staged)}"
    materialized = _raw_git(work.worktree, "checkout-index", "-f", "--", change.path)
    if materialized.returncode != 0:
        return f"checkout {change.path}: {_stderr(materialized)}"
    return ""


def _failure(group: CommitGroup, detail: str, work: CommitWork) -> AutommitError:
    return AutommitError(
        "patch_failed",
        f"Unable to apply commit '{group.summary}': {detail}. "
        f"Recovery point: {work.ref} at {work.before}.",
    )


def apply_with_fallback(work: CommitWork, group: CommitGroup) -> str:
    """Apply one commit, escalating patch, then per-file, then plumbing."""
    detail = _rung_patch(work, group)
    if not detail:
        return _RUNG_PATCH
    _reset_worktree(work.worktree)
    per_file = _rung_per_file(work, group)
    if not per_file:
        return _RUNG_PER_FILE
    _reset_worktree(work.worktree)
    if not _supports_plumbing(group):
        raise _failure(group, f"patch: {detail}; per-file: {per_file}", work)
    plumbing = _rung_plumbing(work, group)
    if not plumbing:
        return _RUNG_PLUMBING
    _reset_worktree(work.worktree)
    raise _failure(
        group,
        f"patch: {detail}; per-file: {per_file}; plumbing: {plumbing}",
        work,
    )
