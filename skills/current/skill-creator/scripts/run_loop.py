#!/usr/bin/env -S uv run --script
# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
# /// script
# requires-python = ">=3.12"
# dependencies = ["PyYAML>=6.0"]
# ///
"""Run the eval + improve loop until all pass or max iterations reached.

Combines run_eval.py and improve_description.py in a loop, tracking history
and returning the best description found. Supports train/test split to prevent
overfitting.
"""

import argparse
import json
import random
import sys
import tempfile
import time
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path

from scripts.generate_report import generate_html
from scripts.improve_description import ImproveParams, improve_description
from scripts.run_eval import EvalParams, find_project_root, run_eval
from scripts.utils import parse_skill_md


@dataclass(frozen=True, slots=True)
class LoopConfig:
    """Eval + improvement loop configuration."""

    eval_set: list[dict]
    skill_path: Path
    description_override: str | None
    num_workers: int
    timeout: int
    max_iterations: int
    runs_per_query: int
    trigger_threshold: float
    holdout: float
    model: str
    verbose: bool
    live_report_path: Path | None = None
    log_dir: Path | None = None


@dataclass(slots=True)
class _LoopState:
    """Mutable per-run loop state threaded through iteration helpers."""

    name: str
    original_description: str
    content: str
    train_set: list[dict]
    test_set: list[dict]
    current_description: str
    history: list[dict] = field(default_factory=list)


def _summarize(result_list: list[dict]) -> dict:
    """Summarize pass/fail counts for one result list."""
    passed = sum(1 for r in result_list if r["pass"])
    total = len(result_list)
    return {"passed": passed, "failed": total - passed, "total": total}


def _print_eval_stats(label: str, results: list[dict], elapsed: float) -> None:
    """Print precision/recall/accuracy stats plus per-query results."""
    pos = [r for r in results if r["should_trigger"]]
    neg = [r for r in results if not r["should_trigger"]]
    tp = sum(r["triggers"] for r in pos)
    pos_runs = sum(r["runs"] for r in pos)
    fn = pos_runs - tp
    fp = sum(r["triggers"] for r in neg)
    neg_runs = sum(r["runs"] for r in neg)
    tn = neg_runs - fp
    total = tp + tn + fp + fn
    precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 1.0
    accuracy = (tp + tn) / total if total > 0 else 0.0
    print(
        f"{label}: {tp + tn}/{total} correct,"
        f" precision={precision:.0%} recall={recall:.0%}"
        f" accuracy={accuracy:.0%} ({elapsed:.1f}s)",
        file=sys.stderr,
    )
    for r in results:
        status = "PASS" if r["pass"] else "FAIL"
        rate_str = f"{r['triggers']}/{r['runs']}"
        expected = r["should_trigger"]
        query = r["query"][:60]
        detail = f"[{status}] rate={rate_str} expected={expected}: {query}"
        print(f"  {detail}", file=sys.stderr)


_STARTING_REPORT_HTML = (
    "<html><body><h1>Starting optimization loop...</h1>"
    "<meta http-equiv='refresh' content='5'></body></html>"
)


def split_eval_set(
    eval_set: list[dict],
    holdout: float,
    seed: int = 42,
) -> tuple[list[dict], list[dict]]:
    """Split eval set into train and test sets, stratified by should_trigger."""
    random.seed(seed)

    # Separate by should_trigger
    trigger = [e for e in eval_set if e["should_trigger"]]
    no_trigger = [e for e in eval_set if not e["should_trigger"]]

    # Shuffle each group
    random.shuffle(trigger)
    random.shuffle(no_trigger)

    # Calculate split points
    n_trigger_test = max(1, int(len(trigger) * holdout))
    n_no_trigger_test = max(1, int(len(no_trigger) * holdout))

    # Split
    test_set = trigger[:n_trigger_test] + no_trigger[:n_no_trigger_test]
    train_set = trigger[n_trigger_test:] + no_trigger[n_no_trigger_test:]

    return train_set, test_set


def _split_train_test(
    eval_set: list[dict], holdout: float, *, verbose: bool
) -> tuple[list[dict], list[dict]]:
    """Split into train/test sets, or keep everything for training."""
    if holdout <= 0:
        return list(eval_set), []
    train_set, test_set = split_eval_set(eval_set, holdout)
    if verbose:
        train_size = len(train_set)
        test_size = len(test_set)
        print(
            f"Split: {train_size} train, {test_size} test (holdout={holdout})",
            file=sys.stderr,
        )
    return train_set, test_set


def _history_entry(
    iteration: int,
    state: _LoopState,
    train_results: dict,
    test_results: dict | None,
) -> dict:
    """Build one history record for an iteration."""
    train_summary = train_results["summary"]
    test_summary = test_results["summary"] if test_results else None
    return {
        "iteration": iteration,
        "description": state.current_description,
        "train_passed": train_summary["passed"],
        "train_failed": train_summary["failed"],
        "train_total": train_summary["total"],
        "train_results": train_results["results"],
        "test_passed": test_summary["passed"] if test_summary else None,
        "test_failed": test_summary["failed"] if test_summary else None,
        "test_total": test_summary["total"] if test_summary else None,
        "test_results": test_results["results"] if test_results else None,
        # For backward compat with report generator
        "passed": train_summary["passed"],
        "failed": train_summary["failed"],
        "total": train_summary["total"],
        "results": train_results["results"],
    }


def _write_live_report(config: LoopConfig, state: _LoopState) -> None:
    """Write the in-progress HTML report when a report path is configured."""
    if config.live_report_path is None:
        return
    partial_output = {
        "original_description": state.original_description,
        "best_description": state.current_description,
        "best_score": "in progress",
        "iterations_run": len(state.history),
        "holdout": config.holdout,
        "train_size": len(state.train_set),
        "test_size": len(state.test_set),
        "history": state.history,
    }
    config.live_report_path.write_text(
        generate_html(partial_output, auto_refresh=True, skill_name=state.name),
    )


def _print_iteration_stats(
    train_results: dict, test_results: dict | None, eval_elapsed: float
) -> None:
    """Print train (and test, when present) stats for one iteration."""
    _print_eval_stats("Train", train_results["results"], eval_elapsed)
    if test_results is not None:
        _print_eval_stats("Test ", test_results["results"], 0)


def _run_iteration(
    config: LoopConfig, state: _LoopState, project_root: Path, iteration: int
) -> tuple[dict, dict | None]:
    """Evaluate once, record history, report, and print stats."""
    # Evaluate train + test together in one batch for parallelism
    all_queries = state.train_set + state.test_set
    t0 = time.time()
    all_results = run_eval(
        EvalParams(
            eval_set=all_queries,
            skill_name=state.name,
            description=state.current_description,
            num_workers=config.num_workers,
            timeout=config.timeout,
            project_root=project_root,
            runs_per_query=config.runs_per_query,
            trigger_threshold=config.trigger_threshold,
            model=config.model,
        )
    )
    eval_elapsed = time.time() - t0

    # Split results back into train/test by matching queries
    train_queries = {q["query"] for q in state.train_set}
    results = all_results["results"]
    train_list = [r for r in results if r["query"] in train_queries]
    test_list = [r for r in results if r["query"] not in train_queries]
    train_results = {"results": train_list, "summary": _summarize(train_list)}
    test_results = None
    if state.test_set:
        test_results = {"results": test_list, "summary": _summarize(test_list)}

    state.history.append(_history_entry(iteration, state, train_results, test_results))
    _write_live_report(config, state)
    if config.verbose:
        _print_iteration_stats(train_results, test_results, eval_elapsed)
    return train_results, test_results


def _improve_step(
    config: LoopConfig, state: _LoopState, train_results: dict, iteration: int
) -> str:
    """Propose an improved description from train results."""
    if config.verbose:
        print("\nImproving description...", file=sys.stderr)
    t0 = time.time()
    # Strip test scores from history so improvement model can't see them
    blinded_history = [
        {k: v for k, v in h.items() if not k.startswith("test_")} for h in state.history
    ]
    new_description = improve_description(
        ImproveParams(
            skill_name=state.name,
            skill_content=state.content,
            current_description=state.current_description,
            eval_results=train_results,
            history=blinded_history,
            model=config.model,
            log_dir=config.log_dir,
            iteration=iteration,
        )
    )
    if config.verbose:
        improve_elapsed = time.time() - t0
        print(
            f"Proposed ({improve_elapsed:.1f}s): {new_description}",
            file=sys.stderr,
        )
    return new_description


def _print_iteration_header(
    config: LoopConfig, state: _LoopState, iteration: int
) -> None:
    """Print the verbose per-iteration header."""
    if not config.verbose:
        return
    print(f"\n{'=' * 60}", file=sys.stderr)
    print(f"Iteration {iteration}/{config.max_iterations}", file=sys.stderr)
    print(f"Description: {state.current_description}", file=sys.stderr)
    print(f"{'=' * 60}", file=sys.stderr)


def _pick_best(state: _LoopState) -> tuple[dict, str]:
    """Pick the best iteration by TEST score (or train if no test set)."""
    if state.test_set:
        best = max(state.history, key=lambda h: h["test_passed"] or 0)
        best_score = f"{best['test_passed']}/{best['test_total']}"
    else:
        best = max(state.history, key=lambda h: h["train_passed"])
        best_score = f"{best['train_passed']}/{best['train_total']}"
    return best, best_score


def run_loop(config: LoopConfig) -> dict:
    """Run the eval + improvement loop."""
    project_root = find_project_root()
    name, original_description, content = parse_skill_md(config.skill_path)
    train_set, test_set = _split_train_test(
        config.eval_set, config.holdout, verbose=config.verbose
    )
    state = _LoopState(
        name=name,
        original_description=original_description,
        content=content,
        train_set=train_set,
        test_set=test_set,
        current_description=config.description_override or original_description,
    )
    exit_reason = "unknown"

    for iteration in range(1, config.max_iterations + 1):
        _print_iteration_header(config, state, iteration)

        train_results, _ = _run_iteration(config, state, project_root, iteration)

        if train_results["summary"]["failed"] == 0:
            exit_reason = f"all_passed (iteration {iteration})"
            if config.verbose:
                print(
                    f"\nAll train queries passed on iteration {iteration}!",
                    file=sys.stderr,
                )
            break

        if iteration == config.max_iterations:
            exit_reason = f"max_iterations ({config.max_iterations})"
            if config.verbose:
                print(
                    f"\nMax iterations reached ({config.max_iterations}).",
                    file=sys.stderr,
                )
            break

        # Improve the description based on train results
        state.current_description = _improve_step(
            config, state, train_results, iteration
        )

    best, best_score = _pick_best(state)

    if config.verbose:
        print(f"\nExit reason: {exit_reason}", file=sys.stderr)
        print(
            f"Best score: {best_score} (iteration {best['iteration']})",
            file=sys.stderr,
        )

    return {
        "exit_reason": exit_reason,
        "original_description": state.original_description,
        "best_description": best["description"],
        "best_score": best_score,
        "best_train_score": f"{best['train_passed']}/{best['train_total']}",
        "best_test_score": f"{best['test_passed']}/{best['test_total']}"
        if state.test_set
        else None,
        "final_description": state.current_description,
        "iterations_run": len(state.history),
        "holdout": config.holdout,
        "train_size": len(state.train_set),
        "test_size": len(state.test_set),
        "history": state.history,
    }


def _resolve_live_report_path(report: str, skill_path: Path) -> Path | None:
    """Set up the live report path, opening it so the user can watch."""
    if report == "none":
        return None
    if report == "auto":
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        live_report_path = (
            Path(tempfile.gettempdir())
            / f"skill_description_report_{skill_path.name}_{timestamp}.html"
        )
    else:
        live_report_path = Path(report)
    # Open the report immediately so the user can watch
    live_report_path.write_text(_STARTING_REPORT_HTML)
    webbrowser.open(str(live_report_path))
    return live_report_path


def _resolve_results_dir(
    results_dir_arg: str | None,
) -> tuple[Path | None, Path | None]:
    """Create the timestamped results dir before run_loop so logs can fit."""
    if not results_dir_arg:
        return None, None
    timestamp = time.strftime("%Y-%m-%d_%H%M%S")
    results_dir = Path(results_dir_arg) / timestamp
    results_dir.mkdir(parents=True, exist_ok=True)
    return results_dir, results_dir / "logs"


def main() -> None:
    """Run the eval + improvement loop from command-line arguments."""
    parser = argparse.ArgumentParser(description="Run eval + improve loop")
    parser.add_argument("--eval-set", required=True, help="Path to eval set JSON file")
    parser.add_argument("--skill-path", required=True, help="Path to skill directory")
    parser.add_argument(
        "--description",
        default=None,
        help="Override starting description",
    )
    parser.add_argument(
        "--num-workers",
        type=int,
        default=10,
        help="Number of parallel workers",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Timeout per query in seconds",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=5,
        help="Max improvement iterations",
    )
    parser.add_argument(
        "--runs-per-query",
        type=int,
        default=3,
        help="Number of runs per query",
    )
    parser.add_argument(
        "--trigger-threshold",
        type=float,
        default=0.5,
        help="Trigger rate threshold",
    )
    parser.add_argument(
        "--holdout",
        type=float,
        default=0.4,
        help="Fraction of eval set to hold out for testing (0 to disable)",
    )
    parser.add_argument("--model", required=True, help="Model for improvement")
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print progress to stderr",
    )
    parser.add_argument(
        "--report",
        default="auto",
        help=(
            "Generate HTML report at this path (default: 'auto' for temp "
            "file, 'none' to disable)"
        ),
    )
    parser.add_argument(
        "--results-dir",
        default=None,
        help=(
            "Save all outputs (results.json, report.html, log.txt) to a "
            "timestamped subdirectory here"
        ),
    )
    args = parser.parse_args()

    eval_set = json.loads(Path(args.eval_set).read_text())
    skill_path = Path(args.skill_path)

    if not (skill_path / "SKILL.md").exists():
        print(f"Error: No SKILL.md found at {skill_path}", file=sys.stderr)
        sys.exit(1)

    name, _, _ = parse_skill_md(skill_path)

    live_report_path = _resolve_live_report_path(args.report, skill_path)
    results_dir, log_dir = _resolve_results_dir(args.results_dir)

    output = run_loop(
        LoopConfig(
            eval_set=eval_set,
            skill_path=skill_path,
            description_override=args.description,
            num_workers=args.num_workers,
            timeout=args.timeout,
            max_iterations=args.max_iterations,
            runs_per_query=args.runs_per_query,
            trigger_threshold=args.trigger_threshold,
            holdout=args.holdout,
            model=args.model,
            verbose=args.verbose,
            live_report_path=live_report_path,
            log_dir=log_dir,
        )
    )

    # Save JSON output
    json_output = json.dumps(output, indent=2)
    print(json_output)
    if results_dir:
        (results_dir / "results.json").write_text(json_output)

    # Write final HTML report (without auto-refresh)
    if live_report_path:
        live_report_path.write_text(
            generate_html(output, auto_refresh=False, skill_name=name),
        )
        print(f"\nReport: {live_report_path}", file=sys.stderr)

    if results_dir and live_report_path:
        (results_dir / "report.html").write_text(
            generate_html(output, auto_refresh=False, skill_name=name),
        )

    if results_dir:
        print(f"Results saved to: {results_dir}", file=sys.stderr)


if __name__ == "__main__":
    main()
