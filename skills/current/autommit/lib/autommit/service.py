"""Transactional autommit workflow independent of any model provider."""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from expression import Error, Nothing, Ok, Option, Result, Some

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


def _common_dir(cwd: Path) -> Result[Path, AutommitError]:
    match run_git(cwd, "rev-parse", "--git-common-dir"):
        case Result(tag="ok", ok=value_str):
            value = value_str.strip()
            return Ok(
                (cwd / value).resolve()
                if not Path(value).is_absolute()
                else Path(value).resolve()
            )
        case Result(error=err):
            return Error(err)
        case _:
            return Error(
                AutommitError("git_error", "Failed to resolve git common dir.", 4)
            )


def _current_evidence(cwd: Path) -> Result[Evidence, AutommitError]:
    match try_git(cwd, "symbolic-ref", "--quiet", "HEAD"):
        case Result(tag="ok", ok=ref_result):
            ref = ref_result.stdout.strip() if ref_result.returncode == 0 else ""
        case Result(error=err):
            return Error(err)
        case _:
            ref = ""
    match run_git(cwd, "rev-parse", "HEAD"):
        case Result(tag="ok", ok=before_str):
            before = before_str.strip()
        case Result(error=err):
            return Error(err)
        case _:
            return Error(AutommitError("git_error", "Failed to rev-parse HEAD.", 4))
    match run_git(cwd, "write-tree"):
        case Result(tag="ok", ok=index_tree_str):
            index_tree = index_tree_str.strip()
        case Result(error=err):
            return Error(err)
        case _:
            return Error(AutommitError("git_error", "Failed to write-tree.", 4))
    if not ref or not before or not index_tree:
        return Error(
            AutommitError(
                "unsupported_checkout",
                "Autommit requires a branch checkout with an existing HEAD.",
            )
        )
    return Ok(Evidence(ref, before, index_tree))


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


def _assert_snapshot(cwd: Path, snapshot: str) -> Result[Evidence, AutommitError]:
    match _current_evidence(cwd):
        case Result(tag="ok", ok=evidence):
            if _snapshot_token(evidence) != snapshot:
                return Error(
                    RefusalError(
                        "snapshot_changed",
                        "Autommit branch, HEAD, or index changed after preparation.",
                    )
                )
            return Ok(evidence)
        case Result(error=err):
            return Error(err)
        case _:
            return Error(
                AutommitError("git_error", "Failed to get current evidence.", 4)
            )


def _staged_files(cwd: Path) -> Result[tuple[str, ...], AutommitError]:
    match run_git(cwd, "diff", "--cached", "--name-only", "-z", "--"):
        case Result(tag="ok", ok=output):
            files = tuple(item for item in output.split("\0") if item)
            return Ok(files)
        case Result(error=err):
            return Error(err)
        case _:
            return Error(AutommitError("git_error", "Failed to get staged files.", 4))


def _staged_diff(
    cwd: Path, *, zero_context: bool = False
) -> Result[str, AutommitError]:
    arguments = [
        "-c",
        "diff.mnemonicprefix=false",
        "-c",
        "diff.noprefix=false",
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


def _repository_policy(cwd: Path) -> Result[str, AutommitError]:
    parts: list[str] = []
    match run_git(cwd, "rev-parse", "--show-toplevel"):
        case Result(tag="ok", ok=root_str):
            root = Path(root_str.strip()).resolve()
        case Result(error=err):
            return Error(err)
        case _:
            return Error(AutommitError("git_error", "Failed to find git toplevel.", 4))
    match try_git(cwd, "log", f"-{MAX_LOG_ENTRIES}", "--format=%s"):
        case Result(tag="ok", ok=log_result):
            if log_result.returncode == 0:
                subjects = tuple(
                    line.strip()
                    for line in log_result.stdout.splitlines()
                    if line.strip()
                )
                if subjects:
                    parts.append(
                        "Recent commit subjects (style evidence only):\n"
                        + "\n".join(f"- {subject}" for subject in subjects)
                    )
        case Result(error=err):
            return Error(err)
        case _:
            pass
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
            return Error(
                AutommitError(
                    "policy_io",
                    f"Unable to read repository policy {candidate}: {error}",
                    4,
                )
            )
        bounded = data[:MAX_POLICY_FILE_BYTES].decode("utf-8", errors="replace")
        if not bounded.strip():
            continue
        if len(data) > MAX_POLICY_FILE_BYTES:
            bounded += "\n[policy file truncated]"
        parts.append(f"Repository policy file {candidate}:\n{bounded}")
    return Ok("\n\n".join(parts))


def _cas_ref(
    cwd: Path, ref: str, after: str, before: str
) -> Result[None, AutommitError]:
    match try_git(cwd, "update-ref", ref, after, before):
        case Result(tag="ok", ok=result):
            if result.returncode != 0:
                detail = (
                    result.stderr.strip()
                    or "Autommit branch changed during transaction."
                )
                return Error(RefusalError("branch_changed", detail))
            return Ok(None)
        case Result(error=err):
            return Error(err)
        case _:
            return Error(AutommitError("git_error", "Failed to update ref.", 4))


def _assert_receipt_evidence(
    cwd: Path,
    receipt: Receipt,
    expected_head: str,
) -> Result[None, AutommitError]:
    match _current_evidence(cwd):
        case Result(tag="ok", ok=actual):
            if actual.ref != receipt.ref:
                return Error(
                    RefusalError(
                        "branch_changed",
                        "Autommit branch changed during receipt recovery.",
                    )
                )
            if actual.before != expected_head:
                return Error(
                    RefusalError(
                        "head_changed",
                        "Autommit HEAD changed during receipt recovery.",
                    )
                )
            if actual.index_tree != receipt.index_tree:
                return Error(
                    RefusalError(
                        "index_changed",
                        "Autommit index changed during receipt recovery.",
                    )
                )
            return Ok(None)
        case Result(error=err):
            return Error(err)
        case _:
            return Error(
                AutommitError("git_error", "Failed to get current evidence.", 4)
            )


def _recover_receipt(
    cwd: Path, common_dir: Path, receipt: Receipt
) -> Result[dict[str, object], AutommitError]:
    match _current_evidence(cwd):
        case Result(tag="ok", ok=actual):
            if actual.ref != receipt.ref or actual.index_tree != receipt.index_tree:
                return Error(
                    RefusalError(
                        "receipt_mismatch",
                        "Prepared autommit receipt does not match the current branch and index.",
                    )
                )
            if actual.before == receipt.before:
                match _cas_ref(cwd, receipt.ref, receipt.after, receipt.before):
                    case Result(tag="ok"):
                        match _assert_receipt_evidence(cwd, receipt, receipt.after):
                            case Result(tag="ok"):
                                pass
                            case Result(error=err):
                                return Error(err)
                            case _:
                                return Error(
                                    AutommitError(
                                        "git_error",
                                        "Failed to assert receipt evidence.",
                                        4,
                                    )
                                )
                    case Result(error=err):
                        return Error(err)
                    case _:
                        return Error(
                            AutommitError("git_error", "Failed to CAS ref.", 4)
                        )
            elif actual.before != receipt.after:
                return Error(
                    RefusalError(
                        "receipt_mismatch",
                        "Prepared autommit receipt does not match the current HEAD.",
                    )
                )
            match remove_receipt(common_dir):
                case Result(tag="ok"):
                    return Ok(
                        {
                            "status": "recovered",
                            "message": "Recovered prepared autommit transaction.",
                            "after": receipt.after,
                        }
                    )
                case Result(error=err):
                    return Error(err)
                case _:
                    return Error(
                        AutommitError("receipt_io", "Failed to remove receipt.", 4)
                    )
        case Result(error=err):
            return Error(err)
        case _:
            return Error(
                AutommitError("git_error", "Failed to get current evidence.", 4)
            )


def _consume_or_recover(
    cwd: Path, common_dir: Path
) -> Result[Option[dict[str, object]], AutommitError]:
    match read_receipt(common_dir):
        case Result(tag="ok", ok=receipt_opt):
            match receipt_opt:
                case Option(tag="none"):
                    return Ok(Nothing)
                case Option(tag="some", some=receipt):
                    if receipt.state == "committed":
                        match remove_receipt(common_dir):
                            case Result(tag="ok"):
                                return Ok(Nothing)
                            case Result(error=err):
                                return Error(err)
                            case _:
                                return Ok(Nothing)
                    match _recover_receipt(cwd, common_dir, receipt):
                        case Result(tag="ok", ok=recovered):
                            return Ok(Some(recovered))
                        case Result(error=err):
                            return Error(err)
                        case _:
                            return Ok(Nothing)
                case _:
                    return Ok(Nothing)
        case Result(error=err):
            return Error(err)
        case _:
            return Ok(Nothing)


def prepare(
    cwd: Path, context: tuple[str, ...]
) -> Result[dict[str, object], AutommitError]:
    """Recover if needed, stage when appropriate, and expose exact planning evidence."""
    match _common_dir(cwd):
        case Result(tag="ok", ok=common_dir):
            try:
                with operation_lock(common_dir):
                    match _consume_or_recover(cwd, common_dir):
                        case Result(tag="ok", ok=recovered_opt):
                            match recovered_opt:
                                case Option(tag="some", some=recovered):
                                    return Ok(recovered)
                                case _:
                                    pass
                        case Result(error=err):
                            return Error(err)
                        case _:
                            pass
                    match _staged_files(cwd):
                        case Result(tag="ok", ok=staged):
                            if not staged:
                                match run_git(cwd, "add", "--all"):
                                    case Result(tag="ok"):
                                        match _staged_files(cwd):
                                            case Result(tag="ok", ok=staged_again):
                                                staged = staged_again
                                            case Result(error=err):
                                                return Error(err)
                                            case _:
                                                return Error(
                                                    AutommitError(
                                                        "git_error",
                                                        "Failed to list staged files.",
                                                        4,
                                                    )
                                                )
                                    case Result(error=err):
                                        return Error(err)
                                    case _:
                                        return Error(
                                            AutommitError(
                                                "git_error",
                                                "Failed to stage all files.",
                                                4,
                                            )
                                        )
                            if not staged:
                                return Error(
                                    AutommitError(
                                        "no_changes",
                                        "No local changes to commit.",
                                    )
                                )
                            match _current_evidence(cwd):
                                case Result(tag="ok", ok=evidence):
                                    match _staged_diff(cwd):
                                        case Result(tag="ok", ok=diff):
                                            match _repository_policy(cwd):
                                                case Result(tag="ok", ok=repo_context):
                                                    return Ok(
                                                        {
                                                            "status": "prepared",
                                                            "snapshot": _snapshot_token(
                                                                evidence
                                                            ),
                                                            "ref": evidence.ref,
                                                            "before": evidence.before,
                                                            "index_tree": evidence.index_tree,
                                                            "staged_files": list(
                                                                staged
                                                            ),
                                                            "changed_hunk_count": changed_hunk_count(
                                                                diff
                                                            ),
                                                            "context": "\n\n".join(
                                                                value
                                                                for value in context
                                                                if value
                                                            ),
                                                            "repository_context": repo_context,
                                                            "diff": diff,
                                                        }
                                                    )
                                                case Result(error=err):
                                                    return Error(err)
                                                case _:
                                                    return Error(
                                                        AutommitError(
                                                            "git_error",
                                                            "Failed to read policy.",
                                                            4,
                                                        )
                                                    )
                                        case Result(error=err):
                                            return Error(err)
                                        case _:
                                            return Error(
                                                AutommitError(
                                                    "git_error",
                                                    "Failed to diff index.",
                                                    4,
                                                )
                                            )
                                case Result(error=err):
                                    return Error(err)
                                case _:
                                    return Error(
                                        AutommitError(
                                            "git_error",
                                            "Failed to inspect checkout.",
                                            4,
                                        )
                                    )
                        case Result(error=err):
                            return Error(err)
                        case _:
                            return Error(
                                AutommitError(
                                    "git_error", "Failed to get staged files.", 4
                                )
                            )
            except AutommitError as error:
                return Error(error)
        case Result(error=err):
            return Error(err)
        case _:
            return Error(
                AutommitError("git_error", "Failed to resolve git common dir.", 4)
            )


def _load_validated_plan(
    cwd: Path,
    snapshot: str,
    plan_file: Path,
) -> Result[tuple[Evidence, CommitProposal, tuple[str, ...], str, bool], AutommitError]:
    match _assert_snapshot(cwd, snapshot):
        case Result(tag="ok", ok=evidence):
            match read_json_file(plan_file, "plan"):
                case Result(tag="ok", ok=raw_plan):
                    match normalize_proposal(raw_plan):
                        case Result(tag="ok", ok=proposal):
                            match _staged_files(cwd):
                                case Result(tag="ok", ok=staged):
                                    match _staged_diff(cwd):
                                        case Result(tag="ok", ok=diff):
                                            errors = validate_proposal_coverage(
                                                proposal,
                                                staged,
                                                parse_file_diffs(diff),
                                            )
                                            if errors:
                                                return Error(
                                                    AutommitError(
                                                        "invalid_plan",
                                                        "Invalid split plan: "
                                                        + "; ".join(errors),
                                                    )
                                                )
                                            review = requires_atomicity_review(
                                                proposal, len(staged), diff
                                            )
                                            return Ok(
                                                (
                                                    evidence,
                                                    proposal,
                                                    staged,
                                                    diff,
                                                    review,
                                                )
                                            )
                                        case Result(error=err):
                                            return Error(err)
                                        case _:
                                            return Error(
                                                AutommitError(
                                                    "git_error",
                                                    "Failed to diff index.",
                                                    4,
                                                )
                                            )
                                case Result(error=err):
                                    return Error(err)
                                case _:
                                    return Error(
                                        AutommitError(
                                            "git_error",
                                            "Failed to get staged files.",
                                            4,
                                        )
                                    )
                        case Result(error=err):
                            return Error(err)
                        case _:
                            return Error(
                                AutommitError(
                                    "invalid_plan", "Failed to parse proposal.", 2
                                )
                            )
                case Result(error=err):
                    return Error(err)
                case _:
                    return Error(
                        AutommitError("invalid_json", "Failed to read plan JSON.", 2)
                    )
        case Result(error=err):
            return Error(err)
        case _:
            return Error(AutommitError("git_error", "Failed to verify snapshot.", 3))


def validate_plan(
    cwd: Path,
    snapshot: str,
    plan_file: Path,
    *,
    require_split: bool = False,
) -> Result[dict[str, object], AutommitError]:
    """Validate a model plan against the prepared snapshot."""
    match _load_validated_plan(cwd, snapshot, plan_file):
        case Result(tag="ok", ok=(_, proposal, staged, diff, review)):
            if require_split and len(proposal.commits) < 2:
                return Error(
                    AutommitError(
                        "split_required",
                        "Atomicity review requires at least two commits.",
                    )
                )
            return Ok(
                {
                    "valid": True,
                    "commit_count": len(proposal.commits),
                    "staged_file_count": len(staged),
                    "changed_hunk_count": changed_hunk_count(diff),
                    "requires_atomicity_review": review,
                }
            )
        case Result(error=err):
            return Error(err)
        case _:
            return Error(AutommitError("invalid_plan", "Failed to validate plan.", 2))


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
        (
            group,
            index,
            _position_for_change(group, staged_diff, zero_context_diff),
        )
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
) -> Result[Option[AtomicityDecision], AutommitError]:
    if not review_required:
        return Ok(Nothing)
    if decision_file is None:
        return Error(
            AutommitError(
                "atomicity_review_required",
                "This broad single-commit proposal requires an atomicity decision file.",
            )
        )
    match read_json_file(decision_file, "atomicity decision"):
        case Result(tag="ok", ok=raw_decision):
            match normalize_atomicity_decision(raw_decision):
                case Result(tag="ok", ok=decision):
                    if decision.decision == "split":
                        concerns = "; ".join(decision.concerns)
                        return Error(
                            AutommitError(
                                "atomicity_split_required",
                                f"Atomicity critic requires a split: {concerns}. Rationale: {decision.rationale}",
                            )
                        )
                    return Ok(Some(decision))
                case Result(error=err):
                    return Error(err)
                case _:
                    return Error(
                        AutommitError(
                            "invalid_atomicity_decision",
                            "Failed to normalize decision.",
                            2,
                        )
                    )
        case Result(error=err):
            return Error(err)
        case _:
            return Error(
                AutommitError("invalid_json", "Failed to read decision file.", 2)
            )


def apply(
    cwd: Path,
    snapshot: str,
    plan_file: Path,
    decision_file: Path | None,
) -> Result[dict[str, object], AutommitError]:
    """Prepare commits off-branch, verify the final tree, then publish by CAS."""
    match _common_dir(cwd):
        case Result(tag="ok", ok=common_dir):
            try:
                with operation_lock(common_dir):
                    match _consume_or_recover(cwd, common_dir):
                        case Result(tag="ok", ok=recovered_opt):
                            match recovered_opt:
                                case Option(tag="some", some=recovered):
                                    return Ok(recovered)
                                case _:
                                    pass
                        case Result(error=err):
                            return Error(err)
                        case _:
                            pass
                    match _load_validated_plan(cwd, snapshot, plan_file):
                        case Result(
                            tag="ok",
                            ok=(expected, proposal, _, staged_diff, review),
                        ):
                            match _require_atomicity_decision(review, decision_file):
                                case Result(tag="ok"):
                                    pass
                                case Result(error=err):
                                    return Error(err)
                                case _:
                                    return Error(
                                        AutommitError(
                                            "atomicity_review_required",
                                            "Invalid atomicity review.",
                                            2,
                                        )
                                    )
                            match _staged_diff(cwd, zero_context=True):
                                case Result(tag="ok", ok=zero_context_diff):
                                    pass
                                case Result(error=err):
                                    return Error(err)
                                case _:
                                    return Error(
                                        AutommitError(
                                            "git_error",
                                            "Failed to diff zero context.",
                                            4,
                                        )
                                    )
                            created: list[dict[str, str]] = []
                            with tempfile.TemporaryDirectory(
                                prefix="autommit-worktree-"
                            ) as worktree_name:
                                worktree = Path(worktree_name)
                                with tempfile.TemporaryDirectory(
                                    prefix="autommit-patch-"
                                ) as patch_name:
                                    patch = Path(patch_name) / "commit.patch"
                                    message = Path(patch_name) / "message.txt"
                                    added = False
                                    try:
                                        match run_git(
                                            cwd,
                                            "worktree",
                                            "add",
                                            "--detach",
                                            str(worktree),
                                            expected.before,
                                        ):
                                            case Result(tag="ok"):
                                                added = True
                                            case Result(error=err):
                                                return Error(err)
                                            case _:
                                                return Error(
                                                    AutommitError(
                                                        "git_error",
                                                        "Failed to add worktree.",
                                                        4,
                                                    )
                                                )
                                        for group in _apply_order(
                                            proposal,
                                            staged_diff,
                                            zero_context_diff,
                                        ):
                                            match build_commit_patch(
                                                group.changes,
                                                staged_diff,
                                                zero_context_diff,
                                            ):
                                                case Result(tag="ok", ok=patch_content):
                                                    patch.write_text(
                                                        patch_content,
                                                        encoding="utf-8",
                                                    )
                                                case Result(error=err):
                                                    return Error(err)
                                                case _:
                                                    return Error(
                                                        AutommitError(
                                                            "invalid_plan",
                                                            "Failed to build patch.",
                                                            2,
                                                        )
                                                    )
                                            match run_git(
                                                worktree,
                                                "apply",
                                                "--index",
                                                "--unidiff-zero",
                                                str(patch),
                                            ):
                                                case Result(tag="ok"):
                                                    pass
                                                case Result(error=err):
                                                    return Error(err)
                                                case _:
                                                    return Error(
                                                        AutommitError(
                                                            "git_error",
                                                            "Failed to apply patch.",
                                                            4,
                                                        )
                                                    )
                                            message.write_text(
                                                _commit_message(group) + "\n",
                                                encoding="utf-8",
                                            )
                                            match run_git(
                                                worktree,
                                                "commit",
                                                "-F",
                                                str(message),
                                            ):
                                                case Result(tag="ok"):
                                                    pass
                                                case Result(error=err):
                                                    return Error(err)
                                                case _:
                                                    return Error(
                                                        AutommitError(
                                                            "git_error",
                                                            "Failed to commit in worktree.",
                                                            4,
                                                        )
                                                    )
                                            match run_git(
                                                worktree,
                                                "rev-parse",
                                                "HEAD",
                                            ):
                                                case Result(tag="ok", ok=head_sha):
                                                    created.append(
                                                        {
                                                            "sha": head_sha.strip(),
                                                            "summary": group.summary,
                                                        }
                                                    )
                                                case Result(error=err):
                                                    return Error(err)
                                                case _:
                                                    return Error(
                                                        AutommitError(
                                                            "git_error",
                                                            "Failed to rev-parse HEAD.",
                                                            4,
                                                        )
                                                    )
                                        match run_git(worktree, "rev-parse", "HEAD"):
                                            case Result(tag="ok", ok=final_head_str):
                                                final_head = final_head_str.strip()
                                            case Result(error=err):
                                                return Error(err)
                                            case _:
                                                return Error(
                                                    AutommitError(
                                                        "git_error",
                                                        "Failed to rev-parse worktree HEAD.",
                                                        4,
                                                    )
                                                )
                                        match run_git(
                                            worktree,
                                            "rev-parse",
                                            f"{final_head}^{{tree}}",
                                        ):
                                            case Result(tag="ok", ok=prepared_tree_str):
                                                prepared_tree = (
                                                    prepared_tree_str.strip()
                                                )
                                            case Result(error=err):
                                                return Error(err)
                                            case _:
                                                return Error(
                                                    AutommitError(
                                                        "git_error",
                                                        "Failed to rev-parse tree.",
                                                        4,
                                                    )
                                                )
                                        if prepared_tree != expected.index_tree:
                                            return Error(
                                                RefusalError(
                                                    "tree_mismatch",
                                                    "Prepared commit tree does not match the staged index.",
                                                )
                                            )
                                        match _staged_diff(cwd):
                                            case Result(tag="ok", ok=current_diff):
                                                if current_diff != staged_diff:
                                                    return Error(
                                                        RefusalError(
                                                            "snapshot_changed",
                                                            "Staged snapshot changed during atomic commit preparation.",
                                                        )
                                                    )
                                            case Result(error=err):
                                                return Error(err)
                                            case _:
                                                return Error(
                                                    AutommitError(
                                                        "git_error",
                                                        "Failed to diff index.",
                                                        4,
                                                    )
                                                )
                                        match _assert_snapshot(cwd, snapshot):
                                            case Result(tag="ok"):
                                                pass
                                            case Result(error=err):
                                                return Error(err)
                                            case _:
                                                return Error(
                                                    AutommitError(
                                                        "git_error",
                                                        "Failed to verify snapshot.",
                                                        3,
                                                    )
                                                )
                                        receipt = Receipt(
                                            1,
                                            "prepared",
                                            expected.ref,
                                            expected.before,
                                            final_head,
                                            expected.index_tree,
                                        )
                                        match write_receipt(common_dir, receipt):
                                            case Result(tag="ok"):
                                                pass
                                            case Result(error=err):
                                                return Error(err)
                                            case _:
                                                return Error(
                                                    AutommitError(
                                                        "receipt_io",
                                                        "Failed to write receipt.",
                                                        4,
                                                    )
                                                )
                                        match _assert_snapshot(cwd, snapshot):
                                            case Result(tag="ok"):
                                                pass
                                            case Result(error=err):
                                                return Error(err)
                                            case _:
                                                return Error(
                                                    AutommitError(
                                                        "git_error",
                                                        "Failed to verify snapshot.",
                                                        3,
                                                    )
                                                )
                                        match _cas_ref(
                                            cwd,
                                            expected.ref,
                                            final_head,
                                            expected.before,
                                        ):
                                            case Result(tag="ok"):
                                                pass
                                            case Result(error=err):
                                                return Error(err)
                                            case _:
                                                return Error(
                                                    AutommitError(
                                                        "git_error",
                                                        "Failed to CAS ref.",
                                                        4,
                                                    )
                                                )
                                        match _assert_receipt_evidence(
                                            cwd, receipt, final_head
                                        ):
                                            case Result(tag="ok"):
                                                pass
                                            case Result(error=err):
                                                return Error(err)
                                            case _:
                                                return Error(
                                                    AutommitError(
                                                        "git_error",
                                                        "Failed to verify receipt evidence.",
                                                        4,
                                                    )
                                                )
                                        match remove_receipt(common_dir):
                                            case Result(tag="ok"):
                                                return Ok(
                                                    {
                                                        "status": "committed",
                                                        "message": (
                                                            f"Created {len(created)} commit"
                                                            f"{'s' if len(created) != 1 else ''} atomically."
                                                        ),
                                                        "before": expected.before,
                                                        "after": final_head,
                                                        "commits": created,
                                                    }
                                                )
                                            case Result(error=err):
                                                return Error(err)
                                            case _:
                                                return Error(
                                                    AutommitError(
                                                        "receipt_io",
                                                        "Failed to remove receipt.",
                                                        4,
                                                    )
                                                )
                                    finally:
                                        if added:
                                            try_git(
                                                cwd,
                                                "worktree",
                                                "remove",
                                                "--force",
                                                str(worktree),
                                            )
                        case Result(error=err):
                            return Error(err)
                        case _:
                            return Error(
                                AutommitError("invalid_plan", "Failed to load plan.", 2)
                            )
            except AutommitError as error:
                return Error(error)
        case Result(error=err):
            return Error(err)
        case _:
            return Error(
                AutommitError("git_error", "Failed to resolve git common dir.", 4)
            )
