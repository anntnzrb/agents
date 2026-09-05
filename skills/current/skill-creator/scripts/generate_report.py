#!/usr/bin/env -S uv run --script
# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
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
from typing import Final

_SCORE_GOOD_RATIO: Final[float] = 0.8
_SCORE_OK_RATIO: Final[float] = 0.5


def _query_columns(history: list[dict]) -> tuple[list[dict], list[dict]]:
    """Collect unique train/test queries with should_trigger info."""
    train_queries: list[dict] = []
    test_queries: list[dict] = []
    if not history:
        return train_queries, test_queries
    for r in history[0].get("train_results", history[0].get("results", [])):
        train_queries.append(
            {"query": r["query"], "should_trigger": r.get("should_trigger", True)},
        )
    if history[0].get("test_results"):
        for r in history[0].get("test_results", []):
            test_queries.append(
                {
                    "query": r["query"],
                    "should_trigger": r.get("should_trigger", True),
                },
            )
    return train_queries, test_queries


def _summary_html(data: dict) -> str:
    """Build the summary div from loop output data."""
    best_kind = "(test)" if data.get("best_test_score") else "(train)"
    original = html.escape(data.get("original_description", "N/A"))
    best = html.escape(data.get("best_description", "N/A"))
    iterations = data.get("iterations_run", 0)
    train_size = data.get("train_size", "?")
    test_size = data.get("test_size", "?")
    return (
        f"""
    <div class="summary">
        <p><strong>Original:</strong> {original}</p>
        <p class="best"><strong>Best:</strong> {best}</p>
        <p><strong>Best Score:</strong> {data.get("best_score", "N/A")} {best_kind}</p>
        <p><strong>Iterations:</strong> {iterations} | <strong>Train:</strong> """
        f"""{train_size} | <strong>Test:</strong> {test_size}</p>
    </div>
"""
    )


def _column_headers(train_queries: list[dict], test_queries: list[dict]) -> str:
    """Build the query column header cells."""
    parts = []
    for qinfo in train_queries:
        polarity = "positive-col" if qinfo["should_trigger"] else "negative-col"
        query = html.escape(qinfo["query"])
        parts.append(f'                <th class="{polarity}">{query}</th>\n')
    for qinfo in test_queries:
        polarity = "positive-col" if qinfo["should_trigger"] else "negative-col"
        query = html.escape(qinfo["query"])
        parts.append(f'                <th class="test-col {polarity}">{query}</th>\n')
    return "".join(parts)


def _best_iteration(history: list[dict], test_queries: list[dict]) -> object:
    """Find the best iteration id for highlighting."""
    if test_queries:
        best = max(history, key=lambda h: h.get("test_passed") or 0)
    else:
        best = max(
            history,
            key=lambda h: h.get("train_passed", h.get("passed", 0)),
        )
    return best.get("iteration")


def _aggregate_runs(results: list[dict]) -> tuple[int, int]:
    """Aggregate correct/total runs across all retries."""
    correct = 0
    total = 0
    for r in results:
        runs = r.get("runs", 0)
        triggers = r.get("triggers", 0)
        total += runs
        if r.get("should_trigger", True):
            correct += triggers
        else:
            correct += runs - triggers
    return correct, total


def _score_class(correct: int, total: int) -> str:
    """Return the CSS score class for a correct/total pair."""
    if total > 0:
        ratio = correct / total
        if ratio >= _SCORE_GOOD_RATIO:
            return "score-good"
        if ratio >= _SCORE_OK_RATIO:
            return "score-ok"
    return "score-bad"


def _result_cell(css_class: str, icon: str, triggers: int, runs: int) -> str:
    """Build one result table cell."""
    rate = f"{triggers}/{runs}"
    return (
        f'                <td class="result {css_class}">{icon}'
        f'<span class="rate">{rate}</span></td>\n'
    )


def _iteration_row(
    h: dict, best_iter: object, train_queries: list[dict], test_queries: list[dict]
) -> str:
    """Build one iteration table row."""
    iteration = h.get("iteration", "?")
    description = h.get("description", "")
    train_results = h.get("train_results", h.get("results", []))
    test_results = h.get("test_results", [])
    train_by_query = {r["query"]: r for r in train_results}
    test_by_query = {r["query"]: r for r in test_results} if test_results else {}
    train_correct, train_runs = _aggregate_runs(train_results)
    test_correct, test_runs = _aggregate_runs(test_results)
    train_class = _score_class(train_correct, train_runs)
    test_class = _score_class(test_correct, test_runs)
    row_class = "best-row" if iteration == best_iter else ""
    desc = html.escape(description)
    train_cell = (
        f'<td><span class="score {train_class}">'
        f"{train_correct}/{train_runs}</span></td>"
    )
    test_cell = (
        f'<td><span class="score {test_class}">{test_correct}/{test_runs}</span></td>'
    )
    parts = [
        f"""            <tr class="{row_class}">
                <td>{iteration}</td>
                {train_cell}
                {test_cell}
                <td class="description">{desc}</td>
"""
    ]
    for qinfo in train_queries:
        r = train_by_query.get(qinfo["query"], {})
        did_pass = r.get("pass", False)
        icon = "✓" if did_pass else "✗"
        css_class = "pass" if did_pass else "fail"
        parts.append(
            _result_cell(css_class, icon, r.get("triggers", 0), r.get("runs", 0))
        )
    for qinfo in test_queries:
        r = test_by_query.get(qinfo["query"], {})
        did_pass = r.get("pass", False)
        icon = "✓" if did_pass else "✗"
        css_class = "pass" if did_pass else "fail"
        parts.append(
            _result_cell(
                f"test-result {css_class}",
                icon,
                r.get("triggers", 0),
                r.get("runs", 0),
            )
        )
    parts.append("            </tr>\n")
    return "".join(parts)


def generate_html(
    data: dict, skill_name: str = "", *, auto_refresh: bool = False
) -> str:
    """Generate HTML report from loop output data.

    If auto_refresh is True, adds a meta refresh tag.
    """
    history = data.get("history", [])
    title_prefix = html.escape(skill_name + " \u2014 ") if skill_name else ""
    train_queries, test_queries = _query_columns(history)

    refresh_tag = (
        '    <meta http-equiv="refresh" content="5">\n' if auto_refresh else ""
    )

    html_parts = [
        """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
"""
        + refresh_tag
        + """    <title>"""
        + title_prefix
        + """Skill Description Optimization</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@500;600"""
        """&family=Lora:wght@400;500&display=swap" rel="stylesheet">
    <style>
        body {
            font-family: 'Lora', Georgia, serif;
            max-width: 100%;
            margin: 0 auto;
            padding: 20px;
            background: #faf9f5;
            color: #141413;
        }
        h1 { font-family: 'Poppins', sans-serif; color: #141413; }
        .explainer {
            background: white;
            padding: 15px;
            border-radius: 6px;
            margin-bottom: 20px;
            border: 1px solid #e8e6dc;
            color: #b0aea5;
            font-size: 0.875rem;
            line-height: 1.6;
        }
        .summary {
            background: white;
            padding: 15px;
            border-radius: 6px;
            margin-bottom: 20px;
            border: 1px solid #e8e6dc;
        }
        .summary p { margin: 5px 0; }
        .best { color: #788c5d; font-weight: bold; }
        .table-container {
            overflow-x: auto;
            width: 100%;
        }
        table {
            border-collapse: collapse;
            background: white;
            border: 1px solid #e8e6dc;
            border-radius: 6px;
            font-size: 12px;
            min-width: 100%;
        }
        th, td {
            padding: 8px;
            text-align: left;
            border: 1px solid #e8e6dc;
            white-space: normal;
            word-wrap: break-word;
        }
        th {
            font-family: 'Poppins', sans-serif;
            background: #141413;
            color: #faf9f5;
            font-weight: 500;
        }
        th.test-col {
            background: #6a9bcc;
        }
        th.query-col { min-width: 200px; }
        td.description {
            font-family: monospace;
            font-size: 11px;
            word-wrap: break-word;
            max-width: 400px;
        }
        td.result {
            text-align: center;
            font-size: 16px;
            min-width: 40px;
        }
        td.test-result {
            background: #f0f6fc;
        }
        .pass { color: #788c5d; }
        .fail { color: #c44; }
        .rate {
            font-size: 9px;
            color: #b0aea5;
            display: block;
        }
        tr:hover { background: #faf9f5; }
        .score {
            display: inline-block;
            padding: 2px 6px;
            border-radius: 4px;
            font-weight: bold;
            font-size: 11px;
        }
        .score-good { background: #eef2e8; color: #788c5d; }
        .score-ok { background: #fef3c7; color: #d97706; }
        .score-bad { background: #fceaea; color: #c44; }
        .train-label { color: #b0aea5; font-size: 10px; }
        .test-label { color: #6a9bcc; font-size: 10px; font-weight: bold; }
        .best-row { background: #f5f8f2; }
        th.positive-col { border-bottom: 3px solid #788c5d; }
        th.negative-col { border-bottom: 3px solid #c44; }
        th.test-col.positive-col { border-bottom: 3px solid #788c5d; }
        th.test-col.negative-col { border-bottom: 3px solid #c44; }
        .legend { font-family: 'Poppins', sans-serif; display: flex; gap: 20px;"""
        """ margin-bottom: 10px; font-size: 13px; align-items: center; }
        .legend-item { display: flex; align-items: center; gap: 6px; }
        .legend-swatch { width: 16px; height: 16px; border-radius: 3px;"""
        """ display: inline-block; }
        .swatch-positive { background: #141413; border-bottom: 3px solid #788c5d; }
        .swatch-negative { background: #141413; border-bottom: 3px solid #c44; }
        .swatch-test { background: #6a9bcc; }
        .swatch-train { background: #141413; }
    </style>
</head>
<body>
    <h1>""" + title_prefix + """Skill Description Optimization</h1>
    <div class="explainer">
        <strong>Optimizing your skill's description.</strong> This page updates"""
        """ automatically as Claude tests different versions of your skill's"""
        """ description. Each row is an iteration — a new description attempt."""
        """ The columns show test queries: green checkmarks mean the skill"""
        """ triggered correctly (or correctly didn't trigger), red crosses mean"""
        """ it got it wrong. The "Train" score shows performance on queries"""
        """ used to improve the description; the "Test" score shows"""
        """ performance on held-out queries the optimizer hasn't seen. When"""
        """ it's done, Claude will apply the best-performing description to"""
        """ your skill.
    </div>
""",
    ]

    # Summary section
    html_parts.append(_summary_html(data))

    # Legend
    html_parts.append(
        """
    <div class="legend">
        <span style="font-weight:600">Query columns:</span>
        <span class="legend-item"><span class="legend-swatch swatch-positive"></span>"""
        """ Should trigger</span>
        <span class="legend-item"><span class="legend-swatch swatch-negative"></span>"""
        """ Should NOT trigger</span>
        <span class="legend-item"><span class="legend-swatch swatch-train"></span>"""
        """ Train</span>
        <span class="legend-item"><span class="legend-swatch swatch-test"></span>"""
        """ Test</span>
    </div>
"""
    )

    # Table header
    html_parts.append("""
    <div class="table-container">
    <table>
        <thead>
            <tr>
                <th>Iter</th>
                <th>Train</th>
                <th>Test</th>
                <th class="query-col">Description</th>
""")

    # Add column headers for train and test queries
    html_parts.append(_column_headers(train_queries, test_queries))

    html_parts.append("""            </tr>
        </thead>
        <tbody>
""")

    # Find best iteration for highlighting
    best_iter = _best_iteration(history, test_queries)

    # Add rows for each iteration
    for h in history:
        html_parts.append(_iteration_row(h, best_iter, train_queries, test_queries))

    html_parts.append("""        </tbody>
    </table>
    </div>
""")

    html_parts.append("""
</body>
</html>
""")

    return "".join(html_parts)


def main() -> None:
    """Generate HTML report from command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Generate HTML report from run_loop output",
    )
    parser.add_argument(
        "input",
        help="Path to JSON output from run_loop.py (or - for stdin)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Output HTML file (default: stdout)",
    )
    parser.add_argument(
        "--skill-name",
        default="",
        help="Skill name to include in the report title",
    )
    args = parser.parse_args()

    if args.input == "-":
        data = json.load(sys.stdin)
    else:
        data = json.loads(Path(args.input).read_text())

    html_output = generate_html(data, skill_name=args.skill_name)

    if args.output:
        Path(args.output).write_text(html_output)
        print(f"Report written to {args.output}", file=sys.stderr)
    else:
        print(html_output)


if __name__ == "__main__":
    main()
