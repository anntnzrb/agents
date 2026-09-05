#!/usr/bin/env -S uv run --script
# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
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
from dataclasses import dataclass
from pathlib import Path
from typing import Final

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.utils import parse_skill_md

_MAX_DESCRIPTION_CHARS: Final[int] = 1024


def _call_claude(prompt: str, model: str | None, timeout: int = 300) -> str:
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
    # Fixed argv, no shell: the prompt travels over stdin, not the command line.
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    result = subprocess.run(
        cmd,
        input=prompt,
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"claude -p exited {result.returncode}\nstderr: {result.stderr}",
        )
    return result.stdout


@dataclass(frozen=True, slots=True)
class ImproveParams:
    """Inputs for one description-improvement call."""

    skill_name: str
    skill_content: str
    current_description: str
    eval_results: dict
    history: list[dict]
    model: str
    test_results: dict | None = None
    log_dir: Path | None = None
    iteration: int | None = None


def _split_trigger_results(eval_results: dict) -> tuple[list[dict], list[dict]]:
    """Split eval results into failed-to-trigger and false-trigger lists."""
    results = eval_results["results"]
    failed = [r for r in results if r["should_trigger"] and not r["pass"]]
    false = [r for r in results if not r["should_trigger"] and not r["pass"]]
    return failed, false


def _scores_summary(eval_results: dict, test_results: dict | None) -> str:
    """Summarize train (and test, when present) scores."""
    summary = eval_results["summary"]
    train_score = f"{summary['passed']}/{summary['total']}"
    if not test_results:
        return f"Train: {train_score}"
    test_summary = test_results["summary"]
    test_score = f"{test_summary['passed']}/{test_summary['total']}"
    return f"Train: {train_score}, Test: {test_score}"


def _prompt_head(skill_name: str, current_description: str, scores_summary: str) -> str:
    """Build the opening prompt section through <scores_summary>."""
    return (
        "You are optimizing a skill description for a Claude Code skill called "
        f'"{skill_name}". A "skill" is sort of like a prompt, but with '
        "progressive disclosure -- there's a title and description that "
        "Claude sees when deciding whether to use the skill, and then if it "
        "does use the skill, it reads the .md file which has lots more "
        "details and potentially links to other resources in the skill "
        "folder like helper files and scripts and additional documentation "
        "or examples.\n"
        "\n"
        "The description appears in Claude's "
        '"available_skills" list. When a user sends a query, Claude decides '
        "whether to invoke the skill based solely on the title and on this "
        "description. Your goal is to write a description that triggers for "
        "relevant queries, and doesn't trigger for irrelevant ones.\n"
        "\n"
        "Here's the current description:\n"
        "<current_description>\n"
        f'"{current_description}"\n'
        "</current_description>\n"
        "\n"
        f"Current scores ({scores_summary}):\n"
        "<scores_summary>\n"
    )


def _failure_section(title: str, rows: list[dict]) -> str:
    """Build one failure-list prompt section (empty when no rows)."""
    if not rows:
        return ""
    section = f"{title}:\n"
    for r in rows:
        triggers = r["triggers"]
        runs = r["runs"]
        section += f'  - "{r["query"]}" (triggered {triggers}/{runs} times)\n'
    return section + "\n"


def _history_section(history: list[dict]) -> str:
    """Build the previous-attempts prompt section (empty without history)."""
    if not history:
        return ""
    section = (
        "PREVIOUS ATTEMPTS (do NOT repeat these — try something "
        "structurally different):\n\n"
    )
    for h in history:
        train_s = (
            f"{h.get('train_passed', h.get('passed', 0))}"
            f"/{h.get('train_total', h.get('total', 0))}"
        )
        if h.get("test_passed") is not None:
            test_s = f"{h.get('test_passed', '?')}/{h.get('test_total', '?')}"
        else:
            test_s = None
        score_str = f"train={train_s}" + (f", test={test_s}" if test_s else "")
        section += f"<attempt {score_str}>\n"
        section += f'Description: "{h["description"]}"\n'
        if "results" in h:
            section += "Train results:\n"
            for r in h["results"]:
                status = "PASS" if r["pass"] else "FAIL"
                section += (
                    f'  [{status}] "{r["query"][:80]}"'
                    f" (triggered {r['triggers']}/{r['runs']})\n"
                )
        if h.get("note"):
            section += f"Note: {h['note']}\n"
        section += "</attempt>\n\n"
    return section


def _prompt_tail(skill_content: str) -> str:
    """Build the closing prompt section from </scores_summary> onward."""
    return (
        "</scores_summary>\n"
        "\n"
        "Skill content (for context on what the skill does):\n"
        "<skill_content>\n"
        f"{skill_content}\n"
        "</skill_content>\n"
        "\n"
        "Based on the failures, write a new and improved description that is "
        "more likely to trigger correctly. When I say "
        '"based on the failures", it\'s a bit of a tricky line to walk '
        "because we don't want to overfit to the specific cases you're "
        "seeing. So what I DON'T want you to do is produce an "
        "ever-expanding list of specific queries that this skill should or "
        "shouldn't trigger for. Instead, try to generalize from the "
        "failures to broader categories of user intent and situations where "
        "this skill would be useful or not useful. The reason for this is "
        "twofold:\n"
        "\n"
        "1. Avoid overfitting\n"
        "2. The list might get loooong and it's injected into ALL queries "
        "and there might be a lot of skills, so we don't want to blow too "
        "much space on any given description.\n"
        "\n"
        "Concretely, your description should not be more than about 100-200 "
        "words, even if that comes at the cost of accuracy. There is a hard "
        "limit of 1024 characters — descriptions over that will be "
        "truncated, so stay comfortably under it.\n"
        "\n"
        "Here are some tips that we've found to work well in writing these "
        "descriptions:\n"
        '- The skill should be phrased in the imperative -- "Use this skill '
        'for" rather than "this skill does"\n'
        "- The skill description should focus on the user's intent, what "
        "they are trying to achieve, vs. the implementation details of how "
        "the skill works.\n"
        "- The description competes with other skills for Claude's "
        "attention — make it distinctive and immediately recognizable.\n"
        "- If you're getting lots of failures after repeated attempts, "
        "change things up. Try different sentence structures or wordings.\n"
        "\n"
        "I'd encourage you to be creative and mix up the style in different "
        "iterations since you'll have multiple opportunities to try "
        "different approaches and we'll just grab the highest-scoring one "
        "at the end.\n"
        "\n"
        "Please respond with only the new description text in "
        "<new_description> tags, nothing else."
    )


def _extract_description(text: str) -> str:
    """Extract <new_description> content, falling back to stripped text."""
    match = re.search(r"<new_description>(.*?)</new_description>", text, re.DOTALL)
    if match:
        return match.group(1).strip().strip('"')
    return text.strip().strip('"')


def _shorten_over_limit(
    description: str, prompt: str, model: str, transcript: dict
) -> str:
    """Make one fresh single-turn call asking for a shorter rewrite."""
    shorten_prompt = (
        f"{prompt}\n\n---\n\n"
        "A previous attempt produced this description, which at "
        f"{len(description)} characters is over the "
        f"{_MAX_DESCRIPTION_CHARS}-character hard limit:\n\n"
        f'"{description}"\n\n'
        f"Rewrite it to be under {_MAX_DESCRIPTION_CHARS} characters while "
        "keeping the most important trigger words and intent coverage. "
        "Respond with only the new description in <new_description> tags."
    )
    shorten_text = _call_claude(shorten_prompt, model)
    shortened = _extract_description(shorten_text)
    transcript["rewrite_prompt"] = shorten_prompt
    transcript["rewrite_response"] = shorten_text
    transcript["rewrite_description"] = shortened
    transcript["rewrite_char_count"] = len(shortened)
    return shortened


def improve_description(params: ImproveParams) -> str:
    """Call Claude to improve the description based on eval results."""
    failed_triggers, false_triggers = _split_trigger_results(params.eval_results)
    scores_summary = _scores_summary(params.eval_results, params.test_results)
    prompt = (
        _prompt_head(params.skill_name, params.current_description, scores_summary)
        + _failure_section(
            "FAILED TO TRIGGER (should have triggered but didn't)",
            failed_triggers,
        )
        + _failure_section(
            "FALSE TRIGGERS (triggered but shouldn't have)", false_triggers
        )
        + _history_section(params.history)
        + _prompt_tail(params.skill_content)
    )

    text = _call_claude(prompt, params.model)
    description = _extract_description(text)

    transcript: dict = {
        "iteration": params.iteration,
        "prompt": prompt,
        "response": text,
        "parsed_description": description,
        "char_count": len(description),
        "over_limit": len(description) > _MAX_DESCRIPTION_CHARS,
    }

    # Safety net: the prompt already states the 1024-char hard limit, but if
    # the model blew past it anyway, make one fresh single-turn call that
    # quotes the too-long version and asks for a shorter rewrite. (The old
    # SDK path did this as a true multi-turn; `claude -p` is one-shot, so we
    # inline the prior output into the new prompt instead.)
    if len(description) > _MAX_DESCRIPTION_CHARS:
        description = _shorten_over_limit(description, prompt, params.model, transcript)

    transcript["final_description"] = description

    if params.log_dir:
        params.log_dir.mkdir(parents=True, exist_ok=True)
        log_file = params.log_dir / f"improve_iter_{params.iteration or 'unknown'}.json"
        log_file.write_text(json.dumps(transcript, indent=2))

    return description


def main() -> None:
    """Improve a skill description from command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Improve a skill description based on eval results",
    )
    parser.add_argument(
        "--eval-results",
        required=True,
        help="Path to eval results JSON (from run_eval.py)",
    )
    parser.add_argument("--skill-path", required=True, help="Path to skill directory")
    parser.add_argument(
        "--history",
        default=None,
        help="Path to history JSON (previous attempts)",
    )
    parser.add_argument("--model", required=True, help="Model for improvement")
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print thinking to stderr",
    )
    args = parser.parse_args()

    skill_path = Path(args.skill_path)
    if not (skill_path / "SKILL.md").exists():
        print(f"Error: No SKILL.md found at {skill_path}", file=sys.stderr)
        sys.exit(1)

    eval_results = json.loads(Path(args.eval_results).read_text())
    history = []
    if args.history:
        history = json.loads(Path(args.history).read_text())

    name, _, content = parse_skill_md(skill_path)
    current_description = eval_results["description"]

    if args.verbose:
        print(f"Current: {current_description}", file=sys.stderr)
        summary = eval_results["summary"]
        print(f"Score: {summary['passed']}/{summary['total']}", file=sys.stderr)
    new_description = improve_description(
        ImproveParams(
            skill_name=name,
            skill_content=content,
            current_description=current_description,
            eval_results=eval_results,
            history=history,
            model=args.model,
        )
    )

    if args.verbose:
        print(f"Improved: {new_description}", file=sys.stderr)

    # Output as JSON with both the new description and updated history
    output = {
        "description": new_description,
        "history": [
            *history,
            {
                "description": current_description,
                "passed": eval_results["summary"]["passed"],
                "failed": eval_results["summary"]["failed"],
                "total": eval_results["summary"]["total"],
                "results": eval_results["results"],
            },
        ],
    }
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
