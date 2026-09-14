"""Own the autommit loop: prepare, plan, validate, critique, apply."""

from __future__ import annotations

import json
import os
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
    render_critic_prompt,
    render_planner_prompt,
)
from autommit.proposal import normalize_atomicity_decision, normalize_proposal
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


def _progress(options: RunOptions, message: str) -> None:
    """Announce a blocking stage on stderr; machine output stays on stdout."""
    if options.json_output:
        return
    sys.stderr.write(message + "\n")
    sys.stderr.flush()


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


def _planner_request(brain: _Brain, evidence: PlannerEvidence) -> ModelRequest:
    return ModelRequest(
        model=brain.model,
        base_url=brain.base_url,
        api_key=brain.api_key,
        timeout=brain.timeout,
        system=PLAN_SYSTEM,
        user=render_planner_prompt(evidence),
        reasoning_effort=brain.reasoning_effort,
    )


def _critic_request(brain: _Brain, evidence: CriticEvidence) -> ModelRequest:
    return ModelRequest(
        model=brain.model,
        base_url=brain.base_url,
        api_key=brain.api_key,
        timeout=brain.timeout,
        system=CRITIC_SYSTEM,
        user=render_critic_prompt(evidence),
        reasoning_effort=brain.reasoning_effort,
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
        zero_diff=evidence.zero_diff,
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
    if not config.api_key:
        raise AutommitError(
            "missing_api_key",
            "Set AUTOMMIT_API_KEY or OPENAI_API_KEY, or pass an API key argument.",
        )
    return _Brain(
        model=config.model,
        base_url=config.base_url,
        api_key=config.api_key,
        timeout=config.timeout,
        reasoning_effort=config.reasoning_effort,
    )


def _attempt_plan(
    context: _PlanContext,
    evidence: PlannerEvidence,
    *,
    require_split: bool,
    attempts: int,
) -> tuple[dict[str, object], bool] | None:
    """Run a bounded planner loop, feeding exact validation errors back."""
    current = evidence
    for _ in range(max(1, attempts)):
        try:
            payload = call_planner(
                _planner_request(context.brain, current), post=context.options.post
            )
            context.plan_path.write_text(json.dumps(payload), encoding="utf-8")
            validation = validate_plan(
                context.options.repo,
                context.snapshot,
                context.plan_path,
                require_split=require_split,
            )
        except AutommitError as error:
            if error.code not in RETRYABLE_PLAN_CODES:
                raise
            current = _with_correction(evidence, error.message)
            continue
        review = bool(validation["requires_atomicity_review"])
        return payload, review
    return None


def _forced_split_correction(concerns: tuple[str, ...], rationale: str) -> str:
    listed = "\n".join(f"- {concern}" for concern in concerns)
    return (
        "The independent atomicity critic rejected the single-commit proposal.\n"
        f"Concerns:\n{listed}\n"
        f"Rationale: {rationale}\n"
        "Split the staged changes into at least two commits, one per concern."
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
    for _ in range(MAX_CRITIC_ATTEMPTS):
        try:
            decision = call_critic(
                _critic_request(context.brain, evidence), post=context.options.post
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
    forced = _attempt_plan(
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
            "plan was produced.",
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
        evidence = PlannerEvidence(
            inventory=inventory,
            staged_files=staged_files,
            repository_context=repository_context,
            user_context=user_context,
            correction=None,
            zero_diff=zero_diff,
        )
        with tempfile.TemporaryDirectory(prefix="autommit-run-") as run_dir:
            context = _PlanContext(
                options=options,
                brain=brain,
                snapshot=snapshot,
                plan_path=Path(run_dir) / "plan.json",
                decision_path=Path(run_dir) / "decision.json",
                evidence=evidence,
                staged_count=len(staged_files),
                hunk_count=hunk_count,
                diff=str(prepared["diff"]),
            )
            _progress(options, "Planning...")
            planned = _attempt_plan(
                context,
                evidence,
                require_split=False,
                attempts=MAX_PLAN_ATTEMPTS,
            )
            if planned is None:
                raise AutommitError(
                    "invalid_plan",
                    f"Planner produced no valid plan after {MAX_PLAN_ATTEMPTS} attempts.",
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
