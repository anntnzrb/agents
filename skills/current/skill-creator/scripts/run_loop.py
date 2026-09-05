#!/usr/bin/env -S uv run --script
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
from pathlib import Path
from typing import cast

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.generate_report import generate_html
from scripts.improve_description import improve_description
from scripts.run_eval import find_project_root, run_eval
from scripts.utils import parse_skill_md


def split_eval_set(
    eval_set: list[dict[str, object]],
    holdout: float,
    seed: int = 42,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Split eval set into train and test sets, stratified by should_trigger."""
    random.seed(seed)

    # Separate by should_trigger
    trigger = [e for e in eval_set if bool(e.get("should_trigger", False))]
    no_trigger = [e for e in eval_set if not bool(e.get("should_trigger", False))]

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


def _print_eval_stats(
    label: str,
    results: list[dict[str, object]],
    elapsed: float,
) -> None:
    """Print evaluation statistics to stderr."""
    pos = [r for r in results if bool(r.get("should_trigger", False))]
    neg = [r for r in results if not bool(r.get("should_trigger", False))]
    tp = sum(int(str(r.get("triggers", 0))) for r in pos)
    pos_runs = sum(int(str(r.get("runs", 0))) for r in pos)
    fn = pos_runs - tp
    fp = sum(int(str(r.get("triggers", 0))) for r in neg)
    neg_runs = sum(int(str(r.get("runs", 0))) for r in neg)
    tn = neg_runs - fp
    total = tp + tn + fp + fn
    precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 1.0
    accuracy = (tp + tn) / total if total > 0 else 0.0
    stats_msg = (
        f"{label}: {tp + tn}/{total} correct, "
        + f"precision={precision:.0%} recall={recall:.0%} "
        + f"accuracy={accuracy:.0%} ({elapsed:.1f}s)"
    )
    print(stats_msg, file=sys.stderr)
    for r in results:
        status = "PASS" if bool(r.get("pass", False)) else "FAIL"
        rate_str = f"{r.get('triggers', 0)}/{r.get('runs', 0)}"
        query_preview = str(r.get("query", ""))[:60]
        expected = r.get("should_trigger", False)
        print(
            f"  [{status}] rate={rate_str} expected={expected}: " + query_preview,
            file=sys.stderr,
        )


def _split_eval_results(
    all_results: dict[str, object],
    train_set: list[dict[str, object]],
    has_test_set: bool,
) -> tuple[dict[str, object], dict[str, object] | None]:
    """Split combined eval results into train and test result dictionaries."""
    train_queries_set = {str(q["query"]) for q in train_set}
    raw_results = cast("list[dict[str, object]]", all_results["results"])
    train_result_list = [r for r in raw_results if str(r["query"]) in train_queries_set]
    test_result_list = [
        r for r in raw_results if str(r["query"]) not in train_queries_set
    ]

    train_passed = sum(1 for r in train_result_list if bool(r.get("pass", False)))
    train_total = len(train_result_list)
    train_summary = {
        "passed": train_passed,
        "failed": train_total - train_passed,
        "total": train_total,
    }
    train_results: dict[str, object] = {
        "results": train_result_list,
        "summary": train_summary,
    }

    if has_test_set:
        test_passed = sum(1 for r in test_result_list if bool(r.get("pass", False)))
        test_total = len(test_result_list)
        test_summary = {
            "passed": test_passed,
            "failed": test_total - test_passed,
            "total": test_total,
        }
        test_results: dict[str, object] | None = {
            "results": test_result_list,
            "summary": test_summary,
        }
    else:
        test_results = None

    return train_results, test_results


def _build_history_entry(
    iteration: int,
    current_description: str,
    train_results: dict[str, object],
    test_results: dict[str, object] | None,
) -> dict[str, object]:
    """Build a history record for one iteration."""
    train_summary = cast("dict[str, int]", train_results["summary"])
    test_summary = (
        cast("dict[str, int]", test_results["summary"]) if test_results else None
    )
    test_res_list = (
        cast("list[dict[str, object]]", test_results["results"])
        if test_results
        else None
    )
    return {
        "iteration": iteration,
        "description": current_description,
        "train_passed": train_summary["passed"],
        "train_failed": train_summary["failed"],
        "train_total": train_summary["total"],
        "train_results": train_results["results"],
        "test_passed": test_summary["passed"] if test_summary else None,
        "test_failed": test_summary["failed"] if test_summary else None,
        "test_total": test_summary["total"] if test_summary else None,
        "test_results": test_res_list,
        # For backward compat with report generator
        "passed": train_summary["passed"],
        "failed": train_summary["failed"],
        "total": train_summary["total"],
        "results": train_results["results"],
    }


def _update_live_report(
    live_report_path: Path,
    partial_output: dict[str, object],
    skill_name: str,
) -> None:
    """Write live report HTML to disk."""
    _ = live_report_path.write_text(
        generate_html(partial_output, auto_refresh=True, skill_name=skill_name),
        encoding="utf-8",
    )


def _find_best_result(
    history: list[dict[str, object]],
    has_test_set: bool,
) -> tuple[dict[str, object], str]:
    """Find the best iteration by test score (or train score if no test set)."""
    if has_test_set:
        best = max(
            history,
            key=lambda h: int(str(h.get("test_passed") or 0)),
        )
        best_score = f"{best['test_passed']}/{best['test_total']}"
    else:
        best = max(
            history,
            key=lambda h: int(str(h.get("train_passed") or 0)),
        )
        best_score = f"{best['train_passed']}/{best['train_total']}"
    return best, best_score


def _prepare_eval_sets(
    eval_set: list[dict[str, object]],
    holdout: float,
    verbose: bool,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Prepare train and test sets according to holdout fraction."""
    if holdout > 0:
        train_set, test_set = split_eval_set(eval_set, holdout)
        if verbose:
            split_msg = (
                f"Split: {len(train_set)} train, "
                + f"{len(test_set)} test (holdout={holdout})"
            )
            print(split_msg, file=sys.stderr)
        return train_set, test_set
    return eval_set, []


def _run_single_iteration(  # noqa: PLR0913, PLR0917 - Preserved helper signature for iteration execution
    iteration: int,
    max_iterations: int,
    current_description: str,
    skill_name: str,
    train_set: list[dict[str, object]],
    test_set: list[dict[str, object]],
    num_workers: int,
    timeout: int,
    project_root: Path,
    runs_per_query: int,
    trigger_threshold: float,
    model: str,
    verbose: bool,
) -> tuple[dict[str, object], dict[str, object] | None]:
    """Execute one evaluation iteration over train and test sets."""
    if verbose:
        print(f"\n{'=' * 60}", file=sys.stderr)
        print(f"Iteration {iteration}/{max_iterations}", file=sys.stderr)
        print(f"Description: {current_description}", file=sys.stderr)
        print(f"{'=' * 60}", file=sys.stderr)

    all_queries = train_set + test_set
    t0 = time.time()
    all_results = run_eval(
        eval_set=all_queries,
        skill_name=skill_name,
        description=current_description,
        num_workers=num_workers,
        timeout=timeout,
        project_root=project_root,
        runs_per_query=runs_per_query,
        trigger_threshold=trigger_threshold,
        model=model,
    )
    eval_elapsed = time.time() - t0

    train_results, test_results = _split_eval_results(
        all_results, train_set, bool(test_set)
    )

    if verbose:
        train_res_list = cast("list[dict[str, object]]", train_results["results"])
        _print_eval_stats("Train", train_res_list, eval_elapsed)
        if test_results:
            test_res_list = cast("list[dict[str, object]]", test_results["results"])
            _print_eval_stats("Test ", test_res_list, 0.0)

    return train_results, test_results


def _run_iteration_improvement(  # noqa: PLR0913, PLR0917 - Preserved helper signature for improvement step
    skill_name: str,
    skill_content: str,
    current_description: str,
    train_results: dict[str, object],
    history: list[dict[str, object]],
    model: str,
    log_dir: Path | None,
    iteration: int,
    verbose: bool,
) -> str:
    """Improve description based on train results and log elapsed time."""
    if verbose:
        print("\nImproving description...", file=sys.stderr)

    t0 = time.time()
    blinded_history: list[dict[str, object]] = [
        {k: v for k, v in h.items() if not k.startswith("test_")} for h in history
    ]
    new_description = improve_description(
        skill_name=skill_name,
        skill_content=skill_content,
        current_description=current_description,
        eval_results=train_results,
        history=blinded_history,
        model=model,
        log_dir=log_dir,
        iteration=iteration,
    )
    improve_elapsed = time.time() - t0

    if verbose:
        print(
            f"Proposed ({improve_elapsed:.1f}s): {new_description}",
            file=sys.stderr,
        )
    return new_description


def _check_exit_condition(
    train_summary: dict[str, int],
    iteration: int,
    max_iterations: int,
    verbose: bool,
) -> str | None:
    """Check if the loop should terminate."""
    if train_summary["failed"] == 0:
        if verbose:
            print(
                f"\nAll train queries passed on iteration {iteration}!",
                file=sys.stderr,
            )
        return f"all_passed (iteration {iteration})"
    if iteration == max_iterations:
        if verbose:
            print(f"\nMax iterations reached ({max_iterations}).", file=sys.stderr)
        return f"max_iterations ({max_iterations})"
    return None


def run_loop(  # noqa: PLR0913, PLR0917 - Preserved public function signature
    eval_set: list[dict[str, object]],
    skill_path: Path,
    description_override: str | None,
    num_workers: int,
    timeout: int,
    max_iterations: int,
    runs_per_query: int,
    trigger_threshold: float,
    holdout: float,
    model: str,
    verbose: bool,
    live_report_path: Path | None = None,
    log_dir: Path | None = None,
) -> dict[str, object]:
    """Run the eval + improvement loop."""
    project_root = find_project_root()
    name, original_description, content = parse_skill_md(skill_path)
    current_description = description_override or original_description

    train_set, test_set = _prepare_eval_sets(eval_set, holdout, verbose)

    history: list[dict[str, object]] = []
    exit_reason = "unknown"

    for iteration in range(1, max_iterations + 1):
        train_results, test_results = _run_single_iteration(
            iteration=iteration,
            max_iterations=max_iterations,
            current_description=current_description,
            skill_name=name,
            train_set=train_set,
            test_set=test_set,
            num_workers=num_workers,
            timeout=timeout,
            project_root=project_root,
            runs_per_query=runs_per_query,
            trigger_threshold=trigger_threshold,
            model=model,
            verbose=verbose,
        )
        history.append(
            _build_history_entry(
                iteration, current_description, train_results, test_results
            )
        )

        if live_report_path:
            partial_output: dict[str, object] = {
                "original_description": original_description,
                "best_description": current_description,
                "best_score": "in progress",
                "iterations_run": len(history),
                "holdout": holdout,
                "train_size": len(train_set),
                "test_size": len(test_set),
                "history": history,
            }
            _update_live_report(
                live_report_path=live_report_path,
                partial_output=partial_output,
                skill_name=name,
            )

        train_summary = cast("dict[str, int]", train_results["summary"])
        term_reason = _check_exit_condition(
            train_summary, iteration, max_iterations, verbose
        )
        if term_reason is not None:
            exit_reason = term_reason
            break

        current_description = _run_iteration_improvement(
            skill_name=name,
            skill_content=content,
            current_description=current_description,
            train_results=train_results,
            history=history,
            model=model,
            log_dir=log_dir,
            iteration=iteration,
            verbose=verbose,
        )

    best, best_score = _find_best_result(history, bool(test_set))

    if verbose:
        print(f"\nExit reason: {exit_reason}", file=sys.stderr)
        print(
            f"Best score: {best_score} (iteration {best['iteration']})",
            file=sys.stderr,
        )

    return {
        "exit_reason": exit_reason,
        "original_description": original_description,
        "best_description": best["description"],
        "best_score": best_score,
        "best_train_score": f"{best['train_passed']}/{best['train_total']}",
        "best_test_score": f"{best['test_passed']}/{best['test_total']}"
        if test_set
        else None,
        "final_description": current_description,
        "iterations_run": len(history),
        "holdout": holdout,
        "train_size": len(train_set),
        "test_size": len(test_set),
        "history": history,
    }


def _setup_report_path(report_arg: str, skill_name: str) -> Path | None:
    """Set up live report path and initialize report HTML."""
    if report_arg == "none":
        return None
    if report_arg == "auto":
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        live_report_path = (
            Path(tempfile.gettempdir())
            / f"skill_description_report_{skill_name}_{timestamp}.html"
        )
    else:
        live_report_path = Path(report_arg)
    init_html = (
        "<html><body><h1>Starting optimization loop...</h1>"
        + "<meta http-equiv='refresh' content='5'></body></html>"
    )
    _ = live_report_path.write_text(init_html, encoding="utf-8")
    _ = webbrowser.open(str(live_report_path))
    return live_report_path


def _save_loop_outputs(
    output: dict[str, object],
    skill_name: str,
    live_report_path: Path | None,
    results_dir: Path | None,
) -> None:
    """Save JSON and HTML output reports to disk."""
    json_output = json.dumps(output, indent=2)
    print(json_output)
    if results_dir:
        _ = (results_dir / "results.json").write_text(json_output, encoding="utf-8")

    if live_report_path:
        _ = live_report_path.write_text(
            generate_html(output, auto_refresh=False, skill_name=skill_name),
            encoding="utf-8",
        )
        print(f"\nReport: {live_report_path}", file=sys.stderr)

    if results_dir and live_report_path:
        _ = (results_dir / "report.html").write_text(
            generate_html(output, auto_refresh=False, skill_name=skill_name),
            encoding="utf-8",
        )

    if results_dir:
        print(f"Results saved to: {results_dir}", file=sys.stderr)


def main() -> None:
    """Run eval + improve loop CLI."""
    parser = argparse.ArgumentParser(description="Run eval + improve loop")
    _ = parser.add_argument(
        "--eval-set", required=True, help="Path to eval set JSON file"
    )
    _ = parser.add_argument(
        "--skill-path", required=True, help="Path to skill directory"
    )
    _ = parser.add_argument(
        "--description",
        default=None,
        help="Override starting description",
    )
    _ = parser.add_argument(
        "--num-workers",
        type=int,
        default=10,
        help="Number of parallel workers",
    )
    _ = parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Timeout per query in seconds",
    )
    _ = parser.add_argument(
        "--max-iterations",
        type=int,
        default=5,
        help="Max improvement iterations",
    )
    _ = parser.add_argument(
        "--runs-per-query",
        type=int,
        default=3,
        help="Number of runs per query",
    )
    _ = parser.add_argument(
        "--trigger-threshold",
        type=float,
        default=0.5,
        help="Trigger rate threshold",
    )
    _ = parser.add_argument(
        "--holdout",
        type=float,
        default=0.4,
        help="Fraction of eval set to hold out for testing (0 to disable)",
    )
    _ = parser.add_argument("--model", required=True, help="Model for improvement")
    _ = parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print progress to stderr",
    )
    _ = parser.add_argument(
        "--report",
        default="auto",
        help=(
            "Generate HTML report at this path "
            + "(default: 'auto' for temp file, 'none' to disable)"
        ),
    )
    _ = parser.add_argument(
        "--results-dir",
        default=None,
        help=(
            "Save all outputs (results.json, report.html, log.txt) "
            + "to a timestamped subdirectory here"
        ),
    )
    args_map = cast("dict[str, object]", vars(parser.parse_args()))

    eval_set_path = Path(str(args_map["eval_set"]))
    raw_eval_set = cast("object", json.loads(eval_set_path.read_text(encoding="utf-8")))
    if not isinstance(raw_eval_set, list):
        msg = "Eval set must be a JSON list"
        raise TypeError(msg)
    eval_set = cast("list[dict[str, object]]", raw_eval_set)
    skill_path = Path(str(args_map["skill_path"]))

    if not (skill_path / "SKILL.md").exists():
        print(f"Error: No SKILL.md found at {skill_path}", file=sys.stderr)
        sys.exit(1)

    name, _, _ = parse_skill_md(skill_path)

    report_arg = str(args_map["report"])
    live_report_path = _setup_report_path(report_arg, skill_path.name)

    results_dir_arg = (
        str(args_map["results_dir"])
        if args_map.get("results_dir") is not None
        else None
    )
    if results_dir_arg:
        timestamp = time.strftime("%Y-%m-%d_%H%M%S")
        results_dir = Path(results_dir_arg) / timestamp
        results_dir.mkdir(parents=True, exist_ok=True)
    else:
        results_dir = None

    log_dir = results_dir / "logs" if results_dir else None

    description_override = (
        str(args_map["description"])
        if args_map.get("description") is not None
        else None
    )
    num_workers = int(str(args_map["num_workers"]))
    timeout = int(str(args_map["timeout"]))
    max_iterations = int(str(args_map["max_iterations"]))
    runs_per_query = int(str(args_map["runs_per_query"]))
    trigger_threshold = float(str(args_map["trigger_threshold"]))
    holdout = float(str(args_map["holdout"]))
    model = str(args_map["model"])
    verbose = bool(args_map.get("verbose", False))

    output = run_loop(
        eval_set=eval_set,
        skill_path=skill_path,
        description_override=description_override,
        num_workers=num_workers,
        timeout=timeout,
        max_iterations=max_iterations,
        runs_per_query=runs_per_query,
        trigger_threshold=trigger_threshold,
        holdout=holdout,
        model=model,
        verbose=verbose,
        live_report_path=live_report_path,
        log_dir=log_dir,
    )

    _save_loop_outputs(output, name, live_report_path, results_dir)


if __name__ == "__main__":
    main()
