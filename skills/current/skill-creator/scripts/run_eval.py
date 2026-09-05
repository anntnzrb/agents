#!/usr/bin/env -S uv run --script
# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Run trigger evaluation for a skill description.

Tests whether a skill's description causes Claude to trigger (read the skill)
for a set of queries. Outputs results as JSON.
"""

import argparse
import json
import os
import select
import subprocess
import sys
import time
import uuid
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.utils import parse_skill_md


@dataclass(frozen=True, slots=True)
class QueryConfig:
    """Fixed context for a single trigger-eval query run."""

    skill_name: str
    skill_description: str
    timeout: int
    project_root: str
    model: str | None = None


@dataclass(frozen=True, slots=True)
class EvalParams:
    """Full eval-set run configuration."""

    eval_set: list[dict]
    skill_name: str
    description: str
    num_workers: int
    timeout: int
    project_root: Path
    runs_per_query: int = 1
    trigger_threshold: float = 0.5
    model: str | None = None


def find_project_root() -> Path:
    """Find the project root by walking up from cwd looking for .claude/.

    Mimics how Claude Code discovers its project root, so the command file
    we create ends up where claude -p will look for it.
    """
    current = Path.cwd()
    for parent in [current, *current.parents]:
        if (parent / ".claude").is_dir():
            return parent
    return current


class _StreamTracker:
    """Accumulate stream-event state while watching for the probe skill."""

    def __init__(self) -> None:
        """Initialize empty tracking state."""
        self.pending_tool_name: str | None = None
        self.accumulated_json = ""

    def feed(self, event: dict, clean_name: str) -> bool | None:
        """Feed one stream event; True/False on decision, None to continue."""
        if event.get("type") != "stream_event":
            return None
        se = event.get("event", {})
        se_type = se.get("type", "")
        if se_type == "content_block_start":
            return self._block_started(se)
        if se_type == "content_block_delta" and self.pending_tool_name:
            return self._block_delta(se, clean_name)
        if se_type in ("content_block_stop", "message_stop"):
            return self._block_stopped(se_type, clean_name)
        return None

    def _block_started(self, se: dict) -> bool | None:
        """Track a content block start; False on an unrelated tool call."""
        cb = se.get("content_block", {})
        if cb.get("type") != "tool_use":
            return None
        tool_name = cb.get("name", "")
        if tool_name in ("Skill", "Read"):
            self.pending_tool_name = tool_name
            self.accumulated_json = ""
            return None
        return False

    def _block_delta(self, se: dict, clean_name: str) -> bool | None:
        """Accumulate partial input JSON; True once the probe name appears."""
        delta = se.get("delta", {})
        if delta.get("type") != "input_json_delta":
            return None
        self.accumulated_json += delta.get("partial_json", "")
        if clean_name in self.accumulated_json:
            return True
        return None

    def _block_stopped(self, se_type: str, clean_name: str) -> bool | None:
        """Decide at block/message stop; None when nothing was pending."""
        if not self.pending_tool_name:
            if se_type == "message_stop":
                return False
            return None
        return clean_name in self.accumulated_json


def _check_assistant_message(event: dict, clean_name: str) -> bool | None:
    """Check a full assistant message for probe-skill tool use."""
    if event.get("type") != "assistant":
        return None
    message = event.get("message", {})
    for content_item in message.get("content", []):
        if content_item.get("type") != "tool_use":
            continue
        tool_name = content_item.get("name", "")
        tool_input = content_item.get("input", {})
        skill_hit = tool_name == "Skill" and clean_name in tool_input.get("skill", "")
        read_hit = tool_name == "Read" and clean_name in tool_input.get("file_path", "")
        return skill_hit or read_hit
    return None


def _handle_stream_line(
    line: str, tracker: _StreamTracker, clean_name: str
) -> bool | None:
    """Parse one stream line; True/False on decision, None to continue."""
    text = line.strip()
    if not text:
        return None
    try:
        event = json.loads(text)
    except json.JSONDecodeError:
        return None
    if event.get("type") == "result":
        return False
    decision = tracker.feed(event, clean_name)
    if decision is not None:
        return decision
    return _check_assistant_message(event, clean_name)


def _command_content(skill_name: str, skill_description: str) -> str:
    """Render the probe command file content."""
    # Use YAML block scalar to avoid breaking on quotes in description
    indented_desc = "\n  ".join(skill_description.split("\n"))
    return (
        "---\n"
        "description: |\n"
        f"  {indented_desc}\n"
        "---\n\n"
        f"# {skill_name}\n\n"
        f"This skill handles: {skill_description}\n"
    )


def _watch_stream(
    process: subprocess.Popen[bytes], clean_name: str, timeout: int
) -> bool:
    """Watch claude -p stream output until the trigger decision is known."""
    stdout = process.stdout
    if stdout is None:
        return False
    tracker = _StreamTracker()
    start_time = time.time()
    buffer = ""
    try:
        while time.time() - start_time < timeout:
            if process.poll() is not None:
                remaining = stdout.read()
                if remaining:
                    buffer += remaining.decode("utf-8", errors="replace")
                break
            ready, _, _ = select.select([stdout], [], [], 1.0)
            if not ready:
                continue
            chunk = os.read(stdout.fileno(), 8192)
            if not chunk:
                break
            buffer += chunk.decode("utf-8", errors="replace")
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                decision = _handle_stream_line(line, tracker, clean_name)
                if decision is not None:
                    return decision
    finally:
        # Clean up process on any exit path (return, exception, timeout)
        if process.poll() is None:
            process.kill()
            process.wait()
    return False


def run_single_query(query: str, config: QueryConfig) -> bool:
    """Run a single query and return whether the skill was triggered.

    Creates a command file in .claude/commands/ so it appears in Claude's
    available_skills list, then runs `claude -p` with the raw query.
    Uses --include-partial-messages to detect triggering early from
    stream events (content_block_start) rather than waiting for the
    full assistant message, which only arrives after tool execution.
    """
    unique_id = uuid.uuid4().hex[:8]
    clean_name = f"{config.skill_name}-skill-{unique_id}"
    project_commands_dir = Path(config.project_root) / ".claude" / "commands"
    command_file = project_commands_dir / f"{clean_name}.md"

    try:
        project_commands_dir.mkdir(parents=True, exist_ok=True)
        command_file.write_text(
            _command_content(config.skill_name, config.skill_description)
        )

        cmd = [
            "claude",
            "-p",
            query,
            "--output-format",
            "stream-json",
            "--verbose",
            "--include-partial-messages",
        ]
        if config.model:
            cmd.extend(["--model", config.model])

        # Remove CLAUDECODE env var to allow nesting claude -p inside a
        # Claude Code session. The guard is for interactive terminal conflicts;
        # programmatic subprocess usage is safe.
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

        # Fixed argv, no shell: query/model come from local eval files.
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=config.project_root,
            env=env,
        )
        return _watch_stream(process, clean_name, config.timeout)
    finally:
        if command_file.exists():
            command_file.unlink()


def run_eval(params: EvalParams) -> dict:
    """Run the full eval set and return results."""
    results = []
    query_config = QueryConfig(
        skill_name=params.skill_name,
        skill_description=params.description,
        timeout=params.timeout,
        project_root=str(params.project_root),
        model=params.model,
    )

    with ProcessPoolExecutor(max_workers=params.num_workers) as executor:
        future_to_info = {}
        for item in params.eval_set:
            for run_idx in range(params.runs_per_query):
                future = executor.submit(
                    run_single_query,
                    item["query"],
                    query_config,
                )
                future_to_info[future] = (item, run_idx)

        query_triggers: dict[str, list[bool]] = {}
        query_items: dict[str, dict] = {}
        for future in as_completed(future_to_info):
            item, _ = future_to_info[future]
            query = item["query"]
            query_items[query] = item
            if query not in query_triggers:
                query_triggers[query] = []
            try:
                query_triggers[query].append(future.result())
            except Exception as e:
                print(f"Warning: query failed: {e}", file=sys.stderr)
                query_triggers[query].append(False)

    for query, triggers in query_triggers.items():
        item = query_items[query]
        trigger_rate = sum(triggers) / len(triggers)
        should_trigger = item["should_trigger"]
        if should_trigger:
            did_pass = trigger_rate >= params.trigger_threshold
        else:
            did_pass = trigger_rate < params.trigger_threshold
        results.append(
            {
                "query": query,
                "should_trigger": should_trigger,
                "trigger_rate": trigger_rate,
                "triggers": sum(triggers),
                "runs": len(triggers),
                "pass": did_pass,
            },
        )

    passed = sum(1 for r in results if r["pass"])
    total = len(results)

    return {
        "skill_name": params.skill_name,
        "description": params.description,
        "results": results,
        "summary": {
            "total": total,
            "passed": passed,
            "failed": total - passed,
        },
    }


def main() -> None:
    """Run trigger evaluation from command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Run trigger evaluation for a skill description",
    )
    parser.add_argument("--eval-set", required=True, help="Path to eval set JSON file")
    parser.add_argument("--skill-path", required=True, help="Path to skill directory")
    parser.add_argument(
        "--description",
        default=None,
        help="Override description to test",
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
        "--model",
        default=None,
        help="Model to use for claude -p (default: user's configured model)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print progress to stderr",
    )
    args = parser.parse_args()

    eval_set = json.loads(Path(args.eval_set).read_text())
    skill_path = Path(args.skill_path)

    if not (skill_path / "SKILL.md").exists():
        print(f"Error: No SKILL.md found at {skill_path}", file=sys.stderr)
        sys.exit(1)

    name, original_description, _ = parse_skill_md(skill_path)
    description = args.description or original_description
    project_root = find_project_root()

    if args.verbose:
        print(f"Evaluating: {description}", file=sys.stderr)

    output = run_eval(
        EvalParams(
            eval_set=eval_set,
            skill_name=name,
            description=description,
            num_workers=args.num_workers,
            timeout=args.timeout,
            project_root=project_root,
            runs_per_query=args.runs_per_query,
            trigger_threshold=args.trigger_threshold,
            model=args.model,
        )
    )

    if args.verbose:
        summary = output["summary"]
        print(
            f"Results: {summary['passed']}/{summary['total']} passed",
            file=sys.stderr,
        )
        for r in output["results"]:
            status = "PASS" if r["pass"] else "FAIL"
            rate_str = f"{r['triggers']}/{r['runs']}"
            expected = r["should_trigger"]
            query = r["query"][:70]
            detail = f"[{status}] rate={rate_str} expected={expected}: {query}"
            print(f"  {detail}", file=sys.stderr)

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
