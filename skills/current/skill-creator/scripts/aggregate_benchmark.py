#!/usr/bin/env -S uv run --script
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
import contextlib
import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

MIN_CONFIGS_FOR_DELTA = 2

type RunResult = dict[str, object]
type RunSummary = dict[str, dict[str, object]]
type BenchmarkData = dict[str, object]


def _safe_float(val: object, default: float = 0.0) -> float:
    """Extract float safely from an untyped object."""
    if isinstance(val, (int, float)):
        return float(val)
    return default


def _safe_int(val: object, default: int = 0) -> int:
    """Extract int safely from an untyped object."""
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        return int(val)
    return default


def _safe_dict(val: object) -> dict[str, object]:
    """Extract dict safely from an untyped object."""
    if isinstance(val, dict):
        return cast("dict[str, object]", val)
    return {}


def _safe_list(val: object) -> list[object]:
    """Extract list safely from an untyped object."""
    if isinstance(val, list):
        return cast("list[object]", val)
    return []


def calculate_stats(values: list[float]) -> dict[str, float]:
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
    """Determine the root directory to search for eval directories."""
    runs_dir = benchmark_dir / "runs"
    if runs_dir.exists():
        return runs_dir
    if list(benchmark_dir.glob("eval-*")):
        return benchmark_dir
    print(
        f"No eval directories found in {benchmark_dir} or {benchmark_dir / 'runs'}",
    )
    return None


def _get_eval_id(eval_dir: Path, eval_idx: int) -> int:
    """Extract eval ID from metadata or directory name fallback."""
    metadata_path = eval_dir / "eval_metadata.json"
    if metadata_path.exists():
        with contextlib.suppress(json.JSONDecodeError, OSError, TypeError, ValueError):
            raw = cast("object", json.loads(metadata_path.read_text(encoding="utf-8")))
            if isinstance(raw, dict) and "eval_id" in raw:
                raw_dict = cast("dict[str, object]", raw)
                return _safe_int(raw_dict.get("eval_id"), eval_idx)
    with contextlib.suppress(ValueError, IndexError):
        return int(eval_dir.name.split("-")[1])
    return eval_idx


def _extract_timing(run_dir: Path, grading: dict[str, object]) -> tuple[float, int]:
    """Extract time in seconds and tokens from grading or timing.json."""
    timing = _safe_dict(grading.get("timing"))
    time_seconds = _safe_float(timing.get("total_duration_seconds"), 0.0)
    tokens = 0
    timing_file = run_dir / "timing.json"
    if time_seconds == 0.0 and timing_file.exists():
        with contextlib.suppress(json.JSONDecodeError, OSError):
            timing_data = cast(
                "object", json.loads(timing_file.read_text(encoding="utf-8"))
            )
            if isinstance(timing_data, dict):
                t_dict = cast("dict[str, object]", timing_data)
                time_seconds = _safe_float(t_dict.get("total_duration_seconds"), 0.0)
                tokens = _safe_int(t_dict.get("total_tokens"), 0)
    return time_seconds, tokens


def _extract_notes(notes_summary: dict[str, object]) -> list[str]:
    """Extract notes list from user notes summary."""
    notes: list[str] = [
        u for u in _safe_list(notes_summary.get("uncertainties")) if isinstance(u, str)
    ]
    notes.extend(
        nr
        for nr in _safe_list(notes_summary.get("needs_review"))
        if isinstance(nr, str)
    )
    notes.extend(
        w for w in _safe_list(notes_summary.get("workarounds")) if isinstance(w, str)
    )
    return notes


def _validate_expectations(raw_expectations: list[object], grading_file: Path) -> None:
    """Validate expectations and warn on missing fields."""
    for exp_obj in raw_expectations:
        exp = _safe_dict(exp_obj)
        if "text" not in exp or "passed" not in exp:
            msg = (
                f"Warning: expectation in {grading_file} missing "
                + f"required fields (text, passed, evidence): {exp}"
            )
            print(msg)


def _load_single_run(run_dir: Path, eval_id: int) -> RunResult | None:
    """Load and process a single run directory."""
    grading_file = run_dir / "grading.json"
    if not grading_file.exists():
        print(f"Warning: grading.json not found in {run_dir}")
        return None

    try:
        raw_grading = cast(
            "object", json.loads(grading_file.read_text(encoding="utf-8"))
        )
        if not isinstance(raw_grading, dict):
            return None
        grading = cast("dict[str, object]", raw_grading)
    except (json.JSONDecodeError, OSError) as e:
        print(f"Warning: Invalid JSON in {grading_file}: {e}")
        return None

    run_number = int(run_dir.name.split("-")[1])
    summary = _safe_dict(grading.get("summary"))
    time_seconds, timing_tokens = _extract_timing(run_dir, grading)

    metrics = _safe_dict(grading.get("execution_metrics"))
    tool_calls = _safe_int(metrics.get("total_tool_calls"), 0)
    tokens = timing_tokens or _safe_int(metrics.get("output_chars"), 0)
    errors = _safe_int(metrics.get("errors_encountered"), 0)

    raw_expectations = _safe_list(grading.get("expectations"))
    _validate_expectations(raw_expectations, grading_file)

    notes_summary = _safe_dict(grading.get("user_notes_summary"))
    notes = _extract_notes(notes_summary)

    return {
        "eval_id": eval_id,
        "run_number": run_number,
        "pass_rate": _safe_float(summary.get("pass_rate"), 0.0),
        "passed": _safe_int(summary.get("passed"), 0),
        "failed": _safe_int(summary.get("failed"), 0),
        "total": _safe_int(summary.get("total"), 0),
        "time_seconds": time_seconds,
        "tokens": tokens,
        "tool_calls": tool_calls,
        "errors": errors,
        "expectations": raw_expectations,
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
        eval_id = _get_eval_id(eval_dir, eval_idx)

        # Discover config directories dynamically rather than hardcoding names
        for config_dir in sorted(eval_dir.iterdir()):
            if not config_dir.is_dir() or not list(config_dir.glob("run-*")):
                continue
            config = config_dir.name
            if config not in results:
                results[config] = []

            for run_dir in sorted(config_dir.glob("run-*")):
                result = _load_single_run(run_dir, eval_id)
                if result is not None:
                    results[config].append(result)

    return results


def aggregate_results(
    results: dict[str, list[RunResult]],
) -> RunSummary:
    """Aggregate run results into summary statistics.

    Returns run_summary with stats for each configuration and delta.
    """
    run_summary: RunSummary = {}
    configs = list(results.keys())

    for config in configs:
        runs = results.get(config, [])

        if not runs:
            run_summary[config] = {
                "pass_rate": {"mean": 0.0, "stddev": 0.0, "min": 0.0, "max": 0.0},
                "time_seconds": {"mean": 0.0, "stddev": 0.0, "min": 0.0, "max": 0.0},
                "tokens": {"mean": 0.0, "stddev": 0.0, "min": 0.0, "max": 0.0},
            }
            continue

        pass_rates = [_safe_float(r.get("pass_rate")) for r in runs]
        times = [_safe_float(r.get("time_seconds")) for r in runs]
        tokens = [_safe_float(r.get("tokens")) for r in runs]

        run_summary[config] = {
            "pass_rate": calculate_stats(pass_rates),
            "time_seconds": calculate_stats(times),
            "tokens": calculate_stats(tokens),
        }

    # Calculate delta between the first two configs (if two exist)
    if len(configs) >= MIN_CONFIGS_FOR_DELTA:
        primary = _safe_dict(run_summary.get(configs[0]))
        baseline = _safe_dict(run_summary.get(configs[1]))
    elif configs:
        primary = _safe_dict(run_summary.get(configs[0]))
        baseline = {}
    else:
        primary = {}
        baseline = {}

    primary_pr = _safe_dict(primary.get("pass_rate"))
    baseline_pr = _safe_dict(baseline.get("pass_rate"))
    delta_pass_rate = _safe_float(primary_pr.get("mean")) - _safe_float(
        baseline_pr.get("mean"),
    )

    primary_ts = _safe_dict(primary.get("time_seconds"))
    baseline_ts = _safe_dict(baseline.get("time_seconds"))
    delta_time = _safe_float(primary_ts.get("mean")) - _safe_float(
        baseline_ts.get("mean"),
    )

    primary_tok = _safe_dict(primary.get("tokens"))
    baseline_tok = _safe_dict(baseline.get("tokens"))
    delta_tokens = _safe_float(primary_tok.get("mean")) - _safe_float(
        baseline_tok.get("mean"),
    )

    run_summary["delta"] = {
        "pass_rate": f"{delta_pass_rate:+.2f}",
        "time_seconds": f"{delta_time:+.1f}",
        "tokens": f"{delta_tokens:+.0f}",
    }

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
    runs: list[dict[str, object]] = [
        {
            "eval_id": result.get("eval_id", 0),
            "configuration": config,
            "run_number": result.get("run_number", 0),
            "result": {
                "pass_rate": result.get("pass_rate", 0.0),
                "passed": result.get("passed", 0),
                "failed": result.get("failed", 0),
                "total": result.get("total", 0),
                "time_seconds": result.get("time_seconds", 0.0),
                "tokens": result.get("tokens", 0),
                "tool_calls": result.get("tool_calls", 0),
                "errors": result.get("errors", 0),
            },
            "expectations": result.get("expectations", []),
            "notes": result.get("notes", []),
        }
        for config in results
        for result in results[config]
    ]

    # Determine eval IDs from results
    eval_ids = sorted(
        {_safe_int(r.get("eval_id")) for config in results.values() for r in config},
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
    metadata = _safe_dict(benchmark.get("metadata"))
    run_summary = cast("RunSummary", _safe_dict(benchmark.get("run_summary")))

    # Determine config names (excluding "delta")
    configs = [k for k in run_summary if k != "delta"]
    config_a = configs[0] if len(configs) >= 1 else "config_a"
    config_b = configs[1] if len(configs) >= MIN_CONFIGS_FOR_DELTA else "config_b"
    label_a = config_a.replace("_", " ").title()
    label_b = config_b.replace("_", " ").title()

    evals_run_list = _safe_list(metadata.get("evals_run"))
    runs_per_config = _safe_int(metadata.get("runs_per_configuration"), 3)
    skill_title = str(metadata.get("skill_name", ""))
    exec_model = str(metadata.get("executor_model", ""))
    ts = str(metadata.get("timestamp", ""))

    lines = [
        f"# Skill Benchmark: {skill_title}",
        "",
        f"**Model**: {exec_model}",
        f"**Date**: {ts}",
        f"**Evals**: {', '.join(map(str, evals_run_list))} "
        + f"({runs_per_config} runs each per configuration)",
        "",
        "## Summary",
        "",
        f"| Metric | {label_a} | {label_b} | Delta |",
        "|--------|------------|---------------|-------|",
    ]

    a_summary = _safe_dict(run_summary.get(config_a))
    b_summary = _safe_dict(run_summary.get(config_b))
    delta = _safe_dict(run_summary.get("delta"))

    # Format pass rate
    a_pr = _safe_dict(a_summary.get("pass_rate"))
    b_pr = _safe_dict(b_summary.get("pass_rate"))
    lines.append(
        "| Pass Rate | "
        + f"{_safe_float(a_pr.get('mean')) * 100:.0f}% "
        + f"± {_safe_float(a_pr.get('stddev')) * 100:.0f}% | "
        + f"{_safe_float(b_pr.get('mean')) * 100:.0f}% "
        + f"± {_safe_float(b_pr.get('stddev')) * 100:.0f}% | "
        + f"{delta.get('pass_rate', '—')} |",
    )

    # Format time
    a_time = _safe_dict(a_summary.get("time_seconds"))
    b_time = _safe_dict(b_summary.get("time_seconds"))
    lines.append(
        f"| Time | {_safe_float(a_time.get('mean')):.1f}s "
        + f"± {_safe_float(a_time.get('stddev')):.1f}s | "
        + f"{_safe_float(b_time.get('mean')):.1f}s "
        + f"± {_safe_float(b_time.get('stddev')):.1f}s | "
        + f"{delta.get('time_seconds', '—')}s |",
    )

    # Format tokens
    a_tokens = _safe_dict(a_summary.get("tokens"))
    b_tokens = _safe_dict(b_summary.get("tokens"))
    lines.append(
        "| Tokens | "
        + f"{_safe_float(a_tokens.get('mean')):.0f} "
        + f"± {_safe_float(a_tokens.get('stddev')):.0f} | "
        + f"{_safe_float(b_tokens.get('mean')):.0f} "
        + f"± {_safe_float(b_tokens.get('stddev')):.0f} | "
        + f"{delta.get('tokens', '—')} |",
    )

    # Notes section
    notes = _safe_list(benchmark.get("notes"))
    if notes:
        lines.extend(["", "## Notes", ""])
        lines.extend([f"- {note}" for note in notes if isinstance(note, str)])

    return "\n".join(lines)


def main() -> None:
    """CLI entry point to aggregate benchmark results."""
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
        help="Output path for benchmark.json (default: <benchmark_dir>/benchmark.json)",
    )

    args = parser.parse_args()
    benchmark_dir = cast("Path", args.benchmark_dir)
    skill_name = cast("str", args.skill_name)
    skill_path = cast("str", args.skill_path)
    output_arg = cast("Path | None", args.output)

    if not benchmark_dir.exists():
        print(f"Directory not found: {benchmark_dir}")
        sys.exit(1)

    # Generate benchmark
    benchmark = generate_benchmark(benchmark_dir, skill_name, skill_path)

    # Determine output paths
    output_json = output_arg or (benchmark_dir / "benchmark.json")
    output_md = output_json.with_suffix(".md")

    # Write benchmark.json
    _ = output_json.write_text(json.dumps(benchmark, indent=2) + "\n", encoding="utf-8")
    print(f"Generated: {output_json}")

    # Write benchmark.md
    markdown = generate_markdown(benchmark)
    _ = output_md.write_text(markdown + "\n", encoding="utf-8")
    print(f"Generated: {output_md}")

    # Print summary
    run_summary = cast("RunSummary", _safe_dict(benchmark.get("run_summary")))
    configs = [k for k in run_summary if k != "delta"]
    delta = _safe_dict(run_summary.get("delta"))

    print("\nSummary:")
    for config in configs:
        pr_dict = _safe_dict(run_summary[config].get("pass_rate"))
        pr = _safe_float(pr_dict.get("mean"))
        label = config.replace("_", " ").title()
        print(f"  {label}: {pr * 100:.1f}% pass rate")
    print(f"  Delta:         {delta.get('pass_rate', '—')}")


if __name__ == "__main__":
    main()
