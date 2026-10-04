"""Escalating patch application for one commit inside the temporary worktree."""

import os
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path

from autommit.errors import AutommitError
from autommit.git import (
    GIT_ENVIRONMENT,
    GIT_ENVIRONMENT_DROPS,
    GIT_SAFE_ARGS,
    try_git,
)
from autommit.proposal import (
    AllSelector,
    CommitChange,
    CommitGroup,
    IndicesSelector,
    LinesSelector,
    build_commit_patch,
    decode_git_path,
    parse_file_diffs,
)

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
    applied: tuple[CommitChange, ...] = ()


def _raw_git(
    cwd: Path, *args: str, input_bytes: bytes | None = None
) -> subprocess.CompletedProcess[bytes]:
    """Run Git with byte I/O so binary blobs survive intact."""
    env = {**os.environ, **GIT_ENVIRONMENT}
    for dropped in GIT_ENVIRONMENT_DROPS:
        _ = env.pop(dropped, None)
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
    result = try_git(worktree, "apply", "--index", str(patch_path))
    if result.returncode != 0:
        return result.stderr.strip() or result.stdout.strip() or "git apply failed"
    return ""


def _reset_worktree(worktree: Path) -> None:
    """Discard the temporary worktree state between rungs. Never runs in the user repo."""
    _ = try_git(worktree, "reset", "--hard", "HEAD")


def _rung_patch(work: CommitWork, group: CommitGroup) -> str:
    target = work.patch_dir / "commit.patch"
    _ = target.write_text(
        build_commit_patch(group.changes, work.staged_diff, work.zero_diff),
        encoding="utf-8",
    )
    return _apply_patch(work.worktree, target)


def _rung_per_file(work: CommitWork, group: CommitGroup) -> str:
    target = work.patch_dir / "change.patch"
    for position, change in enumerate(group.changes):
        _ = target.write_text(
            build_commit_patch((change,), work.staged_diff, work.zero_diff),
            encoding="utf-8",
        )
        detail = _apply_patch(work.worktree, target)
        if detail:
            return f"change {position + 1} ({change.path}): {detail}"
    return ""


def _file_mode(repo: Path, path: str, tree: str) -> str:
    result = try_git(repo, "ls-tree", tree, "--", path)
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
    if not isinstance(change.hunks, AllSelector):
        blob = _partial_blob(work, change)
    return _stage_blob(work, change.path, blob)


def _partial_blob(work: CommitWork, change: CommitChange) -> bytes:
    """Render cumulative edits at original offsets, never searching for a preimage."""
    zero = next(
        f for f in parse_file_diffs(work.zero_diff) if f.filename == change.path
    )
    regular = next(
        f for f in parse_file_diffs(work.staged_diff) if f.filename == change.path
    )
    source = change.path
    for line in regular.content.split("\n"):
        if line.startswith("rename from "):
            source = decode_git_path(line.removeprefix("rename from "))
    base = _staged_blob(work.repo, work.before, source) or b""
    lines = base.split(b"\n")
    if base.endswith(b"\n"):
        _ = lines.pop()
    lines = [line + b"\n" for line in lines]
    if base and not base.endswith(b"\n"):
        lines[-1] = lines[-1].removesuffix(b"\n")
    if not base:
        lines = []
    selectors = [c.hunks for c in (*work.applied, change) if c.path == change.path]

    def selected(position: int, old: int) -> bool:
        for selector in selectors:
            if (
                isinstance(selector, LinesSelector)
                and selector.start <= position <= selector.end
            ):
                return True
            if isinstance(selector, IndicesSelector):
                for hunk in regular.hunks:
                    start = hunk.old_start - 1 if hunk.old_lines else hunk.old_start
                    if (
                        hunk.index in selector.indices
                        and start <= old <= start + hunk.old_lines
                    ):
                        return True
        return False

    result: list[bytes] = []
    cursor = 0
    for hunk in zero.hunks:
        offset = hunk.old_start - 1 if hunk.old_lines else hunk.old_start
        result.extend(lines[cursor:offset])
        body = hunk.content.split("\n")[1:]
        old = offset
        new = max(1, hunk.new_start)
        for index, line in enumerate(body):
            if line[:1] not in ("-", "+"):
                continue
            payload = line[1:].encode("utf-8", "surrogateescape")
            if index + 1 >= len(body) or not body[index + 1].startswith(
                "\\ No newline"
            ):
                payload += b"\n"
            if line.startswith("-"):
                if not selected(new, old):
                    result.append(lines[old])
                old += 1
            else:
                if selected(new, offset):
                    result.append(payload)
                new += 1
        cursor = offset + hunk.old_lines
    result.extend(lines[cursor:])
    return b"".join(result)


def _stage_blob(
    work: CommitWork, path: str, blob: bytes | None, *, mode: str | None = None
) -> str:
    change = CommitChange(path, AllSelector())
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
    mode = mode or _file_mode(work.repo, change.path, work.index_tree)
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
        f"Unable to apply commit '{group.summary}': {detail}. Recovery point: {work.ref} at {work.before}.",
    )


def apply_with_fallback(work: CommitWork, group: CommitGroup) -> str:
    """Apply one commit, escalating patch, then per-file, then plumbing."""
    partial = tuple(c for c in group.changes if not isinstance(c.hunks, AllSelector))
    whole = tuple(c for c in group.changes if isinstance(c.hunks, AllSelector))
    if partial:
        if whole:
            _ = apply_with_fallback(work, replace(group, changes=whole))
        for change in partial:
            detail = _stage_change(work, change)
            if detail:
                raise _failure(group, detail, work)
            work = replace(work, applied=(*work.applied, change))
        return _RUNG_PLUMBING
    detail = _rung_patch(work, group)
    if not detail:
        return _RUNG_PATCH
    _reset_worktree(work.worktree)
    per_file = _rung_per_file(work, group)
    if not per_file:
        return _RUNG_PER_FILE
    _reset_worktree(work.worktree)
    plumbing = _rung_plumbing(work, group)
    if not plumbing:
        return _RUNG_PLUMBING
    _reset_worktree(work.worktree)
    raise _failure(
        group,
        f"patch: {detail}; per-file: {per_file}; plumbing: {plumbing}",
        work,
    )


def stage_edited_moves(work: CommitWork) -> bool:
    """Stage detected edited renames with the source blob and source mode."""
    files = [
        file
        for file in parse_file_diffs(work.staged_diff)
        if "\nrename from " in file.content and file.hunks
    ]
    for file in files:
        source = next(
            decode_git_path(line.removeprefix("rename from "))
            for line in file.content.split("\n")
            if line.startswith("rename from ")
        )
        blob = _staged_blob(work.repo, work.before, source)
        mode = _file_mode(work.repo, source, work.before)
        for path, content in ((file.filename, blob), (source, None)):
            if detail := _stage_blob(work, path, content, mode=mode):
                raise AutommitError("patch_failed", detail)
    return bool(files)
