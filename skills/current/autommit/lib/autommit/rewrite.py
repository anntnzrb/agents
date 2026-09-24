"""Rebuild the commits since a base revision while preserving the final tree."""

from __future__ import annotations

import contextlib
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Final, cast

from autommit.client import ModelRequest, call_critic, call_planner
from autommit.config import ConfigOverrides, load_config
from autommit.errors import AutommitError, RefusalError
from autommit.fallback import CommitWork, apply_with_fallback
from autommit.git import GIT_DIFF_FLAGS, run_git, try_git
from autommit.inventory import (
    CRITIC_SYSTEM,
    PLAN_SYSTEM,
    CriticEvidence,
    FileInventory,
    PlannerEvidence,
    build_inventory,
    inventory_payload,
    planner_diff,
    render_critic_prompt,
    render_planner_prompt,
    stack_correction,
)
from autommit.proposal import (
    changed_hunk_count,
    compute_apply_order,
    normalize_atomicity_decision,
    normalize_proposal,
    parse_file_diffs,
    requires_atomicity_review,
    validate_proposal_coverage,
)
from autommit.service import (
    _blocking_state,
    _cas_ref,
    _commit_message,
    _git_dir,
    _repository_policy,
    _require_atomicity_decision,
    _run_smoke,
    read_json_file,
)
from autommit.transaction import (
    Receipt,
    RecoveryPoint,
    clear_recovery_point,
    format_recovery_hint,
    operation_lock,
    read_recovery_point,
    remove_receipt,
    write_receipt,
    write_recovery_point,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from autommit.orchestrate import RunOptions

SCHEMA: Final[str] = "autommit/v1"
MAX_PLAN_ATTEMPTS: Final[int] = 3
MAX_FORCED_SPLIT_ATTEMPTS: Final[int] = 3
MAX_CRITIC_ATTEMPTS: Final[int] = 2
RETRYABLE_PLAN_CODES: Final[frozenset[str]] = frozenset(
    {"invalid_plan", "split_required"}
)
DEFAULT_BASE_CANDIDATES: Final[tuple[str, ...]] = ("origin/HEAD", "origin/main", "main")
MIN_SPLIT_COMMITS: Final[int] = 2


@dataclass(frozen=True, slots=True)
class RewriteEvidence:
    """Everything a rewrite run binds before planning."""

    ref: str
    before: str
    base: str
    target_tree: str
    snapshot: str
    staged_files: tuple[str, ...]
    diff: str
    zero_diff: str
    inventory: tuple[FileInventory, ...]
    repository_context: str
    user_context: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Brain:
    """Resolved endpoint settings for rewrite calls."""

    model: str
    base_url: str
    api_key: str
    timeout: float
    reasoning_effort: str | None = None
    notify: Callable[[str], None] | None = None


def _write(message: str) -> None:
    print(message, flush=True)  # noqa: T201


def _write_error(message: str) -> None:
    sys.stderr.write(message + "\n")
    sys.stderr.flush()


def _note(options: RunOptions, message: str) -> None:
    """Write one human line to stdout unless the caller asked for JSON."""
    if options.json_output:
        return
    _write(message)


def _stderr_line(message: str) -> None:
    sys.stderr.write(message + "\n")
    sys.stderr.flush()


def _progress(options: RunOptions, message: str) -> None:
    """Announce a blocking stage on stderr; machine output stays on stdout."""
    if not options.json_output:
        _stderr_line(message)


def _emit(payload: dict[str, object], *, error: bool = False) -> None:
    stream = sys.stderr if error else sys.stdout
    stream.write(json.dumps(payload, separators=(",", ":")) + "\n")
    stream.flush()


def _success(data: object) -> dict[str, object]:
    return {"schema": SCHEMA, "ok": True, "command": "rewrite", "result": data}


def _failure(error: AutommitError, message: str) -> dict[str, object]:
    return {
        "schema": SCHEMA,
        "ok": False,
        "command": "rewrite",
        "error": {"code": error.code, "message": message},
    }


def _frozen_tree(cwd: Path) -> str:
    """Freeze the worktree, including uncommitted work, without touching the index."""
    with tempfile.TemporaryDirectory(prefix="autommit-rewrite-index-") as index_dir:
        env = {"GIT_INDEX_FILE": str(Path(index_dir) / "index")}
        _ = run_git(cwd, "read-tree", "HEAD", env=env)
        _ = run_git(cwd, "add", "--all", env=env)
        return run_git(cwd, "write-tree", env=env).strip()


def _range_diff(cwd: Path, base: str, target: str, *, zero_context: bool) -> str:
    arguments = [
        "diff",
        "--binary",
        "--src-prefix=a/",
        "--dst-prefix=b/",
        *GIT_DIFF_FLAGS,
    ]
    if zero_context:
        arguments.append("--unified=0")
    arguments.extend([base, target, "--"])
    return run_git(cwd, *arguments)


def _range_files(cwd: Path, base: str, target: str) -> tuple[str, ...]:
    output = run_git(cwd, "diff", "--name-only", "-z", base, target, "--")
    return tuple(item for item in output.split("\0") if item)


def _resolve_base(cwd: Path, requested: str | None) -> str:
    candidates: tuple[str, ...] = (requested,) if requested else DEFAULT_BASE_CANDIDATES
    for candidate in candidates:
        resolved = try_git(cwd, "rev-parse", f"{candidate}^{{commit}}")
        if resolved.returncode != 0:
            continue
        base = resolved.stdout.strip()
        ancestor = try_git(cwd, "merge-base", "--is-ancestor", base, "HEAD")
        if ancestor.returncode != 0:
            raise RefusalError(
                "invalid_base",
                f"Base revision {candidate} ({base[:7]}) is not an ancestor of HEAD.",
            )
        return base
    raise RefusalError(
        "invalid_base",
        "No usable base revision found. Pass --base <rev> explicitly.",
    )


def _snapshot_token(ref: str, before: str, target: str) -> str:
    canonical = json.dumps(
        {"ref": ref, "before": before, "target": target},
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(canonical.encode()).hexdigest()


def _evidence(repo: Path, prepared: dict[str, object]) -> RewriteEvidence:
    staged_files = tuple(cast("list[str]", prepared["staged_files"]))
    diff = str(prepared["diff"])
    return RewriteEvidence(
        ref=str(prepared["ref"]),
        before=str(prepared["before"]),
        base=str(prepared["base"]),
        target_tree=str(prepared["target_tree"]),
        snapshot=str(prepared["snapshot"]),
        staged_files=staged_files,
        diff=diff,
        zero_diff=str(prepared["zero_diff"]),
        inventory=build_inventory(repo, staged_files, diff),
        repository_context=str(prepared.get("repository_context", "")),
        user_context=tuple(cast("list[str]", prepared.get("user_context", []))),
    )


def _assert_snapshot(cwd: Path, evidence: RewriteEvidence) -> None:
    ref_result = try_git(cwd, "symbolic-ref", "--quiet", "HEAD")
    head_result = try_git(cwd, "rev-parse", "HEAD")
    ref = ref_result.stdout.strip() if ref_result.returncode == 0 else ""
    head = head_result.stdout.strip() if head_result.returncode == 0 else ""
    token = _snapshot_token(ref, head, _frozen_tree(cwd))
    if token != evidence.snapshot:
        raise RefusalError(
            "snapshot_changed",
            "Rewrite branch, HEAD, or worktree content changed after preparation.",
        )


def _record_point(git_dir: Path, evidence: RewriteEvidence) -> None:
    with contextlib.suppress(AutommitError, OSError):
        write_recovery_point(
            git_dir,
            RecoveryPoint(ref=evidence.ref, before=evidence.before, pid=os.getpid()),
        )


def prepare_rewrite(
    cwd: Path, context: tuple[str, ...], *, base_rev: str | None = None
) -> dict[str, object]:
    """Freeze the target tree, resolve the base, and expose rewrite evidence."""
    git_dir = _git_dir(cwd)
    with operation_lock(git_dir):
        if blocking := _blocking_state(git_dir):
            raise RefusalError("in_progress_state", blocking)
        ref_result = try_git(cwd, "symbolic-ref", "--quiet", "HEAD")
        head_result = try_git(cwd, "rev-parse", "HEAD")
        if ref_result.returncode != 0 or head_result.returncode != 0:
            raise AutommitError(
                "unsupported_checkout",
                "Rewrite requires a branch checkout with an existing HEAD.",
            )
        ref = ref_result.stdout.strip()
        before = head_result.stdout.strip()
        base = _resolve_base(cwd, base_rev)
        target_tree = _frozen_tree(cwd)
        staged = _range_files(cwd, base, target_tree)
        if not staged:
            raise AutommitError(
                "no_changes", "No changes since the base revision to rewrite."
            )
        diff = _range_diff(cwd, base, target_tree, zero_context=False)
        zero_diff = _range_diff(cwd, base, target_tree, zero_context=True)
        inventory = build_inventory(cwd, staged, diff)
        return {
            "status": "prepared",
            "mode": "rewrite",
            "ref": ref,
            "before": before,
            "base": base,
            "target_tree": target_tree,
            "snapshot": _snapshot_token(ref, before, target_tree),
            "staged_files": list(staged),
            "staged_file_count": len(staged),
            "changed_hunk_count": changed_hunk_count(diff),
            "diff": diff,
            "zero_diff": zero_diff,
            "inventory": inventory_payload(inventory),
            "repository_context": _repository_policy(cwd),
            "user_context": list(context),
            "context": "\n\n".join(context),
        }


def _validate_rewrite_plan(
    cwd: Path,
    evidence: RewriteEvidence,
    plan_file: Path,
    *,
    require_split: bool = False,
) -> dict[str, object]:
    _assert_snapshot(cwd, evidence)
    proposal = normalize_proposal(read_json_file(plan_file, "plan"))
    errors = validate_proposal_coverage(
        proposal, evidence.staged_files, parse_file_diffs(evidence.diff)
    )
    if errors:
        raise AutommitError("invalid_plan", "Invalid split plan: " + "; ".join(errors))
    if require_split and len(proposal.commits) < MIN_SPLIT_COMMITS:
        raise AutommitError(
            "split_required", "Atomicity review requires at least two commits."
        )
    return {
        "valid": True,
        "commit_count": len(proposal.commits),
        "staged_file_count": len(evidence.staged_files),
        "changed_hunk_count": changed_hunk_count(evidence.diff),
        "requires_atomicity_review": requires_atomicity_review(proposal, evidence.diff),
    }


def publish_rewrite(
    cwd: Path,
    evidence: RewriteEvidence,
    plan_file: Path,
    decision_file: Path | None,
    *,
    smoke: str | None = None,
) -> dict[str, object]:
    """Rebuild commits off-branch, verify the final tree, and move the branch by CAS."""
    git_dir = _git_dir(cwd)
    with operation_lock(git_dir):
        if blocking := _blocking_state(git_dir):
            raise RefusalError("in_progress_state", blocking)
        validation = _validate_rewrite_plan(cwd, evidence, plan_file)
        proposal = normalize_proposal(read_json_file(plan_file, "plan"))
        _ = _require_atomicity_decision(
            bool(validation["requires_atomicity_review"]), decision_file
        )
        created: list[dict[str, str]] = []

        with (
            tempfile.TemporaryDirectory(
                prefix="autommit-rewrite-worktree-"
            ) as worktree_name,
            tempfile.TemporaryDirectory(prefix="autommit-rewrite-patch-") as patch_name,
        ):
            worktree = Path(worktree_name)
            message = Path(patch_name) / "message.txt"
            run_git(cwd, "worktree", "add", "--detach", str(worktree), evidence.base)
            try:
                for commit_index in compute_apply_order(proposal.commits):
                    group = proposal.commits[commit_index]
                    work = CommitWork(
                        repo=cwd,
                        worktree=worktree,
                        patch_dir=Path(patch_name),
                        index_tree=evidence.target_tree,
                        ref=evidence.ref,
                        before=evidence.before,
                        staged_diff=evidence.diff,
                        zero_diff=evidence.zero_diff,
                    )
                    _ = apply_with_fallback(work, group)
                    if smoke is not None:
                        _run_smoke(worktree, smoke, evidence.ref, evidence.before)
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
                _record_point(git_dir, evidence)
                raise
            finally:
                try_git(cwd, "worktree", "remove", "--force", str(worktree))
                try_git(cwd, "worktree", "prune")

            final_tree = run_git(cwd, "rev-parse", f"{final_head}^{{tree}}").strip()
            if final_tree != evidence.target_tree:
                _record_point(git_dir, evidence)
                raise RefusalError(
                    "tree_mismatch",
                    "Rebuilt commits do not reproduce the frozen worktree tree.",
                )

            receipt = Receipt(
                version=1,
                state="prepared",
                ref=evidence.ref,
                before=evidence.before,
                after=final_head,
                index_tree=evidence.target_tree,
            )
            write_receipt(git_dir, receipt)
            _cas_ref(cwd, evidence.ref, final_head, evidence.before)
            remove_receipt(git_dir)
            clear_recovery_point(git_dir)
            _ = run_git(cwd, "read-tree", final_head)

            return {
                "status": "rewritten",
                "ref": evidence.ref,
                "base": evidence.base,
                "before": evidence.before,
                "after": final_head,
                "target_tree": evidence.target_tree,
                "commit_count": len(created),
                "commits": created,
                "recovery_hint": format_recovery_hint(evidence.ref, evidence.before),
            }


def _brain(options: RunOptions) -> _Brain:
    config = load_config(
        overrides=ConfigOverrides(
            model=options.model,
            base_url=options.base_url,
            api_key=options.api_key,
            timeout=options.timeout,
            reasoning_effort=options.reasoning_effort,
        ),
        environ=os.environ,
    )
    return _Brain(
        model=config.model,
        base_url=config.base_url,
        api_key=config.api_key,
        timeout=config.timeout,
        reasoning_effort=config.reasoning_effort,
        notify=None if options.json_output else _stderr_line,
    )


def _planner_evidence(
    evidence: RewriteEvidence, correction: str | None
) -> PlannerEvidence:
    return PlannerEvidence(
        inventory=evidence.inventory,
        staged_files=evidence.staged_files,
        repository_context=evidence.repository_context,
        user_context=evidence.user_context,
        correction=correction,
        diff=planner_diff(evidence.diff, frozenset()),
    )


def _planner_request(
    brain: _Brain, evidence: PlannerEvidence, label: str
) -> ModelRequest:
    return ModelRequest(
        model=brain.model,
        base_url=brain.base_url,
        api_key=brain.api_key,
        timeout=brain.timeout,
        system=PLAN_SYSTEM,
        user=render_planner_prompt(evidence),
        reasoning_effort=brain.reasoning_effort,
        label=label,
        notify=brain.notify,
    )


def _critic_request(
    brain: _Brain, evidence: CriticEvidence, label: str
) -> ModelRequest:
    return ModelRequest(
        model=brain.model,
        base_url=brain.base_url,
        api_key=brain.api_key,
        timeout=brain.timeout,
        system=CRITIC_SYSTEM,
        user=render_critic_prompt(evidence),
        reasoning_effort=brain.reasoning_effort,
        label=label,
        notify=brain.notify,
    )


@dataclass(frozen=True, slots=True)
class _PlanRunner:
    """Shared state for bounded planner loops."""

    options: RunOptions
    brain: _Brain
    evidence: RewriteEvidence
    plan_file: Path


def _plan_loop(
    runner: _PlanRunner,
    *,
    correction: str | None,
    require_split: bool,
    attempts: int,
) -> dict[str, object] | None:
    current = correction
    stage = "Replanning for the critic" if require_split else "Planning"
    for attempt in range(1, max(1, attempts) + 1):
        try:
            payload = call_planner(
                _planner_request(
                    runner.brain,
                    _planner_evidence(runner.evidence, current),
                    f"{stage} (attempt {attempt}/{attempts})",
                ),
                post=runner.options.post,
            )
            runner.plan_file.write_text(json.dumps(payload), encoding="utf-8")
            _ = _validate_rewrite_plan(
                runner.options.repo,
                runner.evidence,
                runner.plan_file,
                require_split=require_split,
            )
        except AutommitError as error:
            if error.code not in RETRYABLE_PLAN_CODES:
                raise
            current = stack_correction(correction, error.message)
            continue
        return payload
    return None


def run_rewrite(options: RunOptions) -> int:
    """Rebuild history since the base revision and return the process exit code."""
    try:
        prepared = prepare_rewrite(options.repo, options.context, base_rev=options.base)
        evidence = _evidence(options.repo, prepared)
        _note(
            options,
            f"Frozen {len(evidence.staged_files)} file(s) since "
            f"{evidence.base[:7]} (snapshot {evidence.snapshot[:8]}).",
        )
        if options.dry_run:
            payload = {
                "status": "dry_run",
                "mode": "rewrite",
                "base": evidence.base,
                "target_tree": evidence.target_tree,
                "snapshot": evidence.snapshot,
                "staged_files": list(evidence.staged_files),
                "inventory": prepared["inventory"],
            }
            if options.json_output:
                _emit(_success(payload))
            else:
                for file in evidence.inventory:
                    _write(f"- {file.path} [{file.status}] {len(file.hunks)} hunk(s)")
                _write("Dry run only: history was not rewritten.")
            return 0

        brain = _brain(options)
        _progress(options, "Planning...")
        with tempfile.TemporaryDirectory(prefix="autommit-rewrite-run-") as run_dir:
            plan_file = Path(run_dir) / "plan.json"
            decision_file = Path(run_dir) / "decision.json"
            if (
                _plan_loop(
                    _PlanRunner(
                        options=options,
                        brain=brain,
                        evidence=evidence,
                        plan_file=plan_file,
                    ),
                    correction=None,
                    require_split=False,
                    attempts=MAX_PLAN_ATTEMPTS,
                )
                is None
            ):
                raise AutommitError(
                    "invalid_plan",
                    f"Planner produced no valid plan after {MAX_PLAN_ATTEMPTS} attempts.",
                )
            validation = _validate_rewrite_plan(options.repo, evidence, plan_file)
            chosen: Path | None = None
            if bool(validation["requires_atomicity_review"]):
                _progress(options, "Reviewing atomicity...")
                chosen = _review(options, brain, evidence, plan_file, decision_file)
            _progress(
                options,
                f"Rebuilding {int(cast('int', validation['commit_count']))} commit(s)...",
            )
            result = publish_rewrite(
                options.repo, evidence, plan_file, chosen, smoke=options.smoke
            )
            if options.json_output:
                _emit(_success(result))
            else:
                for commit in cast("list[dict[str, str]]", result["commits"]):
                    _write(f"Created {commit['sha'][:7]} {commit['summary']}")
                _write(
                    f"Rewrote {result['commit_count']} commit(s) since "
                    f"{evidence.base[:7]} ({evidence.before[:7]} -> "
                    f"{str(result['after'])[:7]})."
                )
            return 0
    except AutommitError as error:
        hint = _hint(options.repo)
        message = error.message if hint is None else f"{error.message} {hint}"
        if options.json_output:
            _emit(_failure(error, message), error=True)
        else:
            _write_error(f"Error [{error.code}]: {message}")
        return error.exit_code


def _review(
    options: RunOptions,
    brain: _Brain,
    evidence: RewriteEvidence,
    plan_file: Path,
    decision_file: Path,
) -> Path | None:
    """Run the critic gate; return a decision file, or None after a forced split."""
    proposal = normalize_proposal(read_json_file(plan_file, "plan"))
    first = proposal.commits[0]
    critic_evidence = CriticEvidence(
        summary=first.summary,
        details=first.details,
        staged_count=len(evidence.staged_files),
        hunk_count=changed_hunk_count(evidence.diff),
        diff=evidence.diff,
    )
    decision: dict[str, object] | None = None
    for attempt in range(1, MAX_CRITIC_ATTEMPTS + 1):
        try:
            decision = call_critic(
                _critic_request(
                    brain,
                    critic_evidence,
                    f"Reviewing atomicity (attempt {attempt}/{MAX_CRITIC_ATTEMPTS})",
                ),
                post=options.post,
            )
        except AutommitError as error:
            if error.code != "invalid_atomicity_decision":
                raise
            continue
        break
    if decision is None:
        raise AutommitError(
            "invalid_atomicity_decision",
            f"Atomicity critic produced no verdict after {MAX_CRITIC_ATTEMPTS} attempts.",
        )
    verdict = normalize_atomicity_decision(decision)
    if verdict.decision == "accept":
        decision_file.write_text(json.dumps(decision), encoding="utf-8")
        return decision_file
    listed = "\n".join(f"- {concern}" for concern in verdict.concerns)
    correction = (
        "The independent atomicity critic rejected the single-commit proposal.\n"
        f"Concerns:\n{listed}\n"
        f"Rationale: {verdict.rationale}\n"
        "Split the changes into at least two commits, one per concern."
    )
    if (
        _plan_loop(
            _PlanRunner(
                options=options,
                brain=brain,
                evidence=evidence,
                plan_file=plan_file,
            ),
            correction=correction,
            require_split=True,
            attempts=MAX_FORCED_SPLIT_ATTEMPTS,
        )
        is None
    ):
        raise AutommitError(
            "atomicity_split_required",
            "The atomicity critic required a split and no valid multi-commit "
            "plan was produced.",
        )
    return None


def _hint(repo: Path) -> str | None:
    result = try_git(repo, "rev-parse", "--absolute-git-dir")
    if result.returncode != 0:
        return None
    point = read_recovery_point(Path(result.stdout.strip()).resolve())
    if point is None:
        return None
    return format_recovery_hint(point.ref, point.before)
