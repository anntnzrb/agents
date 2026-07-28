"""Narrow, argv-only adapter for the Git observations this controller needs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import Sequence

from .errors import GitError, GitMissingError, RefusalError
from .models import GitWorktree, Repository


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: bytes
    stderr: bytes


def _run(repo: Path, args: Sequence[str], *, check: bool = True) -> CommandResult:
    """Run Git with an explicit repository and no shell interpretation."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            shell=False,
        )
    except FileNotFoundError as error:
        raise GitMissingError() from error
    if check and result.returncode != 0:
        raise GitError(
            "git_command_failed",
            "Git command failed",
            {
                "argv": list(args),
                "returncode": result.returncode,
                "stderr": result.stderr.decode("utf-8", "replace"),
            },
        )
    return CommandResult(result.returncode, result.stdout, result.stderr)


def _physical_directory(path: Path, *, label: str) -> Path:
    try:
        resolved = path.expanduser().resolve(strict=True)
    except OSError as error:
        raise RefusalError("repository_unavailable", f"{label} cannot be resolved physically", {"path": str(path)}) from error
    if not resolved.is_dir():
        raise RefusalError("repository_unusable", f"{label} is not a directory", {"path": str(path)})
    return resolved


def _single_line(repo: Path, args: Sequence[str]) -> str:
    value = _run(repo, args).stdout
    if not value.endswith(b"\n") or b"\n" in value[:-1] or b"\x00" in value:
        raise GitError("git_output_malformed", "Git returned malformed line output", {"argv": list(args)})
    try:
        return value[:-1].decode("utf-8", "strict")
    except UnicodeDecodeError as error:
        raise GitError("git_output_malformed", "Git returned non-UTF-8 line output", {"argv": list(args)}) from error


def _valid_full_ref(ref: str) -> bool:
    if not ref.startswith("refs/") or ref.endswith(("/", ".")) or ".." in ref or "@{" in ref or "//" in ref:
        return False
    if any(ord(character) <= 0x20 or ord(character) == 0x7F or character in "~^:?*[\\" for character in ref):
        return False
    return all(component and not component.startswith(".") and not component.endswith(".") and not component.endswith(".lock") for component in ref.split("/"))

def parse_worktree_porcelain(raw: bytes) -> tuple[GitWorktree, ...]:
    """Parse only the documented NUL-delimited worktree porcelain grammar."""
    if not raw or not raw.endswith(b"\x00"):
        raise GitError("git_output_malformed", "Git worktree porcelain is not NUL terminated", {})
    records: list[list[bytes]] = []
    current: list[bytes] = []
    for item in raw[:-1].split(b"\x00"):
        if item == b"":
            if not current:
                raise GitError("git_output_malformed", "Git worktree porcelain contains an empty record", {})
            records.append(current)
            current = []
        else:
            current.append(item)
    if current:
        raise GitError("git_output_malformed", "Git worktree porcelain has an unterminated record", {})
    if not records:
        raise GitError("git_output_malformed", "Git returned no worktrees", {})

    parsed: list[GitWorktree] = []
    for fields in records:
        values: dict[str, bytes] = {}
        flags: set[str] = set()
        for field in fields:
            key, separator, value = field.partition(b" ")
            if key in {b"detached", b"bare"}:
                if separator or key in flags:
                    raise GitError("git_output_malformed", "Git worktree porcelain has malformed flags", {})
                flags.add(key.decode("ascii"))
                continue
            try:
                text_key = key.decode("ascii", "strict")
            except UnicodeDecodeError as error:
                raise GitError("git_output_malformed", "Git worktree porcelain has an invalid field name", {}) from error
            if key in {b"locked", b"prunable"}:
                if text_key in values:
                    raise GitError("git_output_malformed", "Git worktree porcelain has unknown or duplicate fields", {})
                values[text_key] = value if separator else b""
                continue
            if key not in {b"worktree", b"HEAD", b"branch"} or not separator or text_key in values:
                raise GitError("git_output_malformed", "Git worktree porcelain has unknown or duplicate fields", {})
            values[text_key] = value
        if "worktree" not in values or "HEAD" not in values:
            raise GitError("git_output_malformed", "Git worktree porcelain lacks required fields", {})
        if "branch" in values and "detached" in flags:
            raise GitError("git_output_malformed", "Git worktree porcelain says branch and detached", {})
        if "bare" in flags:
            raise RefusalError("repository_bare", "Bare repositories cannot host managed worktrees", {})
        try:
            raw_path = Path(values["worktree"].decode("utf-8", "strict"))
            if not raw_path.is_absolute():
                raise ValueError("worktree path is not absolute")
            worktree_path = raw_path.resolve(strict=False)
            head = values["HEAD"].decode("ascii", "strict")
            branch = values.get("branch")
            locked = values.get("locked")
            prunable = values.get("prunable")
            ref = None if branch is None else branch.decode("utf-8", "strict")
            lock_reason = None if locked is None else locked.decode("utf-8", "strict")
            prune_reason = None if prunable is None else prunable.decode("utf-8", "strict")
        except (OSError, UnicodeDecodeError, ValueError) as error:
            raise GitError("git_output_malformed", "Git worktree porcelain has invalid paths or text", {}) from error
        if (
            not worktree_path.is_absolute()
            or len(head) not in {40, 64}
            or any(character not in "0123456789abcdef" for character in head.lower())
            or (ref is not None and not _valid_full_ref(ref))
        ):
            raise GitError("git_output_malformed", "Git worktree porcelain has invalid required values", {})
        parsed.append(GitWorktree(worktree_path, head, ref, "detached" in flags, lock_reason, prune_reason))
    return tuple(parsed)


def inspect_repository(repo: Path) -> Repository:
    """Return physical identity and a strict linked-worktree snapshot."""
    source = _physical_directory(repo, label="repository")
    bare = _single_line(source, ["rev-parse", "--is-bare-repository"])
    if bare == "true":
        raise RefusalError("repository_bare", "Bare repositories cannot host managed worktrees", {"repo": str(source)})
    if bare != "false":
        raise GitError("git_output_malformed", "Git returned an invalid bare-repository result", {"value": bare})
    requested_root = _physical_directory(Path(_single_line(source, ["rev-parse", "--show-toplevel"])), label="repository root")
    common = _physical_directory(
        Path(_single_line(source, ["rev-parse", "--path-format=absolute", "--git-common-dir"])),
        label="common Git directory",
    )
    worktrees = parse_worktree_porcelain(_run(requested_root, ["worktree", "list", "--porcelain", "-z"]).stdout)
    primary = worktrees[0].path
    return Repository(common, primary, worktrees)

def validate_branch(repo: Path, branch: str) -> None:
    if not branch or "\x00" in branch or branch.startswith("-"):
        raise RefusalError("invalid_branch", "Branch name is invalid", {"branch": branch})
    result = _run(repo, ["check-ref-format", "--branch", branch], check=False)
    if result.returncode != 0:
        raise RefusalError("invalid_branch", "Branch name is invalid", {"branch": branch})


def local_branch_exists(repo: Path, branch: str) -> bool:
    result = _run(repo, ["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], check=False)
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    raise GitError("git_command_failed", "Could not inspect local branch", {"branch": branch, "returncode": result.returncode, "stderr": result.stderr.decode("utf-8", "replace")})

def worktree_add(repo: Path, path: Path, mode: str, *, base: str | None, branch: str | None) -> None:
    if mode == "new-branch":
        if base is None or branch is None:
            raise ValueError("new-branch requires base and branch")
        _run(repo, ["worktree", "add", "--checkout", "-b", branch, str(path), base])
    elif mode == "existing-branch":
        if branch is None:
            raise ValueError("existing-branch requires branch")
        _run(repo, ["worktree", "add", "--checkout", str(path), branch])
    elif mode == "detached-ephemeral":
        if base is None:
            raise ValueError("detached-ephemeral requires base")
        _run(repo, ["worktree", "add", "--detach", str(path), base])
    else:
        raise ValueError(f"unknown mode: {mode}")


def worktree_remove(repo: Path, path: Path) -> None:
    _run(repo, ["worktree", "remove", str(path)])


def worktree_dirty(path: Path) -> bool:
    result = _run(path, ["status", "--porcelain=v1", "-z"])
    return bool(result.stdout)


def worktree_head_and_ref(path: Path) -> tuple[str, str | None]:
    head = _single_line(path, ["rev-parse", "HEAD"])
    symbolic = _run(path, ["symbolic-ref", "-q", "HEAD"], check=False)
    if symbolic.returncode == 1:
        return head, None
    if symbolic.returncode != 0 or not symbolic.stdout.endswith(b"\n"):
        raise GitError("git_command_failed", "Could not determine worktree ref", {"path": str(path)})
    return head, symbolic.stdout[:-1].decode("utf-8", "strict")
