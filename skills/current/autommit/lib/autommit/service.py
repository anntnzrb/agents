"""Transactional autommit workflow independent of any model provider."""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Literal

from expression import Error, Nothing, Ok, Option, Result, Some

from autommit.errors import AutommitError, RefusalError
from autommit.git import run_git, try_git
from autommit.proposal import (
    AtomicityDecision,
    CommitGroup,
    CommitProposal,
    build_commit_patch,
    changed_hunk_count,
    normalize_atomicity_decision,
    normalize_proposal,
    parse_file_diffs,
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
_MIN_SPLIT_COMMITS = 2


@dataclass(frozen=True, slots=True)
class Evidence:
    """Git state bound into a prepared snapshot token."""

    ref: str
    before: str
    index_tree: str


def _git_dir(cwd: Path) -> Result[Path, AutommitError]:
    """Resolve the worktree-local Git directory."""
    match run_git(cwd, "rev-parse", "--absolute-git-dir"):
        case Result(tag="ok", ok=value_str):
            value = value_str.strip()
            return Ok(Path(value).resolve())
        case Result(error=err):
            return Error(err)


def _current_evidence(
    cwd: Path, *, index_file: Path | None = None
) -> Result[Evidence, AutommitError]:
    match try_git(cwd, "symbolic-ref", "--quiet", "HEAD"):
        case Result(tag="ok", ok=symbolic_ref):
            ref = symbolic_ref.stdout.strip() if symbolic_ref.returncode == 0 else ""
        case Result(error=err):
            return Error(err)
    match try_git(cwd, "rev-parse", "HEAD"):
        case Result(tag="ok", ok=head_rev):
            before = head_rev.stdout.strip() if head_rev.returncode == 0 else ""
        case Result(error=err):
            return Error(err)
    env = {"GIT_INDEX_FILE": str(index_file)} if index_file else None
    match run_git(cwd, "write-tree", env=env):
        case Result(tag="ok", ok=tree_out):
            index_tree = tree_out.strip()
        case Result(error=err):
            return Error(err)
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


def _staged_files(
    cwd: Path, *, index_file: Path | None = None
) -> Result[tuple[str, ...], AutommitError]:
    env = {"GIT_INDEX_FILE": str(index_file)} if index_file else None
    match run_git(cwd, "diff", "--cached", "--name-only", "-z", "--", env=env):
        case Result(tag="ok", ok=output):
            files = tuple(item for item in output.split("\0") if item)
            return Ok(files)
        case Result(error=err):
            return Error(err)


def _staged_diff(
    cwd: Path, *, zero_context: bool = False, index_file: Path | None = None
) -> Result[str, AutommitError]:
    arguments = [
        "-c",
        "core.quotepath=false",
        "-c",
        "diff.mnemonicPrefix=false",
        "-c",
        "diff.noprefix=false",
        "diff",
        "--cached",
        "--binary",
        "--no-ext-diff",
        "--src-prefix=a/",
        "--dst-prefix=b/",
    ]
    if zero_context:
        arguments.append("--unified=0")
    arguments.extend(["--", "."])
    env = {"GIT_INDEX_FILE": str(index_file)} if index_file else None
    return run_git(cwd, *arguments, env=env)


def _commit_exists(cwd: Path, sha: str) -> Result[bool, AutommitError]:
    match try_git(cwd, "cat-file", "-e", f"{sha}^{{commit}}"):
        case Result(tag="ok", ok=result):
            return Ok(result.returncode == 0)
        case Result(error=err):
            return Error(err)


def _tree_for_commit(cwd: Path, sha: str) -> Result[str, AutommitError]:
    match run_git(cwd, "rev-parse", f"{sha}^{{tree}}"):
        case Result(tag="ok", ok=tree):
            return Ok(tree.strip())
        case Result(error=err):
            return Error(err)


def _cas_ref(
    cwd: Path, ref: str, target: str, expected_before: str
) -> Result[None, AutommitError]:
    match try_git(cwd, "update-ref", ref, target, expected_before):
        case Result(tag="ok", ok=result):
            if result.returncode == 0:
                return Ok(None)
            return Error(
                RefusalError(
                    "ref_conflict",
                    f"Ref update failed via CAS ({expected_before} -> {target}): "
                    f"{result.stderr.strip()}",
                )
            )
        case Result(error=err):
            return Error(err)


def _repository_policy(cwd: Path) -> Result[str, AutommitError]:
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
    match run_git(
        cwd,
        "log",
        f"-{MAX_LOG_ENTRIES}",
        "--format=### %h %s%n%b",
        "--no-decorate",
    ):
        case Result(tag="ok", ok=log_output):
            if log_output.strip():
                policies.append("## Recent Commits\n" + log_output.strip())
        case Result(error=err):
            return Error(err)
    return Ok("\n\n".join(policies))


def _recover_receipt(
    cwd: Path, git_dir: Path, receipt: Receipt
) -> Result[dict[str, object], AutommitError]:
    match _current_evidence(cwd):
        case Result(tag="ok", ok=evidence):
            if evidence.ref != receipt.ref:
                return Error(
                    RefusalError(
                        "recovery_conflict",
                        f"Receipt is for branch {receipt.ref}, but checkout is on {evidence.ref}.",
                    )
                )
            if (
                evidence.index_tree != receipt.index_tree
                and evidence.before != receipt.after
            ):
                return Error(
                    RefusalError(
                        "recovery_conflict",
                        "Index tree changed after prepared receipt was written.",
                    )
                )
        case Result(error=err):
            return Error(err)

    match _commit_exists(cwd, receipt.after):
        case Result(tag="ok", ok=commit_ok):
            if not commit_ok:
                return Error(
                    AutommitError(
                        "invalid_receipt",
                        ("Receipt target commit object does not exist in repository."),
                    )
                )
            match _tree_for_commit(cwd, receipt.after):
                case Result(tag="ok", ok=target_tree):
                    if target_tree != receipt.index_tree:
                        return Error(
                            AutommitError(
                                "invalid_receipt",
                                (
                                    "Receipt target commit does not match "
                                    "staged index tree."
                                ),
                            )
                        )
                    match run_git(cwd, "rev-parse", receipt.ref):
                        case Result(tag="ok", ok=current_ref_str):
                            current_ref = current_ref_str.strip()
                            if current_ref == receipt.after:
                                match remove_receipt(git_dir):
                                    case Result(tag="ok"):
                                        return Ok(
                                            {
                                                "status": "recovered",
                                                "recovered_state": (
                                                    "already_committed"
                                                ),
                                                "ref": receipt.ref,
                                                "after": receipt.after,
                                            }
                                        )
                                    case Result(error=err):
                                        return Error(err)
                            if current_ref == receipt.before:
                                match _cas_ref(
                                    cwd,
                                    receipt.ref,
                                    receipt.after,
                                    receipt.before,
                                ):
                                    case Result(tag="ok"):
                                        match remove_receipt(git_dir):
                                            case Result(tag="ok"):
                                                return Ok(
                                                    {
                                                        "status": "recovered",
                                                        "recovered_state": (
                                                            "applied_cas"
                                                        ),
                                                        "ref": receipt.ref,
                                                        "after": receipt.after,
                                                    }
                                                )
                                            case Result(error=err):
                                                return Error(err)
                                    case Result(error=err):
                                        return Error(err)
                            return Error(
                                RefusalError(
                                    "recovery_conflict",
                                    f"Cannot recover receipt: ref {receipt.ref} is at "
                                    f"{current_ref}, expected {receipt.before} or "
                                    f"{receipt.after}.",
                                )
                            )
                        case Result(error=err):
                            return Error(err)
                case Result(error=err):
                    return Error(err)
        case Result(error=err):
            return Error(err)


def _consume_or_recover(
    cwd: Path, git_dir: Path
) -> Result[Option[dict[str, object]], AutommitError]:
    match read_receipt(git_dir):
        case Result(tag="ok", ok=receipt_opt):
            match receipt_opt:
                case Option(tag="some", some=receipt):
                    if receipt.state == "committed":
                        match remove_receipt(git_dir):
                            case Result(tag="ok"):
                                return Ok(Nothing)
                            case Result(error=err):
                                return Error(err)
                    match _recover_receipt(cwd, git_dir, receipt):
                        case Result(tag="ok", ok=recovered):
                            return Ok(Some(recovered))
                        case Result(error=err):
                            return Error(err)
                case _:
                    return Ok(Nothing)
        case Result(error=err):
            return Error(err)


def prepare(
    cwd: Path,
    context: tuple[str, ...],
    *,
    scope: Literal["staged", "all"] = "all",
) -> Result[dict[str, object], AutommitError]:
    """Recover if needed, stage per scope, and expose exact planning evidence."""
    match _git_dir(cwd):
        case Result(tag="ok", ok=git_dir):
            try:
                with operation_lock(git_dir):
                    match _consume_or_recover(cwd, git_dir):
                        case Result(tag="ok", ok=recovered_opt):
                            match recovered_opt:
                                case Option(tag="some", some=recovered):
                                    return Ok(recovered)
                                case _:
                                    pass
                        case Result(error=err):
                            return Error(err)
                    match _staged_files(cwd):
                        case Result(tag="ok", ok=staged):
                            if scope == "all":
                                match run_git(cwd, "add", "--all"):
                                    case Result(tag="ok"):
                                        match _staged_files(cwd):
                                            case Result(tag="ok", ok=staged_all):
                                                staged = staged_all
                                            case Result(error=err):
                                                return Error(err)
                                    case Result(error=err):
                                        return Error(err)
                            elif not staged:
                                return Error(
                                    AutommitError(
                                        "no_staged_changes",
                                        "No staged changes found to commit.",
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
                                                            "snapshot": (
                                                                _snapshot_token(
                                                                    evidence
                                                                )
                                                            ),
                                                            "ref": evidence.ref,
                                                            "before": (evidence.before),
                                                            "index_tree": (
                                                                evidence.index_tree
                                                            ),
                                                            "staged_files": list(
                                                                staged
                                                            ),
                                                            "changed_hunk_count": (
                                                                changed_hunk_count(diff)
                                                            ),
                                                            "context": (
                                                                "\n\n".join(
                                                                    value
                                                                    for value in context
                                                                    if value
                                                                )
                                                            ),
                                                            "repository_context": (
                                                                repo_context
                                                            ),
                                                            "diff": diff,
                                                        }
                                                    )
                                                case Result(error=err):
                                                    return Error(err)
                                        case Result(error=err):
                                            return Error(err)
                                case Result(error=err):
                                    return Error(err)
                        case Result(error=err):
                            return Error(err)
            except AutommitError as error:
                return Error(error)
        case Result(error=err):
            return Error(err)


def read_json_file(path: Path, kind: str) -> Result[object, AutommitError]:
    """Read bounded JSON from a regular file."""
    if not path.exists() or path.is_symlink() or not path.is_file():
        return Error(
            AutommitError(
                "invalid_file",
                f"Autommit {kind} file must be an existing regular file.",
            )
        )
    try:
        with path.open("rb") as handle:
            content = handle.read(MAX_POLICY_FILE_BYTES)
    except OSError as error:
        return Error(AutommitError("file_io", f"Unable to read {kind} file: {error}."))
    try:
        data: object = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        return Error(
            AutommitError(
                "invalid_json", f"Autommit {kind} is not valid JSON: {error}."
            )
        )
    return Ok(data)


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
                                case Result(error=err):
                                    return Error(err)
                        case Result(error=err):
                            return Error(err)
                case Result(error=err):
                    return Error(err)
        case Result(error=err):
            return Error(err)


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
            if require_split and len(proposal.commits) < _MIN_SPLIT_COMMITS:
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


def _apply_order(
    proposal: CommitProposal,
    _staged_diff: str,
    _zero_context_diff: str,
) -> tuple[CommitGroup, ...]:
    """Preserve model's planned semantic commit order without re-sorting by line position."""
    return proposal.commits


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
                (
                    "This broad single-commit proposal requires "
                    "an atomicity decision file."
                ),
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
                                f"Atomicity critic requires a split: {concerns}. "
                                f"Rationale: {decision.rationale}",
                            )
                        )
                    return Ok(Some(decision))
                case Result(error=err):
                    return Error(err)
        case Result(error=err):
            return Error(err)


def _assert_receipt_evidence(
    cwd: Path, receipt: Receipt, final_head: str
) -> Result[None, AutommitError]:
    match _commit_exists(cwd, final_head):
        case Result(tag="ok", ok=commit_ok):
            if not commit_ok:
                return Error(
                    AutommitError(
                        "missing_target_commit",
                        "Created final commit object missing before ref update.",
                    )
                )
            match _tree_for_commit(cwd, final_head):
                case Result(tag="ok", ok=created_tree):
                    if created_tree != receipt.index_tree:
                        return Error(
                            RefusalError(
                                "tree_mismatch",
                                (
                                    "Prepared commit tree does not match "
                                    "staged index tree."
                                ),
                            )
                        )
                    return Ok(None)
                case Result(error=err):
                    return Error(err)
        case Result(error=err):
            return Error(err)


def apply(
    cwd: Path,
    snapshot: str,
    plan_file: Path,
    decision_file: Path | None,
) -> Result[dict[str, object], AutommitError]:
    """Prepare commits off-branch, verify final tree, and publish by CAS."""
    match _git_dir(cwd):
        case Result(tag="ok", ok=git_dir):
            try:
                with operation_lock(git_dir):
                    match _consume_or_recover(cwd, git_dir):
                        case Result(tag="ok"):
                            pass
                        case Result(error=err):
                            return Error(err)
                    match _load_validated_plan(cwd, snapshot, plan_file):
                        case Result(
                            tag="ok",
                            ok=(
                                expected,
                                proposal,
                                _,
                                staged_diff,
                                review,
                            ),
                        ):
                            match _require_atomicity_decision(review, decision_file):
                                case Result(tag="ok"):
                                    pass
                                case Result(error=err):
                                    return Error(err)
                            match _staged_diff(cwd, zero_context=True):
                                case Result(tag="ok", ok=zero_context_diff):
                                    pass
                                case Result(error=err):
                                    return Error(err)
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
                                                    _ = patch.write_text(
                                                        patch_content,
                                                        encoding="utf-8",
                                                    )
                                                case Result(error=err):
                                                    return Error(err)
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
                                            _ = message.write_text(
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
                                            match run_git(
                                                worktree, "rev-parse", "HEAD"
                                            ):
                                                case Result(tag="ok", ok=head_sha):
                                                    created.append(
                                                        {
                                                            "sha": head_sha.strip(),
                                                            "summary": (group.summary),
                                                        }
                                                    )
                                                case Result(error=err):
                                                    return Error(err)
                                        match run_git(worktree, "rev-parse", "HEAD"):
                                            case Result(tag="ok", ok=final_head_str):
                                                final_head = final_head_str.strip()
                                            case Result(error=err):
                                                return Error(err)
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
                                        if prepared_tree != expected.index_tree:
                                            return Error(
                                                RefusalError(
                                                    "tree_mismatch",
                                                    (
                                                        "Prepared commit tree does not "
                                                        "match the staged index."
                                                    ),
                                                )
                                            )
                                        match _staged_diff(cwd):
                                            case Result(tag="ok", ok=current_diff):
                                                if current_diff != staged_diff:
                                                    return Error(
                                                        RefusalError(
                                                            "snapshot_changed",
                                                            (
                                                                "Staged snapshot changed "
                                                                "during atomic commit preparation."
                                                            ),
                                                        )
                                                    )
                                            case Result(error=err):
                                                return Error(err)
                                        match _assert_snapshot(cwd, snapshot):
                                            case Result(tag="ok"):
                                                pass
                                            case Result(error=err):
                                                return Error(err)
                                        receipt = Receipt(
                                            1,
                                            "prepared",
                                            expected.ref,
                                            expected.before,
                                            final_head,
                                            expected.index_tree,
                                        )
                                        match write_receipt(git_dir, receipt):
                                            case Result(tag="ok"):
                                                pass
                                            case Result(error=err):
                                                return Error(err)
                                        match _assert_snapshot(cwd, snapshot):
                                            case Result(tag="ok"):
                                                pass
                                            case Result(error=err):
                                                return Error(err)
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
                                        match _assert_receipt_evidence(
                                            cwd, receipt, final_head
                                        ):
                                            case Result(tag="ok"):
                                                pass
                                            case Result(error=err):
                                                return Error(err)
                                        match remove_receipt(git_dir):
                                            case Result(tag="ok"):
                                                pass
                                            case Result(error=err):
                                                pass
                                        return Ok(
                                            {
                                                "status": "committed",
                                                "message": (
                                                    f"Created {len(created)} commit"
                                                    + ("s" if len(created) != 1 else "")
                                                    + " atomically."
                                                ),
                                                "before": expected.before,
                                                "after": final_head,
                                                "commits": created,
                                            }
                                        )
                                    finally:
                                        if added:
                                            _ = try_git(
                                                cwd,
                                                "worktree",
                                                "remove",
                                                "--force",
                                                str(worktree),
                                            )
                        case Result(error=err):
                            return Error(err)
            except AutommitError as error:
                return Error(error)
        case Result(error=err):
            return Error(err)
