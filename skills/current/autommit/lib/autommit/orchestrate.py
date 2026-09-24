"""Own the autommit loop: prepare, plan, validate, critique, apply."""

from __future__ import annotations

import json
import os
import re
import signal
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal, cast

from autommit.client import ModelRequest, call_critic, call_planner
from autommit.config import ConfigOverrides, load_config
from autommit.errors import AutommitError, CancelledError
from autommit.git import try_git
from autommit.inventory import (
    CRITIC_SYSTEM,
    PLAN_SYSTEM,
    CriticEvidence,
    FileInventory,
    PlannerEvidence,
    build_inventory,
    planner_diff,
    render_critic_prompt,
    render_planner_prompt,
    stack_correction,
)
from autommit.proposal import (
    normalize_atomicity_decision,
    normalize_proposal,
    requires_atomicity_review,
)
from autommit.service import apply, prepare, validate_plan
from autommit.transaction import format_recovery_hint, read_recovery_point

if TYPE_CHECKING:
    from collections.abc import Callable

    from autommit.client import HttpResponse

SCHEMA: Final[str] = "autommit/v1"
MAX_PLAN_ATTEMPTS: Final[int] = 3
MAX_FORCED_SPLIT_ATTEMPTS: Final[int] = 3
MAX_CRITIC_ATTEMPTS: Final[int] = 2
RETRYABLE_PLAN_CODES: Final[frozenset[str]] = frozenset(
    {"invalid_plan", "split_required"}
)
MIN_SPLIT_COMMITS: Final[int] = 2
MAX_ERROR_CHARS: Final[int] = 2000
_SUBJECT: Final[re.Pattern[str]] = re.compile(r"^### \S+ (.+)$", re.MULTILINE)
_CONVENTIONAL: Final[re.Pattern[str]] = re.compile(r"[a-z]+(\([^)]*\))?!?: ")


@dataclass(frozen=True, slots=True)
class RunOptions:
    """Everything one single-command run needs."""

    repo: Path
    scope: Literal["auto", "staged", "all"] = "auto"
    context: tuple[str, ...] = ()
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    timeout: float | None = None
    reasoning_effort: str | None = None
    smoke: str | None = None
    base: str | None = None
    dry_run: bool = False
    json_output: bool = False
    post: Callable[[dict[str, object]], HttpResponse] | None = None


@dataclass(frozen=True, slots=True)
class _Brain:
    """Resolved endpoint settings shared by every model call."""

    model: str
    base_url: str
    api_key: str
    timeout: float
    reasoning_effort: str | None = None
    notify: Callable[[str], None] | None = None


@dataclass(frozen=True, slots=True)
class _PlanContext:
    """Everything the plan and critic steps need."""

    options: RunOptions
    brain: _Brain
    snapshot: str
    plan_path: Path
    decision_path: Path
    evidence: PlannerEvidence
    staged_count: int
    hunk_count: int
    diff: str
    move_commit: dict[str, object] | None = None
    whole_files: frozenset[str] = frozenset()


def _raise_cancelled(signum: int, frame: object) -> None:
    del signum, frame
    raise CancelledError


def _install_signal_handlers() -> dict[int, signal.Handlers]:
    previous: dict[int, signal.Handlers] = {}
    for name in ("SIGINT", "SIGTERM"):
        signum = getattr(signal, name, None)
        if signum is None:
            continue
        previous[signum] = cast("signal.Handlers", signal.getsignal(signum))
        signal.signal(signum, _raise_cancelled)
    return previous


def _restore_signal_handlers(previous: dict[int, signal.Handlers]) -> None:
    for signum, handler in previous.items():
        signal.signal(signum, handler)


def _write(message: str) -> None:
    sys.stdout.write(message + "\n")
    sys.stdout.flush()


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
    return {"schema": SCHEMA, "ok": True, "command": "run", "result": data}


def _failure(error: AutommitError, message: str) -> dict[str, object]:
    return {
        "schema": SCHEMA,
        "ok": False,
        "command": "run",
        "error": {"code": error.code, "message": message},
    }


def _recovery_hint(repo: Path) -> str | None:
    result = try_git(repo, "rev-parse", "--absolute-git-dir")
    if result.returncode != 0:
        return None
    point = read_recovery_point(Path(result.stdout.strip()).resolve())
    if point is None:
        return None
    return format_recovery_hint(point.ref, point.before)


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


def _with_correction(
    evidence: PlannerEvidence, correction: str | None
) -> PlannerEvidence:
    return PlannerEvidence(
        inventory=evidence.inventory,
        staged_files=evidence.staged_files,
        repository_context=evidence.repository_context,
        user_context=evidence.user_context,
        correction=correction,
        diff=evidence.diff,
    )


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


def _attempt_plan(
    context: _PlanContext,
    evidence: PlannerEvidence,
    *,
    require_split: bool,
    attempts: int,
) -> tuple[tuple[dict[str, object], bool] | None, str]:
    """Run a bounded planner loop, feeding exact validation errors back.

    Returns the settled plan (or None) and the last validation error. Pure
    renames never reach the model; their move-only commit is appended here,
    and the split and critic gates judge the model's commits alone.
    """
    current = evidence
    last_error = ""
    stage = "Replanning for the critic" if require_split else "Planning"
    for attempt in range(1, max(1, attempts) + 1):
        try:
            planned = call_planner(
                _planner_request(
                    context.brain, current, f"{stage} (attempt {attempt}/{attempts})"
                ),
                post=context.options.post,
            )
            planned = _dedupe_whole_files(
                _whole_file_selectors(planned, context.whole_files)
            )
            model_proposal = normalize_proposal(planned)
            if require_split and len(model_proposal.commits) < MIN_SPLIT_COMMITS:
                raise AutommitError(
                    "split_required",
                    "Atomicity review requires at least two commits.",
                )
            payload = _with_move_commit(planned, context.move_commit)
            context.plan_path.write_text(json.dumps(payload), encoding="utf-8")
            _ = validate_plan(context.options.repo, context.snapshot, context.plan_path)
        except AutommitError as error:
            if error.code not in RETRYABLE_PLAN_CODES:
                raise
            last_error = error.message
            # keep the standing correction (the critic's concerns) and add the rejection
            current = _with_correction(
                evidence, stack_correction(evidence.correction, error.message)
            )
            continue
        return (payload, requires_atomicity_review(model_proposal, context.diff)), ""
    return None, last_error


def _plan(
    context: _PlanContext, evidence: PlannerEvidence
) -> tuple[tuple[dict[str, object], bool] | None, str]:
    """Plan the staged snapshot; a moves-only snapshot needs no model."""
    if not evidence.staged_files and context.move_commit is not None:
        payload: dict[str, object] = {"commits": [context.move_commit]}
        context.plan_path.write_text(json.dumps(payload), encoding="utf-8")
        _ = validate_plan(context.options.repo, context.snapshot, context.plan_path)
        return (payload, False), ""
    if context.move_commit is not None:
        moved = len(cast("list[object]", context.move_commit["changes"]))
        _progress(
            context.options,
            f"Committing {moved} pure rename(s) as one move-only commit.",
        )
    return _attempt_plan(
        context, evidence, require_split=False, attempts=MAX_PLAN_ATTEMPTS
    )


def _whole_file_selectors(
    planned: dict[str, object], whole_files: frozenset[str]
) -> dict[str, object]:
    """Select hunkless files whole: no other selector can apply to them."""
    commits = planned.get("commits")
    if not whole_files or not isinstance(commits, list):
        return planned
    return {
        **planned,
        "commits": [
            {
                **commit,
                "changes": [
                    {**change, "hunks": "all"}
                    if isinstance(change, dict) and change.get("path") in whole_files
                    else change
                    for change in commit.get("changes", [])
                ],
            }
            if isinstance(commit, dict)
            else commit
            for commit in commits
        ],
    }


def _dedupe_whole_files(planned: dict[str, object]) -> dict[str, object]:
    """Keep a file selected whole only in its first whole-file commit.

    Any other selection of that file is redundant, so it is dropped; a commit
    left empty is removed and dependency indices are remapped.
    """
    commits = cast("list[dict[str, object]]", planned.get("commits", []))
    owner: dict[str, int] = {}
    for index, commit in enumerate(commits):
        for change in cast("list[dict[str, object]]", commit.get("changes", [])):
            path = str(change.get("path"))
            if change.get("hunks") == "all" and path not in owner:
                owner[path] = index
    kept: list[dict[str, object]] = []
    remap: dict[int, int] = {}
    for index, commit in enumerate(commits):
        changes = [
            change
            for change in cast("list[dict[str, object]]", commit.get("changes", []))
            if owner.get(str(change.get("path")), index) == index
            and not (change.get("hunks") != "all" and str(change.get("path")) in owner)
        ]
        if changes:
            remap[index] = len(kept)
            kept.append({**commit, "changes": changes})
    if len(kept) == len(commits) and all(
        len(cast("list[object]", a.get("changes", [])))
        == len(cast("list[object]", b.get("changes", [])))
        for a, b in zip(kept, commits, strict=True)
    ):
        return planned
    return {
        **planned,
        "commits": [
            {
                **commit,
                "dependencies": [
                    remap[int(cast("int", dep))]
                    for dep in cast("list[object]", commit.get("dependencies", []))
                    if int(cast("int", dep)) in remap
                ],
            }
            for commit in kept
        ],
    }


def _with_move_commit(
    planned: dict[str, object], move_commit: dict[str, object] | None
) -> dict[str, object]:
    """Append the move-only commit and apply it first: later commits use its paths."""
    if move_commit is None:
        return planned
    commits = cast("list[object]", planned.get("commits", []))
    move_index = len(commits)
    return {
        **planned,
        "commits": [
            *(
                {
                    **commit,
                    "dependencies": [
                        *cast("list[object]", commit.get("dependencies", [])),
                        move_index,
                    ],
                }
                if isinstance(commit, dict)
                else commit
                for commit in commits
            ),
            move_commit,
        ],
    }


def _move_commit(
    moves: tuple[str, ...], repository_context: str
) -> dict[str, object] | None:
    """One deterministic move-only commit for renames with identical content."""
    if not moves:
        return None
    subjects = _SUBJECT.findall(repository_context)
    conventional = sum(1 for subject in subjects if _CONVENTIONAL.match(subject))
    summary = (
        "refactor: move files without content changes"
        if subjects and conventional * 2 > len(subjects)
        else "Move files without content changes"
    )
    return {
        "summary": summary,
        "details": [f"Rename {len(moves)} file(s); content is unchanged."],
        "dependencies": [],
        "changes": [{"path": path, "hunks": "all"} for path in moves],
    }


def _brief(message: str) -> str:
    if len(message) <= MAX_ERROR_CHARS:
        return message
    return message[:MAX_ERROR_CHARS].rstrip() + " ..."


def _forced_split_correction(concerns: tuple[str, ...], rationale: str) -> str:
    listed = "\n".join(f"- {concern}" for concern in concerns)
    return (
        "The independent atomicity critic rejected the single-commit proposal.\n"
        f"Concerns:\n{listed}\n"
        f"Rationale: {rationale}\n"
        "Return at least two commits in `commits`: one commit per concern above. "
        "A single commit is rejected."
    )


def _review(context: _PlanContext, proposal_payload: dict[str, object]) -> Path | None:
    """Run the critic gate; return a decision file when one is required."""
    _progress(context.options, "Reviewing atomicity...")
    provisional = normalize_proposal(proposal_payload)
    first = provisional.commits[0]
    evidence = CriticEvidence(
        summary=first.summary,
        details=first.details,
        staged_count=context.staged_count,
        hunk_count=context.hunk_count,
        diff=context.diff,
    )
    decision: dict[str, object] | None = None
    for attempt in range(1, MAX_CRITIC_ATTEMPTS + 1):
        try:
            decision = call_critic(
                _critic_request(
                    context.brain,
                    evidence,
                    f"Reviewing atomicity (attempt {attempt}/{MAX_CRITIC_ATTEMPTS})",
                ),
                post=context.options.post,
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
        context.decision_path.write_text(json.dumps(decision), encoding="utf-8")
        return context.decision_path
    forced, last_error = _attempt_plan(
        context,
        _with_correction(
            context.evidence,
            _forced_split_correction(verdict.concerns, verdict.rationale),
        ),
        require_split=True,
        attempts=MAX_FORCED_SPLIT_ATTEMPTS,
    )
    if forced is None:
        raise AutommitError(
            "atomicity_split_required",
            "The atomicity critic required a split and no valid multi-commit "
            f"plan was produced. Last error: {_brief(last_error)}",
        )
    return None


def _dry_run_payload(
    prepared: dict[str, object],
    inventory: tuple[FileInventory, ...],
    staged_files: tuple[str, ...],
) -> dict[str, object]:
    return {
        "status": "dry_run",
        "snapshot": prepared.get("snapshot"),
        "staged_files": list(staged_files),
        "changed_hunk_count": prepared.get("changed_hunk_count"),
        "inventory": prepared.get("inventory"),
        "files": [file.path for file in inventory],
    }


def _report(options: RunOptions, result: dict[str, object]) -> None:
    commits = cast("list[dict[str, str]]", result.get("commits", []))
    if options.json_output:
        _emit(_success(result))
        return
    for commit in commits:
        _write(f"Created {commit['sha'][:7]} {commit['summary']}")
    before = str(result.get("before", ""))[:7]
    after = str(result.get("after", ""))[:7]
    _write(
        f"Created {len(commits)} commit(s) on {result.get('ref', '')} "
        f"({before} -> {after})."
    )


def run_orchestrated(options: RunOptions) -> int:
    """Run the full loop and return the process exit code."""
    previous = _install_signal_handlers()
    try:
        prepared = prepare(options.repo, options.context, scope=options.scope)
        if prepared.get("status") == "recovered":
            _note(
                options, f"Recovered an interrupted run at {prepared.get('after', '')}."
            )
            prepared = prepare(options.repo, options.context, scope=options.scope)
            if prepared.get("status") == "recovered":
                _note(options, "Nothing left to commit after recovery.")
                return 0
        snapshot = str(prepared["snapshot"])
        staged_files = tuple(cast("list[str]", prepared["staged_files"]))
        hunk_count = int(cast("int", prepared["changed_hunk_count"]))
        inventory = build_inventory(options.repo, staged_files, str(prepared["diff"]))
        repository_context = str(prepared.get("repository_context", ""))
        user_context = tuple(cast("list[str]", prepared.get("user_context", [])))
        zero_diff = str(prepared.get("zero_diff", ""))
        ref = str(prepared["ref"])
        before = str(prepared["before"])
        _note(
            options,
            f"Prepared {len(staged_files)} file(s), {hunk_count} hunk(s) "
            f"(snapshot {snapshot[:8]}).",
        )

        if options.dry_run:
            payload = _dry_run_payload(prepared, inventory, staged_files)
            payload["zero_diff"] = zero_diff
            if options.json_output:
                _emit(_success(payload))
            else:
                for file in inventory:
                    _write(f"- {file.path} [{file.status}] {len(file.hunks)} hunk(s)")
                _write("Dry run only: no commits created.")
            return 0

        brain = _brain(options)
        moves = tuple(file.path for file in inventory if file.is_pure_rename)
        planned_diff = planner_diff(str(prepared["diff"]), frozenset(moves))
        evidence = PlannerEvidence(
            inventory=tuple(file for file in inventory if not file.is_pure_rename),
            staged_files=tuple(path for path in staged_files if path not in moves),
            repository_context=repository_context,
            user_context=user_context,
            correction=None,
            diff=planned_diff,
        )
        with tempfile.TemporaryDirectory(prefix="autommit-run-") as run_dir:
            context = _PlanContext(
                options=options,
                brain=brain,
                snapshot=snapshot,
                plan_path=Path(run_dir) / "plan.json",
                decision_path=Path(run_dir) / "decision.json",
                evidence=evidence,
                staged_count=len(evidence.staged_files),
                hunk_count=hunk_count,
                diff=planned_diff,
                move_commit=_move_commit(moves, repository_context),
                whole_files=frozenset(
                    file.path for file in evidence.inventory if file.whole_file_only
                ),
            )
            _progress(options, "Planning...")
            planned, last_error = _plan(context, evidence)
            if planned is None:
                raise AutommitError(
                    "invalid_plan",
                    f"Planner produced no valid plan after {MAX_PLAN_ATTEMPTS} "
                    f"attempts. Last error: {_brief(last_error)}",
                )
            payload, review = planned
            decision_file = _review(context, payload) if review else None
            settled = normalize_proposal(payload)
            _progress(options, f"Applying {len(settled.commits)} commit(s)...")
            result = apply(
                options.repo,
                snapshot,
                context.plan_path,
                decision_file,
                smoke=options.smoke,
            )
            result["recovery_hint"] = format_recovery_hint(ref, before)
            _report(options, result)
            return 0
    except AutommitError as error:
        hint = _recovery_hint(options.repo)
        message = error.message if hint is None else f"{error.message} {hint}"
        if options.json_output:
            _emit(_failure(error, message), error=True)
        else:
            _write_error(f"Error [{error.code}]: {message}")
        return error.exit_code
    finally:
        _restore_signal_handlers(previous)
