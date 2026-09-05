#!/usr/bin/env -S uv run --script
"""Generate an HTML report from run_loop.py output.

Takes the JSON output from run_loop.py and generates a visual HTML report
showing each description attempt with check/x for each test case.
Distinguishes between train and test queries.
"""

import argparse
import html
import json
import sys
from pathlib import Path
from typing import cast

SCORE_GOOD_THRESHOLD = 0.8
SCORE_OK_THRESHOLD = 0.5

type QueryInfo = dict[str, object]
type ReportData = dict[str, object]


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


def _safe_int(val: object, default: int = 0) -> int:
    """Extract int safely from an untyped object."""
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        return int(val)
    return default


def _extract_queries(
    history: list[dict[str, object]],
) -> tuple[list[QueryInfo], list[QueryInfo]]:
    """Extract train and test query info from history."""
    train_queries: list[QueryInfo] = []
    test_queries: list[QueryInfo] = []
    if not history:
        return train_queries, test_queries

    first = history[0]
    train_source = _safe_list(first.get("train_results")) or _safe_list(
        first.get("results"),
    )
    for r_obj in train_source:
        r = _safe_dict(r_obj)
        train_queries.append(
            {
                "query": str(r.get("query", "")),
                "should_trigger": bool(r.get("should_trigger", True)),
            },
        )

    test_source = _safe_list(first.get("test_results"))
    for r_obj in test_source:
        r = _safe_dict(r_obj)
        test_queries.append(
            {
                "query": str(r.get("query", "")),
                "should_trigger": bool(r.get("should_trigger", True)),
            },
        )

    return train_queries, test_queries


def _build_html_head(title_prefix: str, auto_refresh: bool) -> str:
    """Build HTML head and CSS styles."""
    refresh_tag = (
        '    <meta http-equiv="refresh" content="5">\n' if auto_refresh else ""
    )
    font_link = (
        '    <link href="https://fonts.googleapis.com/css2?'
        + "family=Poppins:wght@500;600&"
        + 'family=Lora:wght@400;500&display=swap" rel="stylesheet">'
    )
    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
{refresh_tag}    <title>{title_prefix}Skill Description Optimization</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
{font_link}
    <style>
        body {{
            font-family: 'Lora', Georgia, serif;
            max-width: 100%;
            margin: 0 auto;
            padding: 20px;
            background: #faf9f5;
            color: #141413;
        }}
        h1 {{ font-family: 'Poppins', sans-serif; color: #141413; }}
        .explainer {{
            background: white;
            padding: 15px;
            border-radius: 6px;
            margin-bottom: 20px;
            border: 1px solid #e8e6dc;
            color: #b0aea5;
            font-size: 0.875rem;
            line-height: 1.6;
        }}
        .summary {{
            background: white;
            padding: 15px;
            border-radius: 6px;
            margin-bottom: 20px;
            border: 1px solid #e8e6dc;
        }}
        .summary p {{ margin: 5px 0; }}
        .best {{ color: #788c5d; font-weight: bold; }}
        .table-container {{
            overflow-x: auto;
            width: 100%;
        }}
        table {{
            border-collapse: collapse;
            background: white;
            border: 1px solid #e8e6dc;
            border-radius: 6px;
            font-size: 12px;
            min-width: 100%;
        }}
        th, td {{
            padding: 8px;
            text-align: left;
            border: 1px solid #e8e6dc;
            white-space: normal;
            word-wrap: break-word;
        }}
        th {{
            font-family: 'Poppins', sans-serif;
            background: #141413;
            color: #faf9f5;
            font-weight: 500;
        }}
        th.test-col {{
            background: #6a9bcc;
        }}
        th.query-col {{ min-width: 200px; }}
        td.description {{
            font-family: monospace;
            font-size: 11px;
            word-wrap: break-word;
            max-width: 400px;
        }}
        td.result {{
            text-align: center;
            font-size: 16px;
            min-width: 40px;
        }}
        td.test-result {{
            background: #f0f6fc;
        }}
        .pass {{ color: #788c5d; }}
        .fail {{ color: #c44; }}
        .rate {{
            font-size: 9px;
            color: #b0aea5;
            display: block;
        }}
        tr:hover {{ background: #faf9f5; }}
        .score {{
            display: inline-block;
            padding: 2px 6px;
            border-radius: 4px;
            font-weight: bold;
            font-size: 11px;
        }}
        .score-good {{ background: #eef2e8; color: #788c5d; }}
        .score-ok {{ background: #fef3c7; color: #d97706; }}
        .score-bad {{ background: #fceaea; color: #c44; }}
        .train-label {{ color: #b0aea5; font-size: 10px; }}
        .test-label {{ color: #6a9bcc; font-size: 10px; font-weight: bold; }}
        .best-row {{ background: #f5f8f2; }}
        th.positive-col {{ border-bottom: 3px solid #788c5d; }}
        th.negative-col {{ border-bottom: 3px solid #c44; }}
        th.test-col.positive-col {{ border-bottom: 3px solid #788c5d; }}
        th.test-col.negative-col {{ border-bottom: 3px solid #c44; }}
        .legend {{
            font-family: 'Poppins', sans-serif;
            display: flex;
            gap: 20px;
            margin-bottom: 10px;
            font-size: 13px;
            align-items: center;
        }}
        .legend-item {{ display: flex; align-items: center; gap: 6px; }}
        .legend-swatch {{
            width: 16px;
            height: 16px;
            border-radius: 3px;
            display: inline-block;
        }}
        .swatch-positive {{ background: #141413; border-bottom: 3px solid #788c5d; }}
        .swatch-negative {{ background: #141413; border-bottom: 3px solid #c44; }}
        .swatch-test {{ background: #6a9bcc; }}
        .swatch-train {{ background: #141413; }}
    </style>
</head>
<body>
    <h1>{title_prefix}Skill Description Optimization</h1>
    <div class="explainer">
        <strong>Optimizing your skill's description.</strong> This page updates
        automatically as Claude tests different versions of your skill's description.
        Each row is an iteration &mdash; a new description attempt. The columns show
        test queries: green checkmarks mean the skill triggered correctly (or
        correctly didn't trigger), red crosses mean it got it wrong. The "Train" score
        shows performance on queries used to improve the description; the "Test"
        score shows performance on held-out queries the optimizer hasn't seen.
        When it's done, Claude will apply the best-performing description to
        your skill.
    </div>
"""


def _build_summary_section(data: dict[str, object]) -> str:
    """Build summary and legend sections."""
    best_test_score = data.get("best_test_score")
    score_mode = "(test)" if best_test_score else "(train)"
    orig_desc = html.escape(str(data.get("original_description", "N/A")))
    best_desc = html.escape(str(data.get("best_description", "N/A")))
    best_score = str(data.get("best_score", "N/A"))
    iterations = str(data.get("iterations_run", 0))
    train_size = str(data.get("train_size", "?"))
    test_size = str(data.get("test_size", "?"))

    return f"""
    <div class="summary">
        <p><strong>Original:</strong> {orig_desc}</p>
        <p class="best"><strong>Best:</strong> {best_desc}</p>
        <p><strong>Best Score:</strong> {best_score} {score_mode}</p>
        <p><strong>Iterations:</strong> {iterations} |
           <strong>Train:</strong> {train_size} |
           <strong>Test:</strong> {test_size}</p>
    </div>

    <div class="legend">
        <span style="font-weight:600">Query columns:</span>
        <span class="legend-item">
            <span class="legend-swatch swatch-positive"></span> Should trigger
        </span>
        <span class="legend-item">
            <span class="legend-swatch swatch-negative"></span> Should NOT trigger
        </span>
        <span class="legend-item">
            <span class="legend-swatch swatch-train"></span> Train
        </span>
        <span class="legend-item">
            <span class="legend-swatch swatch-test"></span> Test
        </span>
    </div>
"""


def _build_table_header(
    train_queries: list[QueryInfo],
    test_queries: list[QueryInfo],
) -> str:
    """Build table header columns."""
    parts = [
        """
    <div class="table-container">
    <table>
        <thead>
            <tr>
                <th>Iter</th>
                <th>Train</th>
                <th>Test</th>
                <th class="query-col">Description</th>
""",
    ]

    for qinfo in train_queries:
        polarity = "positive-col" if qinfo["should_trigger"] else "negative-col"
        q_text = html.escape(str(qinfo["query"]))
        parts.append(f'                <th class="{polarity}">{q_text}</th>\n')

    for qinfo in test_queries:
        polarity = "positive-col" if qinfo["should_trigger"] else "negative-col"
        q_text = html.escape(str(qinfo["query"]))
        parts.append(
            f'                <th class="test-col {polarity}">{q_text}</th>\n',
        )

    parts.append("""            </tr>
        </thead>
        <tbody>
""")
    return "".join(parts)


def _find_best_iteration(
    history: list[dict[str, object]],
    has_test_queries: bool,
) -> object:
    """Find the best iteration for row highlighting."""
    if not history:
        return None
    if has_test_queries:
        return max(history, key=lambda h: _safe_int(h.get("test_passed"), 0)).get(
            "iteration",
        )
    return max(
        history,
        key=lambda h: _safe_int(h.get("train_passed", h.get("passed", 0)), 0),
    ).get("iteration")


def _aggregate_runs(results: list[dict[str, object]]) -> tuple[int, int]:
    """Compute aggregate correct/total runs across all retries."""
    correct = 0
    total = 0
    for r in results:
        runs = _safe_int(r.get("runs"), 0)
        triggers = _safe_int(r.get("triggers"), 0)
        total += runs
        if bool(r.get("should_trigger", True)):
            correct += triggers
        else:
            correct += runs - triggers
    return correct, total


def _score_class(correct: int, total: int) -> str:
    """Determine CSS score badge class."""
    if total > 0:
        ratio = correct / total
        if ratio >= SCORE_GOOD_THRESHOLD:
            return "score-good"
        if ratio >= SCORE_OK_THRESHOLD:
            return "score-ok"
    return "score-bad"


def _build_iteration_row(
    h: dict[str, object],
    best_iter: object,
    train_queries: list[QueryInfo],
    test_queries: list[QueryInfo],
) -> str:
    """Build single table row for an iteration."""
    iteration = str(h.get("iteration", "?"))
    description = html.escape(str(h.get("description", "")))

    train_results_list = _safe_list(h.get("train_results")) or _safe_list(
        h.get("results"),
    )
    train_results = [_safe_dict(r) for r in train_results_list]
    test_results = [_safe_dict(r) for r in _safe_list(h.get("test_results"))]

    train_by_query = {str(r.get("query", "")): r for r in train_results}
    test_by_query = {str(r.get("query", "")): r for r in test_results}

    train_correct, train_runs = _aggregate_runs(train_results)
    test_correct, test_runs = _aggregate_runs(test_results)

    train_class = _score_class(train_correct, train_runs)
    test_class = _score_class(test_correct, test_runs)

    row_class = "best-row" if h.get("iteration") == best_iter else ""

    parts = [
        f"""            <tr class="{row_class}">
                <td>{iteration}</td>
                <td><span class="score {train_class}">"""
        + f"{train_correct}/{train_runs}</span></td>\n"
        + f'                <td><span class="score {test_class}">'
        + f"{test_correct}/{test_runs}</span></td>\n"
        + f'                <td class="description">{description}</td>\n',
    ]

    for qinfo in train_queries:
        r = train_by_query.get(str(qinfo["query"]), {})
        did_pass = bool(r.get("pass", False))
        triggers = _safe_int(r.get("triggers"), 0)
        runs = _safe_int(r.get("runs"), 0)
        icon = "✓" if did_pass else "✗"
        css_class = "pass" if did_pass else "fail"
        cell = (
            f'                <td class="result {css_class}">'
            + f'{icon}<span class="rate">{triggers}/{runs}</span></td>\n'
        )
        parts.append(cell)

    for qinfo in test_queries:
        r = test_by_query.get(str(qinfo["query"]), {})
        did_pass = bool(r.get("pass", False))
        triggers = _safe_int(r.get("triggers"), 0)
        runs = _safe_int(r.get("runs"), 0)
        icon = "✓" if did_pass else "✗"
        css_class = "pass" if did_pass else "fail"
        cell = (
            f'                <td class="result test-result {css_class}">'
            + f'{icon}<span class="rate">{triggers}/{runs}</span></td>\n'
        )
        parts.append(cell)

    parts.append("            </tr>\n")
    return "".join(parts)


def generate_html(
    data: dict[str, object],
    auto_refresh: bool = False,
    skill_name: str = "",
) -> str:
    """Generate HTML report from loop output data.

    If auto_refresh is True, adds a meta refresh tag.
    """
    history_list = _safe_list(data.get("history"))
    history = [_safe_dict(h) for h in history_list]
    title_prefix = html.escape(skill_name + " \u2014 ") if skill_name else ""

    train_queries, test_queries = _extract_queries(history)

    html_parts = [
        _build_html_head(title_prefix, auto_refresh),
        _build_summary_section(data),
        _build_table_header(train_queries, test_queries),
    ]

    best_iter = _find_best_iteration(history, bool(test_queries))

    html_parts.extend(
        _build_iteration_row(h, best_iter, train_queries, test_queries) for h in history
    )

    html_parts.append("""        </tbody>
    </table>
    </div>
</body>
</html>
""")

    return "".join(html_parts)


def main() -> None:
    """CLI entry point to generate HTML report from run_loop JSON output."""
    parser = argparse.ArgumentParser(
        description="Generate HTML report from run_loop output",
    )
    _ = parser.add_argument(
        "input",
        help="Path to JSON output from run_loop.py (or - for stdin)",
    )
    _ = parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Output HTML file (default: stdout)",
    )
    _ = parser.add_argument(
        "--skill-name",
        default="",
        help="Skill name to include in the report title",
    )
    args = parser.parse_args()
    input_arg = cast("str", args.input)
    output_arg = cast("str | None", args.output)
    skill_name_arg = cast("str", args.skill_name)

    if input_arg == "-":
        raw_data = cast("object", json.load(sys.stdin))
    else:
        raw_data = cast(
            "object",
            json.loads(Path(input_arg).read_text(encoding="utf-8")),
        )

    data = _safe_dict(raw_data)
    html_output = generate_html(data, skill_name=skill_name_arg)

    if output_arg:
        _ = Path(output_arg).write_text(html_output, encoding="utf-8")
        print(f"Report written to {output_arg}", file=sys.stderr)
    else:
        print(html_output)


if __name__ == "__main__":
    main()
