#!/usr/bin/env -S uv run --script
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
from concurrent.futures import Future, ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import cast

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.utils import parse_skill_md


class StreamState:
    """State for stream event detection during single query execution."""

    def __init__(self) -> None:
        """Initialize stream tracking state."""
        self.pending_tool_name: str | None = None
        self.accumulated_json: str = ""


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


def _handle_content_block_start(
    cb: object,
    state: StreamState,
) -> bool | None:
    """Handle content_block_start event."""
    if isinstance(cb, dict):
        cb_dict = cast("dict[str, object]", cb)
        if cb_dict.get("type") == "tool_use":
            tool_name = cb_dict.get("name")
            if tool_name in ("Skill", "Read"):
                state.pending_tool_name = str(tool_name)
                state.accumulated_json = ""
            else:
                return False
    return None


def _handle_content_block_delta(
    delta: object,
    state: StreamState,
    clean_name: str,
) -> bool | None:
    """Handle content_block_delta event."""
    if isinstance(delta, dict):
        delta_dict = cast("dict[str, object]", delta)
        if delta_dict.get("type") == "input_json_delta":
            partial = delta_dict.get("partial_json")
            if isinstance(partial, str):
                state.accumulated_json += partial
                if clean_name in state.accumulated_json:
                    return True
    return None


def _handle_stream_event(
    event_data: dict[str, object],
    state: StreamState,
    clean_name: str,
) -> bool | None:
    """Process a stream_event object and return trigger decision or None."""
    se = event_data.get("event")
    if not isinstance(se, dict):
        return None
    se_dict = cast("dict[str, object]", se)
    se_type = se_dict.get("type")

    if se_type == "content_block_start":
        return _handle_content_block_start(se_dict.get("content_block"), state)
    if se_type == "content_block_delta" and state.pending_tool_name:
        return _handle_content_block_delta(se_dict.get("delta"), state, clean_name)
    if se_type in ("content_block_stop", "message_stop"):
        if state.pending_tool_name:
            return clean_name in state.accumulated_json
        if se_type == "message_stop":
            return False

    return None


def _handle_assistant_event(
    event_data: dict[str, object],
    clean_name: str,
) -> bool | None:
    """Process an assistant event and return trigger decision or None."""
    message = event_data.get("message")
    if not isinstance(message, dict):
        return None
    message_dict = cast("dict[str, object]", message)
    content = message_dict.get("content")
    if not isinstance(content, list):
        return None
    content_list = cast("list[object]", content)
    for content_item in content_list:
        if not isinstance(content_item, dict):
            continue
        item_dict = cast("dict[str, object]", content_item)
        if item_dict.get("type") != "tool_use":
            continue
        tool_name = str(item_dict.get("name", ""))
        tool_input = item_dict.get("input")
        input_dict = (
            cast("dict[str, object]", tool_input)
            if isinstance(tool_input, dict)
            else {}
        )
        is_skill = tool_name == "Skill" and clean_name in str(
            input_dict.get("skill", "")
        )
        is_read = tool_name == "Read" and clean_name in str(
            input_dict.get("file_path", "")
        )
        return is_skill or is_read
    return None


def _process_stream_line(
    line: str,
    state: StreamState,
    clean_name: str,
    current_triggered: bool,
) -> tuple[bool | None, bool]:
    """Process a single JSON stream line.

    Returns:
        A tuple of (decision_or_none, updated_triggered).
    """
    try:
        raw_event = cast("object", json.loads(line))
    except json.JSONDecodeError:
        return None, current_triggered

    if not isinstance(raw_event, dict):
        return None, current_triggered

    event_dict = cast("dict[str, object]", raw_event)
    event_type = event_dict.get("type")

    if event_type == "stream_event":
        decision = _handle_stream_event(event_dict, state, clean_name)
        if decision is not None:
            return decision, current_triggered
    elif event_type == "assistant":
        decision = _handle_assistant_event(event_dict, clean_name)
        if decision is not None:
            return decision, decision
    elif event_type == "result":
        return current_triggered, current_triggered

    return None, current_triggered


def _create_skill_command_file(
    project_root: str,
    skill_name: str,
    skill_description: str,
    clean_name: str,
) -> Path:
    """Create temporary skill command file in project .claude/commands/."""
    project_commands_dir = Path(project_root) / ".claude" / "commands"
    command_file = project_commands_dir / f"{clean_name}.md"
    project_commands_dir.mkdir(parents=True, exist_ok=True)
    # Use YAML block scalar to avoid breaking on quotes in description
    indented_desc = "\n  ".join(skill_description.split("\n"))
    command_content = (
        f"---\n"
        f"description: |\n"
        f"  {indented_desc}\n"
        f"---\n\n"
        f"# {skill_name}\n\n"
        f"This skill handles: {skill_description}\n"
    )
    _ = command_file.write_text(command_content, encoding="utf-8")
    return command_file


def _read_subprocess_stream(
    process: subprocess.Popen[bytes],
    timeout: int,
    clean_name: str,
) -> bool:
    """Read stream output from claude process until timeout or completion."""
    stdout = process.stdout
    if stdout is None:
        return False

    triggered = False
    start_time = time.time()
    buffer = ""
    state = StreamState()

    while time.time() - start_time < timeout:
        if process.poll() is not None:
            remaining = cast("bytes", stdout.read())
            if remaining:
                buffer += remaining.decode("utf-8", errors="replace")
            break
        ready, _, _ = select.select([stdout], [], [], 1.0)
        if not ready:
            continue

        chunk: bytes = os.read(stdout.fileno(), 8192)
        if not chunk:
            break
        buffer += chunk.decode("utf-8", errors="replace")

        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            line = line.strip()
            if not line:
                continue

            early_return, triggered = _process_stream_line(
                line, state, clean_name, triggered
            )
            if early_return is not None:
                return early_return

    return triggered


def run_single_query(  # noqa: PLR0913, PLR0917 - Preserved helper signature for executor
    query: str,
    skill_name: str,
    skill_description: str,
    timeout: int,
    project_root: str,
    model: str | None = None,
) -> bool:
    """Run a single query and return whether the skill was triggered.

    Creates a command file in .claude/commands/ so it appears in Claude's
    available_skills list, then runs `claude -p` with the raw query.
    Uses --include-partial-messages to detect triggering early from
    stream events (content_block_start) rather than waiting for the
    full assistant message, which only arrives after tool execution.
    """
    unique_id = uuid.uuid4().hex[:8]
    clean_name = f"{skill_name}-skill-{unique_id}"
    command_file = _create_skill_command_file(
        project_root, skill_name, skill_description, clean_name
    )

    try:
        cmd = [
            "claude",
            "-p",
            query,
            "--output-format",
            "stream-json",
            "--verbose",
            "--include-partial-messages",
        ]
        if model:
            cmd.extend(["--model", model])

        # Remove CLAUDECODE env var to allow nesting claude -p inside a
        # Claude Code session. The guard is for interactive terminal conflicts;
        # programmatic subprocess usage is safe.
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

        process = subprocess.Popen(  # noqa: S603 - Trusted command list for claude CLI evaluation
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=project_root,
            env=env,
        )

        try:
            return _read_subprocess_stream(process, timeout, clean_name)
        finally:
            # Clean up process on any exit path (return, exception, timeout)
            if process.poll() is None:
                process.kill()
                _ = process.wait()
    finally:
        if command_file.exists():
            command_file.unlink()


def run_eval(  # noqa: PLR0913, PLR0917 - Preserved public function signature
    eval_set: list[dict[str, object]],
    skill_name: str,
    description: str,
    num_workers: int,
    timeout: int,
    project_root: Path,
    runs_per_query: int = 1,
    trigger_threshold: float = 0.5,
    model: str | None = None,
) -> dict[str, object]:
    """Run the full eval set and return results."""
    results: list[dict[str, object]] = []

    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        future_to_info: dict[Future[bool], tuple[dict[str, object], int]] = {}
        for item in eval_set:
            query_str = str(item["query"])
            for run_idx in range(runs_per_query):
                future = executor.submit(
                    run_single_query,
                    query_str,
                    skill_name,
                    description,
                    timeout,
                    str(project_root),
                    model,
                )
                future_to_info[future] = (item, run_idx)

        query_triggers: dict[str, list[bool]] = {}
        query_items: dict[str, dict[str, object]] = {}
        for future in as_completed(future_to_info):
            item, _ = future_to_info[future]
            query = str(item["query"])
            query_items[query] = item
            if query not in query_triggers:
                query_triggers[query] = []
            try:
                query_triggers[query].append(future.result())
            except Exception as e:  # noqa: BLE001 - Query execution failure in worker process
                print(f"Warning: query failed: {e}", file=sys.stderr)
                query_triggers[query].append(False)

    for query, triggers in query_triggers.items():
        item = query_items[query]
        trigger_rate = sum(triggers) / len(triggers)
        should_trigger = bool(item.get("should_trigger", False))
        if should_trigger:
            did_pass = trigger_rate >= trigger_threshold
        else:
            did_pass = trigger_rate < trigger_threshold
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

    passed = sum(1 for r in results if bool(r["pass"]))
    total = len(results)

    return {
        "skill_name": skill_name,
        "description": description,
        "results": results,
        "summary": {
            "total": total,
            "passed": passed,
            "failed": total - passed,
        },
    }


def main() -> None:
    """Run trigger evaluation CLI."""
    parser = argparse.ArgumentParser(
        description="Run trigger evaluation for a skill description",
    )
    _ = parser.add_argument(
        "--eval-set", required=True, help="Path to eval set JSON file"
    )
    _ = parser.add_argument(
        "--skill-path", required=True, help="Path to skill directory"
    )
    _ = parser.add_argument(
        "--description",
        default=None,
        help="Override description to test",
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
        "--model",
        default=None,
        help="Model to use for claude -p (default: user's configured model)",
    )
    _ = parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print progress to stderr",
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

    name, original_description, _ = parse_skill_md(skill_path)
    description = (
        str(args_map["description"])
        if args_map.get("description") is not None
        else original_description
    )
    num_workers = int(str(args_map["num_workers"]))
    timeout = int(str(args_map["timeout"]))
    runs_per_query = int(str(args_map["runs_per_query"]))
    trigger_threshold = float(str(args_map["trigger_threshold"]))
    model = str(args_map["model"]) if args_map.get("model") is not None else None
    verbose = bool(args_map.get("verbose", False))

    project_root = find_project_root()

    if verbose:
        print(f"Evaluating: {description}", file=sys.stderr)

    output = run_eval(
        eval_set=eval_set,
        skill_name=name,
        description=description,
        num_workers=num_workers,
        timeout=timeout,
        project_root=project_root,
        runs_per_query=runs_per_query,
        trigger_threshold=trigger_threshold,
        model=model,
    )

    if verbose:
        summary = cast("dict[str, int]", output["summary"])
        print(
            f"Results: {summary['passed']}/{summary['total']} passed",
            file=sys.stderr,
        )
        results_list = cast("list[dict[str, object]]", output["results"])
        for r in results_list:
            status = "PASS" if bool(r["pass"]) else "FAIL"
            rate_str = f"{r['triggers']}/{r['runs']}"
            query_preview = str(r["query"])[:70]
            print(
                f"  [{status}] rate={rate_str} expected={r['should_trigger']}: "
                + query_preview,
                file=sys.stderr,
            )

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
