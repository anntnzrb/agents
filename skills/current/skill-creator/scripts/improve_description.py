#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["PyYAML>=6.0"]
# ///
"""Improve a skill description based on eval results.

Takes eval results (from run_eval.py) and generates an improved description
by calling `claude -p` as a subprocess (same auth pattern as run_eval.py —
uses the session's Claude Code auth, no separate ANTHROPIC_API_KEY needed).
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import cast

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.utils import parse_skill_md

CHAR_LIMIT = 1024
DEFAULT_TIMEOUT = 300

type ResultItem = dict[str, object]
type HistoryItem = dict[str, object]
type EvalData = dict[str, object]


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


def _call_claude(
    prompt: str,
    model: str | None,
    timeout: int = DEFAULT_TIMEOUT,
) -> str:
    """Run `claude -p` with the prompt on stdin and return the text response.

    Prompt goes over stdin (not argv) because it embeds the full SKILL.md
    body and can easily exceed comfortable argv length.
    """
    cmd = ["claude", "-p", "--output-format", "text"]
    if model:
        cmd.extend(["--model", model])

    # Remove CLAUDECODE env var to allow nesting claude -p inside a
    # Claude Code session. The guard is for interactive terminal conflicts;
    # programmatic subprocess usage is safe. Same pattern as run_eval.py.
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

    result = subprocess.run(  # noqa: S603 - invoke claude CLI directly
        cmd,
        input=prompt,
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        msg = f"claude -p exited {result.returncode}\nstderr: {result.stderr}"
        raise RuntimeError(msg)
    return result.stdout


def _build_scores_summary(
    eval_results: dict[str, object],
    test_results: dict[str, object] | None,
) -> str:
    """Format scores summary header for prompt."""
    eval_summary = _safe_dict(eval_results.get("summary"))
    train_score = (
        f"{_safe_int(eval_summary.get('passed'))}/"
        + f"{_safe_int(eval_summary.get('total'))}"
    )
    if test_results:
        test_summary = _safe_dict(test_results.get("summary"))
        test_score = (
            f"{_safe_int(test_summary.get('passed'))}/"
            + f"{_safe_int(test_summary.get('total'))}"
        )
        return f"Train: {train_score}, Test: {test_score}"
    return f"Train: {train_score}"


def _format_history_attempt(h: dict[str, object]) -> str:
    """Format a single history attempt for the prompt."""
    train_s = (
        f"{_safe_int(h.get('train_passed', h.get('passed', 0)))}/"
        + f"{_safe_int(h.get('train_total', h.get('total', 0)))}"
    )
    test_s = (
        f"{h.get('test_passed', '?')}/{h.get('test_total', '?')}"
        if h.get("test_passed") is not None
        else None
    )
    score_str = f"train={train_s}" + (f", test={test_s}" if test_s else "")
    desc = str(h.get("description", ""))
    attempt_lines = [
        f"<attempt {score_str}>",
        f'Description: "{desc}"',
    ]
    if "results" in h:
        attempt_lines.append("Train results:")
        for r_obj in _safe_list(h.get("results")):
            r = _safe_dict(r_obj)
            status = "PASS" if bool(r.get("pass")) else "FAIL"
            query_str = str(r.get("query", ""))[:80]
            trig = _safe_int(r.get("triggers"))
            runs = _safe_int(r.get("runs"))
            attempt_lines.append(
                f'  [{status}] "{query_str}" (triggered {trig}/{runs})',
            )
    if h.get("note"):
        attempt_lines.append(f"Note: {h.get('note')}")
    attempt_lines.append("</attempt>\n")
    return "\n".join(attempt_lines)


def _build_prompt_intro(skill_name: str, current_description: str) -> str:
    """Build the opening guidelines and current description section."""
    return (
        "You are optimizing a skill description for a Claude Code skill "
        + f'called "{skill_name}". '
        + 'A "skill" is sort of like a prompt, but with progressive disclosure -- '
        + "there's a title and description that Claude sees when deciding "
        + "whether to use the skill, "
        + "and then if it does use the skill, it reads the .md file which has "
        + "lots more details and potentially links to other resources in the "
        + "skill folder like helper files and scripts and additional "
        + "documentation or examples.\n\n"
        + 'The description appears in Claude\'s "available_skills" list. '
        + "When a user sends a query, Claude decides whether to invoke the skill "
        + "based solely on the title and on this description. Your goal is to "
        + "write a description that triggers for relevant queries, and doesn't "
        + "trigger for irrelevant ones.\n\n"
        + "Here's the current description:\n"
        + "<current_description>\n"
        + f'"{current_description}"\n'
        + "</current_description>\n\n"
    )


def _build_prompt_instructions(skill_content: str) -> str:
    """Build the instructions and tips section of the prompt."""
    return (
        "</scores_summary>\n\n"
        + "Skill content (for context on what the skill does):\n"
        + "<skill_content>\n"
        + f"{skill_content}\n"
        + "</skill_content>\n\n"
        + "Based on the failures, write a new and improved description that is "
        + 'more likely to trigger correctly. When I say "based on the failures", '
        + "it's a bit of a tricky line to walk because we don't want to overfit "
        + "to the specific cases you're seeing. So what I DON'T want you to do is "
        + "produce an ever-expanding list of specific queries that this skill "
        + "should or shouldn't trigger for. Instead, try to generalize "
        + "from the failures to broader categories of user intent and situations "
        + "where this skill would be useful or not useful. The reason for this is "
        + "twofold:\n\n"
        + "1. Avoid overfitting\n"
        + "2. The list might get loooong and it's injected into ALL queries and "
        + "there might be a lot of skills, so we don't want to blow too much "
        + "space on any given description.\n\n"
        + "Concretely, your description should not be more than about 100-200 "
        + "words, even if that comes at the cost of accuracy. There is a hard "
        + f"limit of {CHAR_LIMIT} characters — descriptions over that will be "
        + "truncated, so stay comfortably under it.\n\n"
        + "Here are some tips that we've found to work well in writing these "
        + "descriptions:\n"
        + '- The skill should be phrased in the imperative -- "Use this skill for" '
        + 'rather than "this skill does"\n'
        + "- The skill description should focus on the user's intent, what they "
        + "are trying to achieve, vs. the implementation details of how the "
        + "skill works.\n"
        + "- The description competes with other skills for Claude's attention — "
        + "make it distinctive and immediately recognizable.\n"
        + "- If you're getting lots of failures after repeated attempts, change "
        + "things up. Try different sentence structures or wordings.\n\n"
        + "I'd encourage you to be creative and mix up the style in different "
        + "iterations since you'll have multiple opportunities to try different "
        + "approaches and we'll just grab the highest-scoring one at the end.\n\n"
        + "Please respond with only the new description text in "
        + "<new_description> tags, nothing else."
    )


def _build_prompt(  # noqa: PLR0913, PLR0917 - prompt assembly helper
    skill_name: str,
    skill_content: str,
    current_description: str,
    eval_results: dict[str, object],
    history: list[dict[str, object]],
    test_results: dict[str, object] | None,
) -> str:
    """Build the full improvement prompt."""
    results_list = [_safe_dict(r) for r in _safe_list(eval_results.get("results"))]
    failed_triggers = [
        r
        for r in results_list
        if bool(r.get("should_trigger")) and not bool(r.get("pass"))
    ]
    false_triggers = [
        r
        for r in results_list
        if not bool(r.get("should_trigger")) and not bool(r.get("pass"))
    ]

    scores_summary = _build_scores_summary(eval_results, test_results)

    sections = [
        _build_prompt_intro(skill_name, current_description),
        f"Current scores ({scores_summary}):\n",
        "<scores_summary>\n",
    ]

    if failed_triggers:
        sections.append("FAILED TO TRIGGER (should have triggered but didn't):\n")
        for r in failed_triggers:
            query_text = str(r.get("query", ""))
            trig = _safe_int(r.get("triggers"))
            runs = _safe_int(r.get("runs"))
            sections.append(f'  - "{query_text}" (triggered {trig}/{runs} times)\n')
        sections.append("\n")

    if false_triggers:
        sections.append("FALSE TRIGGERS (triggered but shouldn't have):\n")
        for r in false_triggers:
            query_text = str(r.get("query", ""))
            trig = _safe_int(r.get("triggers"))
            runs = _safe_int(r.get("runs"))
            sections.append(f'  - "{query_text}" (triggered {trig}/{runs} times)\n')
        sections.append("\n")

    if history:
        sections.append(
            "PREVIOUS ATTEMPTS (do NOT repeat these — try something "
            + "structurally different):\n\n",
        )
        sections.extend(_format_history_attempt(h) + "\n" for h in history)

    sections.append(_build_prompt_instructions(skill_content))
    return "".join(sections)


def _extract_description(text: str) -> str:
    """Extract description text from Claude's response."""
    match = re.search(r"<new_description>(.*?)</new_description>", text, re.DOTALL)
    if match:
        return match.group(1).strip().strip('"')
    return text.strip().strip('"')


def _handle_rewrite(
    prompt: str,
    description: str,
    model: str,
    transcript: dict[str, object],
) -> str:
    """Request a shortened description if length exceeds limit."""
    if len(description) <= CHAR_LIMIT:
        return description

    shorten_prompt = (
        f"{prompt}\n\n"
        + "---\n\n"
        + "A previous attempt produced this description, which at "
        + f"{len(description)} characters is over the "
        + f"{CHAR_LIMIT}-character hard limit:\n\n"
        + f'"{description}"\n\n'
        + f"Rewrite it to be under {CHAR_LIMIT} characters while keeping the most "
        + "important trigger words and intent coverage. Respond with only "
        + "the new description in <new_description> tags."
    )
    shorten_text = _call_claude(shorten_prompt, model)
    shortened = _extract_description(shorten_text)

    transcript["rewrite_prompt"] = shorten_prompt
    transcript["rewrite_response"] = shorten_text
    transcript["rewrite_description"] = shortened
    transcript["rewrite_char_count"] = len(shortened)
    return shortened


def improve_description(  # noqa: PLR0913, PLR0917 - public signature required by run_loop
    skill_name: str,
    skill_content: str,
    current_description: str,
    eval_results: dict[str, object],
    history: list[dict[str, object]],
    model: str,
    test_results: dict[str, object] | None = None,
    log_dir: Path | None = None,
    iteration: int | None = None,
) -> str:
    """Call Claude to improve the description based on eval results."""
    prompt = _build_prompt(
        skill_name,
        skill_content,
        current_description,
        eval_results,
        history,
        test_results,
    )

    text = _call_claude(prompt, model)
    description = _extract_description(text)

    transcript: dict[str, object] = {
        "iteration": iteration,
        "prompt": prompt,
        "response": text,
        "parsed_description": description,
        "char_count": len(description),
        "over_limit": len(description) > CHAR_LIMIT,
    }

    description = _handle_rewrite(prompt, description, model, transcript)
    transcript["final_description"] = description

    if log_dir:
        log_dir.mkdir(parents=True, exist_ok=True)
        iter_label = str(iteration) if iteration is not None else "unknown"
        log_file = log_dir / f"improve_iter_{iter_label}.json"
        _ = log_file.write_text(
            json.dumps(transcript, indent=2) + "\n",
            encoding="utf-8",
        )

    return description


def main() -> None:
    """CLI entry point to improve skill description based on eval results."""
    parser = argparse.ArgumentParser(
        description="Improve a skill description based on eval results",
    )
    _ = parser.add_argument(
        "--eval-results",
        required=True,
        help="Path to eval results JSON (from run_eval.py)",
    )
    _ = parser.add_argument(
        "--skill-path",
        required=True,
        help="Path to skill directory",
    )
    _ = parser.add_argument(
        "--history",
        default=None,
        help="Path to history JSON (previous attempts)",
    )
    _ = parser.add_argument(
        "--model",
        required=True,
        help="Model for improvement",
    )
    _ = parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print thinking to stderr",
    )
    args_dict = cast("dict[str, object]", vars(parser.parse_args()))
    skill_path_str = str(args_dict.get("skill_path", ""))
    eval_results_str = str(args_dict.get("eval_results", ""))
    history_path_val = args_dict.get("history")
    model_str = str(args_dict.get("model", ""))
    is_verbose = bool(args_dict.get("verbose", False))

    skill_path = Path(skill_path_str)
    if not (skill_path / "SKILL.md").exists():
        print(f"Error: No SKILL.md found at {skill_path}", file=sys.stderr)
        sys.exit(1)

    eval_raw = cast(
        "object",
        json.loads(Path(eval_results_str).read_text(encoding="utf-8")),
    )
    eval_results = _safe_dict(eval_raw)

    history: list[dict[str, object]] = []
    if history_path_val:
        hist_raw = cast(
            "object",
            json.loads(Path(str(history_path_val)).read_text(encoding="utf-8")),
        )
        history = [_safe_dict(h) for h in _safe_list(hist_raw)]

    name, _, content = parse_skill_md(skill_path)
    current_description = str(eval_results.get("description", ""))

    summary_dict = _safe_dict(eval_results.get("summary"))
    if is_verbose:
        print(f"Current: {current_description}", file=sys.stderr)
        print(
            f"Score: {_safe_int(summary_dict.get('passed'))}/"
            + f"{_safe_int(summary_dict.get('total'))}",
            file=sys.stderr,
        )

    new_description = improve_description(
        skill_name=name,
        skill_content=content,
        current_description=current_description,
        eval_results=eval_results,
        history=history,
        model=model_str,
    )

    if is_verbose:
        print(f"Improved: {new_description}", file=sys.stderr)

    # Output as JSON with both the new description and updated history
    output = {
        "description": new_description,
        "history": [
            *history,
            {
                "description": current_description,
                "passed": _safe_int(summary_dict.get("passed")),
                "failed": _safe_int(summary_dict.get("failed")),
                "total": _safe_int(summary_dict.get("total")),
                "results": _safe_list(eval_results.get("results")),
            },
        ],
    }
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
