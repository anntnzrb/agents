# ruff: noqa: CPY001, E501, EM101, FBT001, PLR2004, TRY301
"""Transactional autommit workflow independent of any model provider."""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from autommit.errors import AutommitError, RefusalError
from autommit.git import run_git, try_git
from autommit.proposal import (
    AllSelector,
    AtomicityDecision,
    CommitGroup,
    CommitProposal,
    IndicesSelector,
    LinesSelector,
    build_commit_patch,
    changed_hunk_count,
    normalize_atomicity_decision,
    normalize_proposal,
    parse_file_diffs,
    read_json_file,
    requires_atomicity_review,
    validate_proposal_coverage,
)
from autommit.transaction import (
    Receipt,
    operation_lock,
    read_receipt,
    remove_receipt,
    write_receipt,
)

MAX_POLICY_FILE_BYTES = 32 * 1024
MAX_LOG_ENTRIES = 8


@dataclass(frozen=True, slots=True)
class Evidence:
    """Git state bound into a prepared snapshot token."""

    ref: str
    before: str
    index_tree: str


def _common_dir(cwd: Path) -> Path:
    value = run_git(cwd, "rev-parse", "--git-common-dir").strip()
    return (
        (cwd / value).resolve()
        if not Path(value).is_absolute()
        else Path(value).resolve()
    )


def _current_evidence(cwd: Path) -> Evidence:
    ref_result = try_git(cwd, "symbolic-ref", "--quiet", "HEAD")
    ref = ref_result.stdout.strip() if ref_result.returncode == 0 else ""
    before = run_git(cwd, "rev-parse", "HEAD").strip()
    index_tree = run_git(cwd, "write-tree").strip()
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


def _staged_files(cwd: Path) -> tuple[str, ...]:
    output = run_git(cwd, "diff", "--cached", "--name-only", "-z", "--")
    return tuple(item for item in output.split("\0") if item)


def _staged_diff(cwd: Path, *, zero_context: bool = False) -> str:
    arguments = [
        "-c",
        "core.quotePath=true",
        "diff",
        "--cached",
        "--binary",
        "--no-ext-diff",
    ]
    if zero_context:
        arguments.append("--unified=0")
    arguments.append("--")
    return run_git(cwd, *arguments)


def _repository_policy(cwd: Path) -> str:
    parts: list[str] = []
    root = Path(run_git(cwd, "rev-parse", "--show-toplevel").strip()).resolve()
    log_result = try_git(cwd, "log", f"-{MAX_LOG_ENTRIES}", "--format=%s")
    if log_result.returncode == 0:
        subjects = tuple(
            line.strip() for line in log_result.stdout.splitlines() if line.strip()
        )
        if subjects:
            parts.append(
                "Recent commit subjects (style evidence only):\n"
                + "\n".join(f"- {subject}" for subject in subjects)
            )
    candidates = [root / "AGENTS.md"]
    resolved_cwd = cwd.resolve()
    if resolved_cwd != root:
        candidates.append(resolved_cwd / "AGENTS.md")
    for candidate in candidates:
        try:
            data = candidate.read_bytes()
        except FileNotFoundError:
            continue
        except OSError as error:
            raise AutommitError(
                "policy_io",
                f"Unable to read repository policy {candidate}: {error}",
                4,
            ) from error
        bounded = data[:MAX_POLICY_FILE_BYTES].decode("utf-8", errors="replace")
        if not bounded.strip():
            continue
        if len(data) > MAX_POLICY_FILE_BYTES:
            bounded += "\n[policy file truncated]"
        parts.append(f"Repository policy file {candidate}:\n{bounded}")
    return "\n\n".join(parts)


def _cas_ref(cwd: Path, ref: str, after: str, before: str) -> None:
    result = try_git(cwd, "update-ref", ref, after, before)
    if result.returncode != 0:
        detail = result.stderr.strip() or "Autommit branch changed during transaction."
        raise RefusalError("branch_changed", detail)


def _assert_receipt_evidence(
    cwd: Path,
    receipt: Receipt,
    expected_head: str,
) -> None:
    actual = _current_evidence(cwd)
    if actual.ref != receipt.ref:
        raise RefusalError(
            "branch_changed", "Autommit branch changed during receipt recovery."
        )
    if actual.before != expected_head:
        raise RefusalError(
            "head_changed", "Autommit HEAD changed during receipt recovery."
        )
    if actual.index_tree != receipt.index_tree:
        raise RefusalError(
            "index_changed", "Autommit index changed during receipt recovery."
        )


def _recover_receipt(
    cwd: Path, common_dir: Path, receipt: Receipt
) -> dict[str, object]:
    actual = _current_evidence(cwd)
    if actual.ref != receipt.ref or actual.index_tree != receipt.index_tree:
        raise RefusalError(
            "receipt_mismatch",
            "Prepared autommit receipt does not match the current branch and index.",
        )
    if actual.before == receipt.before:
        _cas_ref(cwd, receipt.ref, receipt.after, receipt.before)
        _assert_receipt_evidence(cwd, receipt, receipt.after)
    elif actual.before != receipt.after:
        raise RefusalError(
            "receipt_mismatch",
            "Prepared autommit receipt does not match the current HEAD.",
        )
    remove_receipt(common_dir)
    return {
        "status": "recovered",
        "message": "Recovered prepared autommit transaction.",
        "after": receipt.after,
    }


def _consume_or_recover(cwd: Path, common_dir: Path) -> dict[str, object] | None:
    receipt = read_receipt(common_dir)
    if receipt is None:
        return None
    if receipt.state == "committed":
        remove_receipt(common_dir)
        return None
    return _recover_receipt(cwd, common_dir, receipt)


def prepare(cwd: Path, context: tuple[str, ...]) -> dict[str, object]:
    """Recover if needed, stage when appropriate, and expose exact planning evidence."""
    common_dir = _common_dir(cwd)
    with operation_lock(common_dir):
        recovered = _consume_or_recover(cwd, common_dir)
        if recovered is not None:
            return recovered
        staged = _staged_files(cwd)
        if not staged:
            run_git(cwd, "add", "--all")
            staged = _staged_files(cwd)
        if not staged:
            raise AutommitError("no_changes", "No local changes to commit.")
        evidence = _current_evidence(cwd)
        diff = _staged_diff(cwd)
        return {
            "status": "prepared",
            "snapshot": _snapshot_token(evidence),
            "ref": evidence.ref,
            "before": evidence.before,
            "index_tree": evidence.index_tree,
            "staged_files": list(staged),
            "changed_hunk_count": changed_hunk_count(diff),
            "context": "\n\n".join(value for value in context if value),
            "repository_context": _repository_policy(cwd),
            "diff": diff,
        }


def _load_validated_plan(
    cwd: Path,
    snapshot: str,
    plan_file: Path,
) -> tuple[Evidence, CommitProposal, tuple[str, ...], str, bool]:
    evidence = _assert_snapshot(cwd, snapshot)
    proposal = normalize_proposal(read_json_file(plan_file, "plan"))
    staged = _staged_files(cwd)
    diff = _staged_diff(cwd)
    errors = validate_proposal_coverage(proposal, staged, parse_file_diffs(diff))
    if errors:
        raise AutommitError("invalid_plan", "Invalid split plan: " + "; ".join(errors))
    review = requires_atomicity_review(proposal, len(staged), diff)
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
    if require_split and len(proposal.commits) < 2:
        raise AutommitError(
            "split_required",
            "Atomicity review requires at least two commits.",
        )
    return {
        "valid": True,
        "commit_count": len(proposal.commits),
        "staged_file_count": len(staged),
        "changed_hunk_count": changed_hunk_count(diff),
        "requires_atomicity_review": review,
    }


def _position_for_change(
    group: CommitGroup,
    staged_diff: str,
    zero_context_diff: str,
) -> int:
    regular = {file.filename: file for file in parse_file_diffs(staged_diff)}
    zero = {file.filename: file for file in parse_file_diffs(zero_context_diff)}
    positions: list[int] = [0]
    for change in group.changes:
        files = zero if isinstance(change.hunks, LinesSelector) else regular
        file = files.get(change.path)
        if file is None or isinstance(change.hunks, AllSelector):
            continue
        if isinstance(change.hunks, IndicesSelector):
            selected = tuple(
                hunk for hunk in file.hunks if hunk.index in change.hunks.indices
            )
        else:
            selected = tuple(
                hunk
                for hunk in file.hunks
                if hunk.new_start <= change.hunks.end
                and change.hunks.start <= hunk.new_start + max(1, hunk.new_lines) - 1
            )
        positions.extend(hunk.new_start for hunk in selected)
    return max(positions)


def _apply_order(
    proposal: CommitProposal,
    staged_diff: str,
    zero_context_diff: str,
) -> tuple[CommitGroup, ...]:
    entries = (
        (group, index, _position_for_change(group, staged_diff, zero_context_diff))
        for index, group in enumerate(proposal.commits)
    )
    return tuple(
        group
        for group, _, _ in sorted(entries, key=lambda entry: (-entry[2], entry[1]))
    )


def _commit_message(group: CommitGroup) -> str:
    details = tuple(
        detail if detail.startswith("- ") else f"- {detail}" for detail in group.details
    )
    return group.summary if not details else f"{group.summary}\n\n" + "\n".join(details)


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
    decision = normalize_atomicity_decision(
        read_json_file(decision_file, "atomicity decision")
    )
    if decision.decision == "split":
        concerns = "; ".join(decision.concerns)
        raise AutommitError(
            "atomicity_split_required",
            f"Atomicity critic requires a split: {concerns}. Rationale: {decision.rationale}",
        )
    return decision


def apply(
    cwd: Path,
    snapshot: str,
    plan_file: Path,
    decision_file: Path | None,
) -> dict[str, object]:
    """Prepare commits off-branch, verify the final tree, then publish by CAS."""
    common_dir = _common_dir(cwd)
    with operation_lock(common_dir):
        recovered = _consume_or_recover(cwd, common_dir)
        if recovered is not None:
            return recovered
        expected, proposal, _, staged_diff, review = _load_validated_plan(
            cwd,
            snapshot,
            plan_file,
        )
        _require_atomicity_decision(review, decision_file)
        zero_context_diff = _staged_diff(cwd, zero_context=True)
        created: list[dict[str, str]] = []
        with tempfile.TemporaryDirectory(prefix="autommit-worktree-") as worktree_name:
            worktree = Path(worktree_name)
            with tempfile.TemporaryDirectory(prefix="autommit-patch-") as patch_name:
                patch = Path(patch_name) / "commit.patch"
                message = Path(patch_name) / "message.txt"
                added = False
                primary_error: BaseException | None = None
                try:
                    run_git(
                        cwd,
                        "worktree",
                        "add",
                        "--detach",
                        str(worktree),
                        expected.before,
                    )
                    added = True
                    for group in _apply_order(proposal, staged_diff, zero_context_diff):
                        patch.write_text(
                            build_commit_patch(
                                group.changes, staged_diff, zero_context_diff
                            ),
                            encoding="utf-8",
                        )
                        run_git(
                            worktree, "apply", "--index", "--unidiff-zero", str(patch)
                        )
                        message.write_text(
                            _commit_message(group) + "\n", encoding="utf-8"
                        )
                        run_git(worktree, "commit", "-F", str(message))
                        created.append(
                            {
                                "sha": run_git(worktree, "rev-parse", "HEAD").strip(),
                                "summary": group.summary,
                            }
                        )
                    final_head = run_git(worktree, "rev-parse", "HEAD").strip()
                    prepared_tree = run_git(
                        worktree, "rev-parse", f"{final_head}^{{tree}}"
                    ).strip()
                    if prepared_tree != expected.index_tree:
                        raise RefusalError(
                            "tree_mismatch",
                            "Prepared commit tree does not match the staged index.",
                        )
                    if _staged_diff(cwd) != staged_diff:
                        raise RefusalError(
                            "snapshot_changed",
                            "Staged snapshot changed during atomic commit preparation.",
                        )
                    _assert_snapshot(cwd, snapshot)
                    receipt = Receipt(
                        1,
                        "prepared",
                        expected.ref,
                        expected.before,
                        final_head,
                        expected.index_tree,
                    )
                    write_receipt(common_dir, receipt)
                    _assert_snapshot(cwd, snapshot)
                    _cas_ref(cwd, expected.ref, final_head, expected.before)
                    _assert_receipt_evidence(cwd, receipt, final_head)
                    remove_receipt(common_dir)
                    return {
                        "status": "committed",
                        "message": (
                            f"Created {len(created)} commit"
                            f"{'s' if len(created) != 1 else ''} atomically."
                        ),
                        "before": expected.before,
                        "after": final_head,
                        "commits": created,
                    }
                except BaseException as error:
                    primary_error = error
                    raise
                finally:
                    if added:
                        cleanup = try_git(
                            cwd, "worktree", "remove", "--force", str(worktree)
                        )
                        if cleanup.returncode != 0 and primary_error is None:
                            detail = cleanup.stderr.strip() or "unknown cleanup failure"
                            raise AutommitError(
                                "cleanup_failed",
                                f"Autommit cleanup failed: {detail}",
                                4,
                            )
