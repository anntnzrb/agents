#!/usr/bin/env -S uv run --script
# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""Aggregate individual run results into benchmark summary statistics.

Reads grading.json files from run directories and produces:
- run_summary with mean, stddev, min, max for each metric
- delta between with_skill and without_skill configurations

Usage:
    python aggregate_benchmark.py <benchmark_dir>

Example:
    python aggregate_benchmark.py benchmarks/2026-01-15T10-30-00/

The script supports two directory layouts:

    Workspace layout (from skill-creator iterations):
    <benchmark_dir>/
    └── eval-N/
        ├── with_skill/
        │   ├── run-1/grading.json
        │   └── run-2/grading.json
        └── without_skill/
            ├── run-1/grading.json
            └── run-2/grading.json

    Legacy layout (with runs/ subdirectory):
    <benchmark_dir>/
    └── runs/
        └── eval-N/
            ├── with_skill/
            │   └── run-1/grading.json
            └── without_skill/
                └── run-1/grading.json

"""

import argparse
import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final, TypedDict, TypeIs

if TYPE_CHECKING:
    from collections.abc import Callable


class MetricStats(TypedDict):
    """Statistical summary of a single metric."""

    mean: float
    stddev: float
    min: float
    max: float


class ConfigSummary(TypedDict):
    """Aggregate statistics across runs for a single configuration."""

    pass_rate: MetricStats
    time_seconds: MetricStats
    tokens: MetricStats


class DeltaSummary(TypedDict):
    """Difference in metrics between primary and baseline configurations."""

    pass_rate: str
    time_seconds: str
    tokens: str


class RunResult(TypedDict):
    """Extracted data from a single evaluation run."""

    eval_id: object
    run_number: int
    pass_rate: float
    passed: int
    failed: int
    total: int
    time_seconds: float
    tokens: int
    tool_calls: int
    errors: int
    expectations: list[object]
    notes: list[str]


class BenchmarkMetadata(TypedDict):
    """Metadata recorded in the benchmark summary."""

    skill_name: str
    skill_path: str
    executor_model: str
    analyzer_model: str
    timestamp: str
    evals_run: list[str]
    runs_per_configuration: int


class BenchmarkData(TypedDict):
    """Complete structure of benchmark.json."""

    metadata: BenchmarkMetadata
    runs: list[dict[str, object]]
    run_summary: dict[str, object]
    notes: list[str]


def _load_json(fp: Path) -> object:
    fn: Callable[..., object] = json.load
    with fp.open(encoding="utf-8") as f:
        return fn(f)


def _is_str_dict(val: object) -> TypeIs[dict[str, object]]:
    return isinstance(val, dict)


def _is_object_list(val: object) -> TypeIs[list[object]]:
    return isinstance(val, list)


def _to_float(val: object, default: float = 0.0) -> float:
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        try:
            return float(val)
        except ValueError:
            return default
    return default


def calculate_stats(values: list[float]) -> MetricStats:
    """Calculate mean, stddev, min, max for a list of values."""
    if not values:
        return {"mean": 0.0, "stddev": 0.0, "min": 0.0, "max": 0.0}

    n = len(values)
    mean = sum(values) / n

    if n > 1:
        variance = sum((x - mean) ** 2 for x in values) / (n - 1)
        stddev = math.sqrt(variance)
    else:
        stddev = 0.0

    return {
        "mean": round(mean, 4),
        "stddev": round(stddev, 4),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
    }


def _resolve_search_dir(benchmark_dir: Path) -> Path | None:
    """Find the directory holding eval-N/ runs, supporting both layouts."""
    runs_dir = benchmark_dir / "runs"
    if runs_dir.exists():
        return runs_dir
    if list(benchmark_dir.glob("eval-*")):
        return benchmark_dir
    print(
        f"No eval directories found in {benchmark_dir} or {benchmark_dir / 'runs'}",
    )
    return None


def _read_eval_id(eval_dir: Path, eval_idx: int) -> object:
    """Read the eval id from metadata, falling back to name or index."""
    metadata_path = eval_dir / "eval_metadata.json"
    if metadata_path.exists():
        try:
            raw = _load_json(metadata_path)
        except json.JSONDecodeError, OSError:
            return eval_idx
        if _is_str_dict(raw):
            eval_id = raw.get("eval_id")
            if eval_id is not None:
                return eval_id
        return eval_idx
    try:
        return int(eval_dir.name.split("-")[1])
    except IndexError, ValueError:
        return eval_idx


def _extract_timing(timing_obj: dict[str, object], run_dir: Path) -> tuple[float, int]:
    """Extract (duration_seconds, tokens) from timing dict and optional timing.json."""
    raw_dur = timing_obj.get("total_duration_seconds", 0.0)
    time_seconds = _to_float(raw_dur)
    tokens = 0

    timing_file = run_dir / "timing.json"
    if time_seconds == 0.0 and timing_file.exists():
        try:
            raw_timing = _load_json(timing_file)
            if _is_str_dict(raw_timing):
                time_seconds = _to_float(raw_timing.get("total_duration_seconds", 0.0))
                raw_tok = raw_timing.get("total_tokens", 0)
                if isinstance(raw_tok, int):
                    tokens = raw_tok
        except json.JSONDecodeError, OSError:
            pass
    return time_seconds, tokens


def _extract_notes(notes_summary_obj: dict[str, object]) -> list[str]:
    """Extract list of notes from user_notes_summary."""
    notes: list[str] = []
    for key in ("uncertainties", "needs_review", "workarounds"):
        vals = notes_summary_obj.get(key, [])
        if _is_object_list(vals):
            notes.extend(str(v) for v in vals)
    return notes


def _read_run(run_dir: Path, eval_id: object) -> RunResult | None:
    """Read one run directory; None when grading data is missing/invalid."""
    try:
        run_number = int(run_dir.name.split("-")[1])
    except IndexError, ValueError:
        run_number = 0

    grading_file = run_dir / "grading.json"
    if not grading_file.exists():
        print(f"Warning: grading.json not found in {run_dir}")
        return None
    try:
        raw_grading = _load_json(grading_file)
    except (json.JSONDecodeError, OSError) as e:
        print(f"Warning: Invalid JSON in {grading_file}: {e}")
        return None

    if not _is_str_dict(raw_grading):
        return None

    summary_obj = raw_grading.get("summary")
    summary: dict[str, object] = summary_obj if _is_str_dict(summary_obj) else {}

    pass_rate = _to_float(summary.get("pass_rate", 0.0))

    raw_passed = summary.get("passed", 0)
    passed = int(raw_passed) if isinstance(raw_passed, int) else 0

    raw_failed = summary.get("failed", 0)
    failed = int(raw_failed) if isinstance(raw_failed, int) else 0

    raw_total = summary.get("total", 0)
    total = int(raw_total) if isinstance(raw_total, int) else 0

    timing_obj = raw_grading.get("timing")
    timing: dict[str, object] = timing_obj if _is_str_dict(timing_obj) else {}
    time_seconds, tokens = _extract_timing(timing, run_dir)

    metrics_obj = raw_grading.get("execution_metrics")
    metrics: dict[str, object] = metrics_obj if _is_str_dict(metrics_obj) else {}

    raw_tc = metrics.get("total_tool_calls", 0)
    tool_calls = int(raw_tc) if isinstance(raw_tc, int) else 0

    if tokens == 0:
        raw_chars = metrics.get("output_chars", 0)
        tokens = int(raw_chars) if isinstance(raw_chars, int) else 0

    raw_err = metrics.get("errors_encountered", 0)
    errors = int(raw_err) if isinstance(raw_err, int) else 0

    raw_expectations = raw_grading.get("expectations", [])
    expectations: list[object] = (
        raw_expectations if _is_object_list(raw_expectations) else []
    )
    for exp in expectations:
        if isinstance(exp, dict) and ("text" not in exp or "passed" not in exp):
            msg = "".join(
                (
                    f"Warning: expectation in {grading_file} missing ",
                    f"required fields (text, passed, evidence): {exp}",
                )
            )
            print(msg)

    notes_summary_obj = raw_grading.get("user_notes_summary")
    notes_summary: dict[str, object] = (
        notes_summary_obj if _is_str_dict(notes_summary_obj) else {}
    )
    notes = _extract_notes(notes_summary)

    return {
        "eval_id": eval_id,
        "run_number": run_number,
        "pass_rate": pass_rate,
        "passed": passed,
        "failed": failed,
        "total": total,
        "time_seconds": time_seconds,
        "tokens": tokens,
        "tool_calls": tool_calls,
        "errors": errors,
        "expectations": expectations,
        "notes": notes,
    }


def load_run_results(benchmark_dir: Path) -> dict[str, list[RunResult]]:
    """Load all run results from a benchmark directory.

    Returns dict keyed by config name (e.g. "with_skill"/"without_skill",
    or "new_skill"/"old_skill"), each containing a list of run results.
    """
    search_dir = _resolve_search_dir(benchmark_dir)
    if search_dir is None:
        return {}

    results: dict[str, list[RunResult]] = {}

    for eval_idx, eval_dir in enumerate(sorted(search_dir.glob("eval-*"))):
        eval_id = _read_eval_id(eval_dir, eval_idx)

        # Discover config directories dynamically rather than hardcoding names
        for config_dir in sorted(eval_dir.iterdir()):
            if not config_dir.is_dir():
                continue
            # Skip non-config directories (inputs, outputs, etc.)
            if not list(config_dir.glob("run-*")):
                continue
            config = config_dir.name
            if config not in results:
                results[config] = []

            for run_dir in sorted(config_dir.glob("run-*")):
                result = _read_run(run_dir, eval_id)
                if result is not None:
                    results[config].append(result)

    return results


_MIN_DELTA_CONFIGS: Final[int] = 2


def _mean_diff(
    primary: dict[str, object],
    baseline: dict[str, object],
    metric: str,
) -> float:
    """Return the difference of mean metric values between two summaries."""
    prim_metric = primary.get(metric)
    prim_mean = _to_float(prim_metric.get("mean")) if _is_str_dict(prim_metric) else 0.0

    base_metric = baseline.get(metric)
    base_mean = _to_float(base_metric.get("mean")) if _is_str_dict(base_metric) else 0.0

    return prim_mean - base_mean


def _pct_range(mean: float, stddev: float) -> str:
    """Format a mean ± stddev cell as whole-percent values."""
    return f"{mean * 100:.0f}% ± {stddev * 100:.0f}%"


def aggregate_results(
    results: dict[str, list[RunResult]],
) -> dict[str, object]:
    """Aggregate run results into summary statistics.

    Returns run_summary with stats for each configuration and delta.
    """
    run_summary: dict[str, object] = {}
    configs = list(results.keys())

    for config in configs:
        runs = results.get(config, [])

        if not runs:
            run_summary[config] = ConfigSummary(
                pass_rate={"mean": 0.0, "stddev": 0.0, "min": 0.0, "max": 0.0},
                time_seconds={"mean": 0.0, "stddev": 0.0, "min": 0.0, "max": 0.0},
                tokens={"mean": 0.0, "stddev": 0.0, "min": 0.0, "max": 0.0},
            )
            continue

        pass_rates = [r["pass_rate"] for r in runs]
        times = [r["time_seconds"] for r in runs]
        tokens = [float(r.get("tokens", 0)) for r in runs]

        run_summary[config] = ConfigSummary(
            pass_rate=calculate_stats(pass_rates),
            time_seconds=calculate_stats(times),
            tokens=calculate_stats(tokens),
        )

    # Calculate delta between the first two configs (if two exist)
    primary_summary: dict[str, object] = {}
    baseline_summary: dict[str, object] = {}
    if len(configs) >= _MIN_DELTA_CONFIGS:
        p_obj = run_summary.get(configs[0])
        if _is_str_dict(p_obj):
            primary_summary = p_obj
        b_obj = run_summary.get(configs[1])
        if _is_str_dict(b_obj):
            baseline_summary = b_obj
    elif configs:
        p_obj = run_summary.get(configs[0])
        if _is_str_dict(p_obj):
            primary_summary = p_obj

    delta_pass_rate = _mean_diff(primary_summary, baseline_summary, "pass_rate")
    delta_time = _mean_diff(primary_summary, baseline_summary, "time_seconds")
    delta_tokens = _mean_diff(primary_summary, baseline_summary, "tokens")

    run_summary["delta"] = DeltaSummary(
        pass_rate=f"{delta_pass_rate:+.2f}",
        time_seconds=f"{delta_time:+.1f}",
        tokens=f"{delta_tokens:+.0f}",
    )

    return run_summary


def generate_benchmark(
    benchmark_dir: Path,
    skill_name: str = "",
    skill_path: str = "",
) -> BenchmarkData:
    """Generate complete benchmark.json from run results."""
    results = load_run_results(benchmark_dir)
    run_summary = aggregate_results(results)

    # Build runs array for benchmark.json
    runs: list[dict[str, object]] = []
    for config, config_runs in results.items():
        for result in config_runs:
            runs.append(
                {
                    "eval_id": result["eval_id"],
                    "configuration": config,
                    "run_number": result["run_number"],
                    "result": {
                        "pass_rate": result["pass_rate"],
                        "passed": result["passed"],
                        "failed": result["failed"],
                        "total": result["total"],
                        "time_seconds": result["time_seconds"],
                        "tokens": result.get("tokens", 0),
                        "tool_calls": result.get("tool_calls", 0),
                        "errors": result.get("errors", 0),
                    },
                    "expectations": result["expectations"],
                    "notes": result["notes"],
                },
            )

    # Determine eval IDs from results
    eval_ids: list[str] = sorted(
        {str(r["eval_id"]) for config_runs in results.values() for r in config_runs}
    )

    return {
        "metadata": {
            "skill_name": skill_name or "<skill-name>",
            "skill_path": skill_path or "<path/to/skill>",
            "executor_model": "<model-name>",
            "analyzer_model": "<model-name>",
            "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "evals_run": eval_ids,
            "runs_per_configuration": 3,
        },
        "runs": runs,
        "run_summary": run_summary,
        "notes": [],  # To be filled by analyzer
    }


def generate_markdown(benchmark: BenchmarkData) -> str:
    """Generate human-readable benchmark.md from benchmark data."""
    metadata = benchmark["metadata"]
    run_summary = benchmark["run_summary"]

    # Determine config names (excluding "delta")
    configs = [k for k in run_summary if k != "delta"]
    config_a = configs[0] if configs else "config_a"
    config_b = configs[1] if len(configs) >= _MIN_DELTA_CONFIGS else "config_b"
    label_a = config_a.replace("_", " ").title()
    label_b = config_b.replace("_", " ").title()

    lines = [
        f"# Skill Benchmark: {metadata['skill_name']}",
        f"**Model**: {metadata['executor_model']}",
        f"**Date**: {metadata['timestamp']}",
        (
            f"**Evals**: {', '.join(map(str, metadata['evals_run']))}"
            f" ({metadata['runs_per_configuration']} runs each per configuration)"
        ),
        "",
        "## Summary",
        "",
        f"| Metric | {label_a} | {label_b} | Delta |",
        "|--------|------------|---------------|-------|",
    ]

    a_obj = run_summary.get(config_a, {})
    a_summary: dict[str, object] = a_obj if _is_str_dict(a_obj) else {}

    b_obj = run_summary.get(config_b, {})
    b_summary: dict[str, object] = b_obj if _is_str_dict(b_obj) else {}

    delta_obj = run_summary.get("delta", {})
    delta: dict[str, object] = delta_obj if _is_str_dict(delta_obj) else {}

    # Format pass rate
    a_pr_obj = a_summary.get("pass_rate")
    a_pr = a_pr_obj if _is_str_dict(a_pr_obj) else {}
    b_pr_obj = b_summary.get("pass_rate")
    b_pr = b_pr_obj if _is_str_dict(b_pr_obj) else {}
    a_rate = _pct_range(_to_float(a_pr.get("mean")), _to_float(a_pr.get("stddev")))
    b_rate = _pct_range(_to_float(b_pr.get("mean")), _to_float(b_pr.get("stddev")))
    pass_delta = str(delta.get("pass_rate", "-"))
    lines.append(f"| Pass Rate | {a_rate} | {b_rate} | {pass_delta} |")

    # Format time
    a_time_obj = a_summary.get("time_seconds")
    a_time = a_time_obj if _is_str_dict(a_time_obj) else {}
    b_time_obj = b_summary.get("time_seconds")
    b_time = b_time_obj if _is_str_dict(b_time_obj) else {}
    a_dur = (
        f"{_to_float(a_time.get('mean')):.1f}s ± {_to_float(a_time.get('stddev')):.1f}s"
    )
    b_dur = (
        f"{_to_float(b_time.get('mean')):.1f}s ± {_to_float(b_time.get('stddev')):.1f}s"
    )
    time_delta = str(delta.get("time_seconds", "-"))
    lines.append(f"| Time | {a_dur} | {b_dur} | {time_delta}s |")

    # Format tokens
    a_tok_obj = a_summary.get("tokens")
    a_tokens = a_tok_obj if _is_str_dict(a_tok_obj) else {}
    b_tok_obj = b_summary.get("tokens")
    b_tokens = b_tok_obj if _is_str_dict(b_tok_obj) else {}
    a_tok = (
        f"{_to_float(a_tokens.get('mean')):.0f} ± "
        f"{_to_float(a_tokens.get('stddev')):.0f}"
    )
    b_tok = (
        f"{_to_float(b_tokens.get('mean')):.0f} ± "
        f"{_to_float(b_tokens.get('stddev')):.0f}"
    )
    tok_delta = str(delta.get("tokens", "-"))
    lines.append(f"| Tokens | {a_tok} | {b_tok} | {tok_delta} |")

    # Notes section
    if benchmark.get("notes"):
        lines.extend(["", "## Notes", ""])
        for note in benchmark["notes"]:
            lines.append(f"- {note}")

    return "\n".join(lines)


def main() -> None:
    """Aggregate benchmark run results from command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Aggregate benchmark run results into summary statistics",
    )
    _ = parser.add_argument(
        "benchmark_dir",
        type=Path,
        help="Path to the benchmark directory",
    )
    _ = parser.add_argument(
        "--skill-name",
        default="",
        help="Name of the skill being benchmarked",
    )
    _ = parser.add_argument(
        "--skill-path",
        default="",
        help="Path to the skill being benchmarked",
    )
    _ = parser.add_argument(
        "--output",
        "-o",
        type=Path,
        help=(
            "Output path for benchmark.json (default: <benchmark_dir>/benchmark.json)"
        ),
    )

    ns = parser.parse_args()

    raw_dir = getattr(ns, "benchmark_dir", None)
    if not isinstance(raw_dir, Path):
        print("Error: missing benchmark directory", file=sys.stderr)
        sys.exit(1)
    benchmark_dir: Path = raw_dir
    if not benchmark_dir.exists():
        print(f"Directory not found: {benchmark_dir}")
        sys.exit(1)

    skill_name = str(getattr(ns, "skill_name", ""))
    skill_path = str(getattr(ns, "skill_path", ""))

    # Generate benchmark
    benchmark = generate_benchmark(benchmark_dir, skill_name, skill_path)

    # Determine output paths
    out_arg = getattr(ns, "output", None)
    output_json: Path = (
        out_arg if isinstance(out_arg, Path) else (benchmark_dir / "benchmark.json")
    )
    output_md = output_json.with_suffix(".md")

    # Write benchmark.json
    with output_json.open("w", encoding="utf-8") as f:
        json.dump(benchmark, f, indent=2)
    print(f"Generated: {output_json}")

    # Write benchmark.md
    markdown = generate_markdown(benchmark)
    with output_md.open("w", encoding="utf-8") as f:
        _ = f.write(markdown)
    print(f"Generated: {output_md}")

    # Print summary
    run_summary = benchmark["run_summary"]
    configs = [k for k in run_summary if k != "delta"]
    delta_obj = run_summary.get("delta")
    delta: dict[str, object] = delta_obj if _is_str_dict(delta_obj) else {}

    print("\nSummary:")
    for config in configs:
        cfg_obj = run_summary.get(config)
        pr_val: float = 0.0
        if _is_str_dict(cfg_obj):
            pr_obj = cfg_obj.get("pass_rate")
            if _is_str_dict(pr_obj):
                pr_val = _to_float(pr_obj.get("mean"))
        label = config.replace("_", " ").title()
        print(f"  {label}: {pr_val * 100:.1f}% pass rate")
    print(f"  Delta:         {delta.get('pass_rate', '-')}")


if __name__ == "__main__":
    main()
