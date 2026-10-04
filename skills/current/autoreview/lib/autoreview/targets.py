"""Resolve Git targets and collect redacted patches and source snapshots."""

from dataclasses import dataclass
from pathlib import Path

from autoreview.git_ops import git_run, is_dirty, validate_git_ref
from autoreview.models import SAFE_DIFF_FLAGS
from autoreview.redaction import filter_diff_paths, redact_sensitive_text


@dataclass(frozen=True, slots=True)
class ReviewBundle:
    mode: str
    base_ref: str
    commit_sha: str
    changed_files: list[str]
    redacted_files: list[str]
    diff_text: str
    file_stats: list[str]
    snapshots: dict[str, dict[str, str]]


def choose_review_target(
    repo: Path,
    mode: str,
    base_ref: str | None,
    commit_ref: str | None,
) -> tuple[str, str | None, str | None]:
    """Pin requested refs; auto uses dirty local work or origin/main."""
    mode = "local" if mode == "uncommitted" else mode
    if mode == "auto":
        mode = "local" if is_dirty(repo) else "branch"
    if mode == "local":
        return (
            mode,
            validate_git_ref(repo, base_ref, "base") if base_ref else None,
            None,
        )
    if mode == "branch":
        return mode, validate_git_ref(repo, base_ref or "origin/main", "base"), None
    if mode == "commit":
        return mode, None, validate_git_ref(repo, commit_ref or "HEAD", "commit")
    raise ValueError(f"unsupported review mode: {mode}")


def read_snapshot(repo: Path, path: str, state: str) -> str | None:
    """Read a Git blob or a contained, regular working file."""
    if state == "WORKTREE":
        target = repo / path
        if (
            target.is_symlink()
            or not target.is_file()
            or not target.resolve().is_relative_to(repo)
        ):
            return None
        return target.read_text(encoding="utf-8", errors="surrogateescape")
    spec = f":{path}" if state == "INDEX" else f"{state}:{path}"
    proc = git_run(repo, ["show", spec], check=False)
    return proc.stdout if proc.returncode == 0 else None


def capture_diff_bundle(
    repo: Path,
    mode: str,
    base_ref: str | None = None,
    commit_sha: str | None = None,
) -> ReviewBundle:
    """Capture each selected state without executing external diff commands."""
    head = commit_sha or validate_git_ref(repo, "HEAD")
    base = base_ref or head
    if mode == "branch":
        base = git_run(repo, ["merge-base", base, head]).stdout.strip()
    if mode == "commit":
        parents = git_run(
            repo, ["rev-list", "--parents", "-n", "1", head]
        ).stdout.split()
        base = (
            parents[1]
            if len(parents) > 1
            else git_run(repo, ["hash-object", "-t", "tree", "--stdin"]).stdout.strip()
        )
    comparisons: list[tuple[str, list[str]]] = (
        [("INDEX", ["--cached", base]), ("WORKTREE", [])]
        if mode == "local" and base_ref is None
        else [("INDEX", ["--cached", base]), ("WORKTREE", [base])]
        if mode == "local"
        else [(head, [base, head])]
    )
    patches: list[str] = []
    stats: list[str] = []
    paths: set[str] = set()
    redacted: set[str] = set()
    snapshots: dict[str, dict[str, str]] = {}
    for state, refs in comparisons:
        names = git_run(
            repo, ["diff", *SAFE_DIFF_FLAGS, "--name-only", "-z", *refs]
        ).stdout
        kept, hidden = filter_diff_paths([p for p in names.split("\0") if p])
        paths.update(kept)
        redacted.update(hidden)
        if not kept:
            continue
        patch = git_run(repo, ["diff", *SAFE_DIFF_FLAGS, *refs, "--", *kept]).stdout
        patches.append(f"=== {state} ===\n{patch}")
        numstat = git_run(
            repo, ["diff", *SAFE_DIFF_FLAGS, "--numstat", *refs, "--", *kept]
        ).stdout
        for row in numstat.splitlines():
            added, removed, path = row.split("\t", 2)
            stats.append(f"{state}: {path} +{added} -{removed}")
        for path in kept:
            if (content := read_snapshot(repo, path, state)) is not None:
                snapshots.setdefault(path, {})[state] = content
    if mode == "local":
        names = git_run(
            repo, ["ls-files", "--others", "--exclude-standard", "-z"]
        ).stdout
        kept, hidden = filter_diff_paths([p for p in names.split("\0") if p])
        redacted.update(hidden)
        for path in kept:
            content = read_snapshot(repo, path, "WORKTREE")
            if content is None:
                continue
            paths.add(path)
            snapshots.setdefault(path, {})["WORKTREE"] = content
            lines = content.splitlines()
            patch = "".join(f"+{line}\n" for line in lines)
            patches.append(
                f"=== WORKTREE (untracked) ===\ndiff --git a/{path} b/{path}\n--- /dev/null\n+++ b/{path}\n@@ -0,0 +1,{len(lines)} @@\n{patch}"
            )
            stats.append(f"WORKTREE: {path} +{len(lines)} -0")
    return ReviewBundle(
        mode,
        base,
        head,
        sorted(paths),
        sorted(redacted),
        redact_sensitive_text("\n".join(patches)),
        stats,
        snapshots,
    )
