"""Transactional autommit workflow independent of any model provider."""

from __future__ import annotations

import contextlib
import json
import os
import shlex
import subprocess
import tempfile
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Final, Literal

from autommit.errors import AutommitError, RefusalError
from autommit.fallback import CommitWork, apply_with_fallback
from autommit.git import GIT_DIFF_FLAGS, run_git, try_git
from autommit.inventory import build_inventory, inventory_payload
from autommit.proposal import (
    AtomicityDecision,
    CommitGroup,
    CommitProposal,
    changed_hunk_count,
    compute_apply_order,
    normalize_atomicity_decision,
    normalize_proposal,
    parse_file_diffs,
    requires_atomicity_review,
    validate_proposal_coverage,
)
from autommit.transaction import (
    Receipt,
    RecoveryPoint,
    clear_recovery_point,
    operation_lock,
    read_receipt,
    remove_receipt,
    write_receipt,
    write_recovery_point,
)

MAX_POLICY_FILE_BYTES = 32 * 1024
MAX_PLAN_FILE_BYTES = 1024 * 1024
MAX_LOG_ENTRIES = 8
SMOKE_TIMEOUT_SECONDS = 300
_MIN_SPLIT_COMMITS = 2

_BLOCKING_GIT_FILES: Final[tuple[str, ...]] = (
    "MERGE_HEAD",
    "CHERRY_PICK_HEAD",
    "REVERT_HEAD",
)

# A completed rebase can leave REBASE_HEAD behind, so the directories Git writes
# for the lifetime of the operation are the authoritative rebase markers.
_BLOCKING_GIT_DIRECTORIES: Final[tuple[str, ...]] = ("rebase-merge", "rebase-apply")


@dataclass(frozen=True, slots=True)
class Evidence:
    """Git state bound into a prepared snapshot token."""

    ref: str
    before: str
    index_tree: str


def _git_dir(cwd: Path) -> Path:
    """Resolve the worktree-local Git directory."""
    value_str = run_git(cwd, "rev-parse", "--absolute-git-dir")
    return Path(value_str.strip()).resolve()


def _blocking_state(git_dir: Path) -> str | None:
    """Detect an in-progress Git operation that makes mutation unsafe."""
    for name in _BLOCKING_GIT_FILES:
        if (git_dir / name).exists():
            return (
                f"A Git operation is in progress ({name}); "
                "finish or abort it before running autommit."
            )
    for name in _BLOCKING_GIT_DIRECTORIES:
        if (git_dir / name).is_dir():
            return (
                f"A Git rebase is in progress ({name}); "
                "finish or abort it before running autommit."
            )
    return None


def _current_evidence(cwd: Path, *, index_file: Path | None = None) -> Evidence:
    symbolic_ref = try_git(cwd, "symbolic-ref", "--quiet", "HEAD")
    ref = symbolic_ref.stdout.strip() if symbolic_ref.returncode == 0 else ""
    head_rev = try_git(cwd, "rev-parse", "HEAD")
    before = head_rev.stdout.strip() if head_rev.returncode == 0 else ""
    env = {"GIT_INDEX_FILE": str(index_file)} if index_file else None
    tree_out = run_git(cwd, "write-tree", env=env)
    index_tree = tree_out.strip()
    if not ref or not before or not index_tree:
        raise AutommitError(
            "unsupported_checkout",
            "Autommit requires a branch checkout with an existing HEAD.",
        )
    return Evidence(ref, before, index_tree)


def _snapshot_token(evidence: Evidence) -> str:
    canonical = json.dumps(
        {
            "before": evidence.before,
            "index_tree": evidence.index_tree,
            "ref": evidence.ref,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(canonical.encode()).hexdigest()


def _assert_snapshot(cwd: Path, snapshot: str) -> Evidence:
    evidence = _current_evidence(cwd)
    if _snapshot_token(evidence) != snapshot:
        raise RefusalError(
            "snapshot_changed",
            "Autommit branch, HEAD, or index changed after preparation.",
        )
    return evidence


def _staged_files(cwd: Path, *, index_file: Path | None = None) -> tuple[str, ...]:
    env = {"GIT_INDEX_FILE": str(index_file)} if index_file else None
    output = run_git(cwd, "diff", "--cached", "--name-only", "-z", "--", env=env)
    return tuple(item for item in output.split("\0") if item)


def _staged_diff(
    cwd: Path, *, zero_context: bool = False, index_file: Path | None = None
) -> str:
    arguments = [
        "diff",
        "--cached",
        "--binary",
        "--src-prefix=a/",
        "--dst-prefix=b/",
        *GIT_DIFF_FLAGS,
    ]
    if zero_context:
        arguments.append("--unified=0")
    arguments.extend(["--", "."])
    env = {"GIT_INDEX_FILE": str(index_file)} if index_file else None
    return run_git(cwd, *arguments, env=env)


def _commit_exists(cwd: Path, sha: str) -> bool:
    result = try_git(cwd, "cat-file", "-e", f"{sha}^{{commit}}")
    return result.returncode == 0


def _tree_for_commit(cwd: Path, sha: str) -> str:
    return run_git(cwd, "rev-parse", f"{sha}^{{tree}}").strip()


def _cas_ref(cwd: Path, ref: str, target: str, expected_before: str) -> None:
    result = try_git(cwd, "update-ref", ref, target, expected_before)
    if result.returncode != 0:
        raise RefusalError(
            "ref_conflict",
            f"Ref update failed via CAS ({expected_before} -> {target}): "
            f"{result.stderr.strip()}",
        )


def _repository_policy(cwd: Path) -> str:
    policies: list[str] = []
    candidates = (
        cwd / "AGENTS.md",
        cwd / "CLAUDE.md",
        cwd / ".cursorrules",
        cwd / "CONTRIBUTING.md",
    )
    for candidate in candidates:
        if candidate.is_file() and not candidate.is_symlink():
            try:
                with candidate.open("rb") as handle:
                    content = handle.read(MAX_POLICY_FILE_BYTES)
                policies.append(
                    f"## {candidate.name}\n" + content.decode("utf-8", "replace")
                )
            except OSError:
                continue
    log_output = run_git(
        cwd,
        "log",
        f"-{MAX_LOG_ENTRIES}",
        "--format=### %h %s%n%b",
        "--no-decorate",
    )
    if log_output.strip():
        policies.append("## Recent Commits\n" + log_output.strip())
    return "\n\n".join(policies)


def _recover_receipt(cwd: Path, git_dir: Path, receipt: Receipt) -> dict[str, object]:
    evidence = _current_evidence(cwd)
    if evidence.ref != receipt.ref:
        raise RefusalError(
            "recovery_conflict",
            f"Receipt is for branch {receipt.ref}, but checkout is on {evidence.ref}.",
        )
    if evidence.index_tree != receipt.index_tree and evidence.before != receipt.after:
        raise RefusalError(
            "recovery_conflict",
            "Index tree changed after prepared receipt was written.",
        )
    if not _commit_exists(cwd, receipt.after):
        raise AutommitError(
            "invalid_receipt",
            "Receipt target commit object does not exist in repository.",
        )
    target_tree = _tree_for_commit(cwd, receipt.after)
    if target_tree != receipt.index_tree:
        raise AutommitError(
            "invalid_receipt",
            "Receipt target commit does not match staged index tree.",
        )
    current_ref = run_git(cwd, "rev-parse", receipt.ref).strip()
    if current_ref == receipt.after:
        remove_receipt(git_dir)
        return {
            "status": "recovered",
            "recovered_state": "already_committed",
            "ref": receipt.ref,
            "after": receipt.after,
        }
    if current_ref == receipt.before:
        _cas_ref(cwd, receipt.ref, receipt.after, receipt.before)
        remove_receipt(git_dir)
        return {
            "status": "recovered",
            "recovered_state": "applied_cas",
            "ref": receipt.ref,
            "after": receipt.after,
        }
    raise RefusalError(
        "recovery_conflict",
        f"Cannot recover receipt: ref {receipt.ref} is at {current_ref}, "
        f"expected {receipt.before} or {receipt.after}.",
    )


def _consume_or_recover(cwd: Path, git_dir: Path) -> dict[str, object] | None:
    receipt = read_receipt(git_dir)
    if receipt is None:
        return None
    if receipt.state == "published":
        remove_receipt(git_dir)
        return None
    return _recover_receipt(cwd, git_dir, receipt)


def prepare(
    cwd: Path,
    context: tuple[str, ...],
    *,
    scope: Literal["auto", "staged", "all"] = "auto",
) -> dict[str, object]:
    """Recover if needed, stage per scope, and expose exact planning evidence."""
    git_dir = _git_dir(cwd)
    with operation_lock(git_dir):
        if blocking := _blocking_state(git_dir):
            raise RefusalError("in_progress_state", blocking)
        if recovered := _consume_or_recover(cwd, git_dir):
            return recovered
        staged = _staged_files(cwd)
        if scope == "all" or (scope == "auto" and not staged):
            run_git(cwd, "add", "--all")
            staged = _staged_files(cwd)
        elif not staged:
            raise AutommitError(
                "no_staged_changes", "No staged changes found to commit."
            )
        if not staged:
            raise AutommitError("no_changes", "No local changes to commit.")
        evidence = _current_evidence(cwd)
        diff = _staged_diff(cwd)
        zero_diff = _staged_diff(cwd, zero_context=True)
        inventory = build_inventory(cwd, staged, diff)
        repo_context = _repository_policy(cwd)
        return {
            "status": "prepared",
            "snapshot": _snapshot_token(evidence),
            "ref": evidence.ref,
            "before": evidence.before,
            "index_tree": evidence.index_tree,
            "staged_files": list(staged),
            "staged_file_count": len(staged),
            "changed_hunk_count": changed_hunk_count(diff),
            "diff": diff,
            "zero_diff": zero_diff,
            "inventory": inventory_payload(inventory),
            "repository_context": repo_context,
            "user_context": list(context),
            "context": "\n\n".join(context),
        }


def read_json_file(path: Path, kind: str) -> object:
    """Read bounded JSON from a regular file."""
    limit = (
        MAX_PLAN_FILE_BYTES
        if ("plan" in kind or "decision" in kind)
        else MAX_POLICY_FILE_BYTES
    )
    if not path.exists() or path.is_symlink() or not path.is_file():
        raise AutommitError(
            "invalid_file", f"Autommit {kind} file must be an existing regular file."
        )
    try:
        with path.open("rb") as handle:
            content = handle.read(limit + 1)
    except OSError as error:
        raise AutommitError(
            "file_io", f"Unable to read {kind} file: {error}."
        ) from error
    if len(content) > limit:
        raise AutommitError(
            "invalid_file",
            f"Autommit {kind} file exceeds {limit} bytes; reduce the scope and re-run.",
        )
    try:
        return json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AutommitError(
            "invalid_json", f"Autommit {kind} is not valid JSON: {error}."
        ) from error


def _load_validated_plan(
    cwd: Path,
    snapshot: str,
    plan_file: Path,
) -> tuple[Evidence, CommitProposal, tuple[str, ...], str, bool]:
    evidence = _assert_snapshot(cwd, snapshot)
    raw_plan = read_json_file(plan_file, "plan")
    proposal = normalize_proposal(raw_plan)
    staged = _staged_files(cwd)
    diff = _staged_diff(cwd)
    errors = validate_proposal_coverage(proposal, staged, parse_file_diffs(diff))
    if errors:
        raise AutommitError("invalid_plan", "Invalid split plan: " + "; ".join(errors))
    review = requires_atomicity_review(proposal, diff)
    return evidence, proposal, staged, diff, review


def validate_plan(
    cwd: Path,
    snapshot: str,
    plan_file: Path,
    *,
    require_split: bool = False,
) -> dict[str, object]:
    """Validate a model plan against the prepared snapshot."""
    _, proposal, staged, diff, review = _load_validated_plan(cwd, snapshot, plan_file)
    if require_split and len(proposal.commits) < _MIN_SPLIT_COMMITS:
        raise AutommitError(
            "split_required", "Atomicity review requires at least two commits."
        )
    return {
        "valid": True,
        "commit_count": len(proposal.commits),
        "staged_file_count": len(staged),
        "changed_hunk_count": changed_hunk_count(diff),
        "requires_atomicity_review": review,
    }


def _commit_message(group: CommitGroup) -> str:
    subject = group.summary.removesuffix(".").rstrip()
    details = tuple(
        detail if detail.startswith("- ") else f"- {detail}" for detail in group.details
    )
    return subject if not details else f"{subject}\n\n" + "\n".join(details)


def _require_atomicity_decision(
    review_required: bool,
    decision_file: Path | None,
) -> AtomicityDecision | None:
    if not review_required:
        return None
    if decision_file is None:
        raise AutommitError(
            "atomicity_review_required",
            "This broad single-commit proposal requires an atomicity decision file.",
        )
    raw_decision = read_json_file(decision_file, "atomicity decision")
    decision = normalize_atomicity_decision(raw_decision)
    if decision.decision == "split":
        concerns = "; ".join(decision.concerns)
        raise AutommitError(
            "atomicity_split_required",
            f"Atomicity critic requires a split: {concerns}. Rationale: {decision.rationale}",
        )
    return decision


def _record_recovery_point(git_dir: Path, ref: str, before: str) -> None:
    """Persist a recovery point without masking the original failure."""
    with contextlib.suppress(AutommitError, OSError):
        write_recovery_point(
            git_dir,
            RecoveryPoint(ref=ref, before=before, pid=os.getpid()),
        )


def _run_smoke(worktree: Path, command: str, ref: str, before: str) -> None:
    """Run one opt-in validation command inside the temporary worktree."""
    try:
        completed = subprocess.run(
            shlex.split(command),
            cwd=worktree,
            check=False,
            capture_output=True,
            text=True,
            timeout=SMOKE_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise AutommitError(
            "smoke_failed",
            f"Smoke validation could not run: {error}. "
            f"Recovery point: {ref} at {before}.",
            4,
        ) from error
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "no output"
        raise AutommitError(
            "smoke_failed",
            f"Smoke validation failed ({completed.returncode}): {detail}. "
            f"Recovery point: {ref} at {before}.",
            4,
        )


def apply(
    cwd: Path,
    snapshot: str,
    plan_file: Path,
    decision_file: Path | None,
    *,
    smoke: str | None = None,
) -> dict[str, object]:
    """Prepare commits off-branch, verify final tree, and publish by CAS."""
    git_dir = _git_dir(cwd)
    with operation_lock(git_dir):
        if blocking := _blocking_state(git_dir):
            raise RefusalError("in_progress_state", blocking)
        _consume_or_recover(cwd, git_dir)
        expected, proposal, _, staged_diff, review = _load_validated_plan(
            cwd, snapshot, plan_file
        )
        _require_atomicity_decision(review, decision_file)
        zero_context_diff = _staged_diff(cwd, zero_context=True)
        created: list[dict[str, str]] = []

        with (
            tempfile.TemporaryDirectory(prefix="autommit-worktree-") as worktree_name,
            tempfile.TemporaryDirectory(prefix="autommit-patch-") as patch_name,
        ):
            worktree = Path(worktree_name)
            message = Path(patch_name) / "message.txt"
            run_git(cwd, "worktree", "add", "--detach", str(worktree), expected.before)
            try:
                for commit_index in compute_apply_order(proposal.commits):
                    group = proposal.commits[commit_index]
                    work = CommitWork(
                        repo=cwd,
                        worktree=worktree,
                        patch_dir=Path(patch_name),
                        index_tree=expected.index_tree,
                        ref=expected.ref,
                        before=expected.before,
                        staged_diff=staged_diff,
                        zero_diff=zero_context_diff,
                    )
                    _ = apply_with_fallback(work, group)
                    if smoke is not None:
                        _run_smoke(worktree, smoke, expected.ref, expected.before)
                    message.write_text(_commit_message(group), encoding="utf-8")
                    run_git(
                        worktree,
                        "-c",
                        "core.hooksPath=",
                        "commit",
                        "--no-verify",
                        "-F",
                        str(message),
                    )
                    sha = run_git(worktree, "rev-parse", "HEAD").strip()
                    created.append({"sha": sha, "summary": group.summary})

                final_head = run_git(worktree, "rev-parse", "HEAD").strip()
            except AutommitError:
                _record_recovery_point(git_dir, expected.ref, expected.before)
                raise
            finally:
                try_git(cwd, "worktree", "remove", "--force", str(worktree))
                try_git(cwd, "worktree", "prune")
            current_evidence = _current_evidence(cwd)
            if (
                current_evidence.ref != expected.ref
                or current_evidence.before != expected.before
                or current_evidence.index_tree != expected.index_tree
            ):
                _record_recovery_point(git_dir, expected.ref, expected.before)
                raise RefusalError(
                    "snapshot_changed",
                    "Target repository changed while atomic commits were being prepared.",
                )

            created_tree = _tree_for_commit(cwd, final_head)
            if created_tree != expected.index_tree:
                _record_recovery_point(git_dir, expected.ref, expected.before)
                raise RefusalError(
                    "tree_mismatch",
                    "Prepared commit tree does not match staged index tree.",
                )

            receipt = Receipt(
                version=1,
                state="prepared",
                ref=expected.ref,
                before=expected.before,
                after=final_head,
                index_tree=expected.index_tree,
            )
            write_receipt(git_dir, receipt)
            _cas_ref(cwd, expected.ref, final_head, expected.before)
            remove_receipt(git_dir)
            clear_recovery_point(git_dir)

            return {
                "status": "committed",
                "ref": expected.ref,
                "before": expected.before,
                "after": final_head,
                "commit_count": len(created),
                "commits": created,
            }
