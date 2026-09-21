# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""CLI entrypoint for Mneme meeting intelligence skill."""

from __future__ import annotations

import argparse
import datetime
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

_MIN_DECISION_LEN = 20
_MIN_TASK_LEN = 25
_MAX_DECISIONS = 5
_MAX_TASKS = 10
_HIGH_PRIO_CUTOFF = 2

# Regular expressions for lossless transcript denoising
_STUTTER_RE = re.compile(r"\b(\w+)(?:[,\s]+\1\b)+", re.IGNORECASE)
_FILLER_EN_RE = re.compile(
    r"\b(?:um|uh|er|ah|like,\s*you know|you know what i mean)\b", re.IGNORECASE
)
_FILLER_ES_RE = re.compile(
    r"\b(?:este\.\.\.|o sea,\s*o sea|tipo,\s*tipo|eh\.\.\.)\b", re.IGNORECASE
)
_SPEAKER_RE = re.compile(r"^(?:\[?([^:\n]+?)\]?|\*\*([^:\n]+?)\*\*):\s*(.*)$")


def normalize_speaker(name: str) -> str:
    """Normalize speaker name by stripping trailing annotations such as (You)."""
    cleaned = re.sub(r"\s*\((?:You|Tú|Host|Guest)\)\s*$", "", name, flags=re.IGNORECASE)
    return cleaned.strip()


def check_qmd_available() -> bool:
    """Check if qmd binary is available on PATH."""
    return shutil.which("qmd") is not None


def run_qmd_command(args: list[str]) -> int:
    """Execute a qmd command directly via subprocess."""
    if not check_qmd_available():
        sys.stderr.write("Error: 'qmd' binary not found on PATH.\n")
        return 127
    cmd = ["qmd", *args]
    try:
        proc = subprocess.run(cmd, check=False)  # noqa: S603
    except OSError as exc:
        sys.stderr.write(f"Error executing qmd: {exc}\n")
        return 1
    return proc.returncode


def handle_search(args: argparse.Namespace) -> int:
    """Handle search via qmd (hybrid or exact BM25) preserving literal queries."""
    if args.exact:
        cmd_args = ["search"]
        if args.collection:
            cmd_args.extend(["-c", args.collection])
        if args.limit:
            cmd_args.extend(["-n", str(args.limit)])
        if args.json:
            cmd_args.extend(["--format", "json"])
        cmd_args.extend(["--", args.query])
        return run_qmd_command(cmd_args)

    cmd_args = ["query"]
    if args.collection:
        cmd_args.extend(["-c", args.collection])
    if args.limit:
        cmd_args.extend(["-n", str(args.limit)])
    if args.json:
        cmd_args.extend(["--format", "json"])
    if args.no_rerank:
        cmd_args.append("--no-rerank")
    cmd_args.extend(["--", args.query])
    return run_qmd_command(cmd_args)


def handle_get(args: argparse.Namespace) -> int:
    """Handle snippet retrieval via qmd get preserving literal target."""
    cmd_args = ["get", "--", args.target]
    return run_qmd_command(cmd_args)


def denoise_line_text(line: str) -> str:
    """Remove repetitive stutter loops and verbal fillers from a line."""
    denoised = _STUTTER_RE.sub(r"\1", line)
    denoised = _FILLER_EN_RE.sub("", denoised)
    denoised = _FILLER_ES_RE.sub("", denoised)
    return re.sub(r"[ \t]+", " ", denoised).strip()


def clean_text_lossless(raw_text: str) -> str:
    """Perform lossless transcript denoising preserving facts and turn order."""
    cleaned_blocks: list[str] = []
    current_speaker: str | None = None
    current_paragraphs: list[str] = []

    def flush() -> None:
        nonlocal current_speaker, current_paragraphs
        if current_paragraphs:
            content = " ".join(current_paragraphs).strip()
            if content:
                prefix = f"**{current_speaker}:**\n" if current_speaker else ""
                cleaned_blocks.append(f"{prefix}{content}")
        current_paragraphs = []

    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if match := _SPEAKER_RE.match(line):
            speaker_name = normalize_speaker(
                (match.group(1) or match.group(2) or "").strip()
            )
            rest = match.group(3).strip()
            if speaker_name != current_speaker:
                flush()
                current_speaker = speaker_name
            line = rest

        if line and (denoised := denoise_line_text(line)):
            current_paragraphs.append(denoised)

    flush()
    return "\n\n".join(cleaned_blocks).strip() + "\n"


def handle_denoise(args: argparse.Namespace) -> int:
    """Clean raw transcript losslessly and write to output file or stdout."""
    input_path = Path(args.input_file)
    if not input_path.exists():
        sys.stderr.write(f"Error: Input file not found: {input_path}\n")
        return 2

    try:
        raw_text = input_path.read_text(encoding="utf-8")
    except OSError as exc:
        sys.stderr.write(f"Error reading '{input_path}': {exc}\n")
        return 1

    cleaned_text = clean_text_lossless(raw_text)

    if args.output:
        out_path = Path(args.output)
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(cleaned_text, encoding="utf-8")
        except OSError as exc:
            sys.stderr.write(f"Error writing '{out_path}': {exc}\n")
            return 1
    else:
        sys.stdout.write(cleaned_text)

    return 0


def extract_executive_summary(transcript_text: str, title: str) -> str:
    """Generate structured markdown executive summary."""
    lines: list[str] = [
        f"# Executive Summary: {title}",
        "",
        "### Context and Objective",
        f"Synthesized review of technical items and agreements from {title}.",
        "",
        "### Key Decisions Agreed",
    ]

    # Extract sentences with decision keywords
    decision_keywords = (
        "agree",
        "decid",
        "acord",
        "defin",
        "rule",
        "aprob",
        "estándar",
        "standard",
    )
    decisions_found: list[str] = []

    for line in transcript_text.splitlines():
        trimmed = line.strip()
        if (
            any(kw in trimmed.lower() for kw in decision_keywords)
            and len(trimmed) > _MIN_DECISION_LEN
        ):
            decisions_found.append(trimmed)

    if decisions_found:
        lines.extend(f"- **Agreement**: {d}" for d in decisions_found[:_MAX_DECISIONS])
    else:
        lines.append(
            "- **General Alignment**: Core discussion points reviewed and verified."
        )

    lines.extend(
        [
            "",
            "### Commitments and Next Steps",
            "- **Next Action**: Execute deliverables according to project timelines.",
        ]
    )
    return "\n".join(lines) + "\n"


def extract_action_items(transcript_text: str, meeting_id: str) -> dict[str, Any]:
    """Extract structured JSON action items and engineering tasks."""
    now_utc = datetime.datetime.now(datetime.UTC).isoformat()
    tasks: list[dict[str, Any]] = []

    task_keywords = (
        "need to",
        "should",
        "will",
        "coordinat",
        "implement",
        "debe",
        "revisar",
        "tarea",
        "desplegar",
    )
    task_idx = 1

    for line in transcript_text.splitlines():
        trimmed = line.strip()
        if (
            any(kw in trimmed.lower() for kw in task_keywords)
            and len(trimmed) > _MIN_TASK_LEN
        ):
            tasks.append(
                {
                    "id": f"ACTION-{task_idx:02d}",
                    "title": trimmed[:120],
                    "owner": "Team",
                    "priority": "high" if task_idx <= _HIGH_PRIO_CUTOFF else "medium",
                    "context": trimmed,
                    "scope": [f"Execute item: {trimmed[:100]}"],
                    "completion_criteria": [f"Verified and completed: {trimmed[:100]}"],
                }
            )
            task_idx += 1
            if task_idx > _MAX_TASKS:
                break

    if not tasks:
        tasks.append(
            {
                "id": "ACTION-01",
                "title": f"Follow up on {meeting_id} meeting outcomes",
                "owner": "Team",
                "priority": "medium",
                "context": "General meeting follow-up and tracking.",
                "scope": ["Review meeting notes and verify upcoming deliverables."],
                "completion_criteria": ["All action items logged in tracker."],
            }
        )

    return {
        "meeting_id": meeting_id,
        "generated_at": now_utc,
        "tasks": tasks,
    }


def handle_synthesize(args: argparse.Namespace) -> int:
    """Synthesize executive summary and structured tasks from cleaned transcript."""
    input_path = Path(args.input_file)
    if not input_path.exists():
        sys.stderr.write(f"Error: Input file not found: {input_path}\n")
        return 2

    try:
        transcript_text = input_path.read_text(encoding="utf-8")
    except OSError as exc:
        sys.stderr.write(f"Error reading '{input_path}': {exc}\n")
        return 1

    title = input_path.stem
    meeting_id = title

    if args.summary:
        summary_md = extract_executive_summary(transcript_text, title)
        summary_path = Path(args.summary)
        try:
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            summary_path.write_text(summary_md, encoding="utf-8")
        except OSError as exc:
            sys.stderr.write(f"Error writing summary '{summary_path}': {exc}\n")
            return 1

    if args.tasks:
        tasks_data = extract_action_items(transcript_text, meeting_id)
        tasks_path = Path(args.tasks)
        try:
            tasks_path.parent.mkdir(parents=True, exist_ok=True)
            tasks_path.write_text(
                json.dumps(tasks_data, indent=2) + "\n", encoding="utf-8"
            )
        except OSError as exc:
            sys.stderr.write(f"Error writing tasks '{tasks_path}': {exc}\n")
            return 1

    if not args.summary and not args.tasks:
        summary_md = extract_executive_summary(transcript_text, title)
        sys.stdout.write(summary_md)

    return 0


def build_parser() -> argparse.ArgumentParser:
    """Construct command-line parser."""
    parser = argparse.ArgumentParser(
        prog="mneme",
        description="Mneme: meeting intelligence and QMD search.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    search_p = subparsers.add_parser(
        "search", help="Execute search across knowledge base (hybrid or exact)"
    )
    search_p.add_argument("query", help="Search query string")
    search_p.add_argument("-c", "--collection", help="Collection name")
    search_p.add_argument("-n", "--limit", type=int, default=5, help="Result limit")
    search_p.add_argument(
        "--exact",
        action="store_true",
        help="Execute exact BM25 keyword search instead of hybrid search",
    )
    search_p.add_argument(
        "--no-rerank",
        action="store_true",
        help="Disable LLM reranking in hybrid search",
    )
    search_p.add_argument(
        "--json",
        action="store_true",
        help="Output results in JSON format",
    )
    get_p = subparsers.add_parser(
        "get", help="Retrieve line-ranged snippet by docid or path"
    )
    get_p.add_argument(
        "target", help="Document target (e.g. #docid:line:count or path)"
    )

    denoise_p = subparsers.add_parser(
        "denoise", help="Execute lossless transcript denoising"
    )
    denoise_p.add_argument("input_file", help="Path to raw transcript file")
    denoise_p.add_argument("-o", "--output", help="Path for cleaned output file")

    synth_p = subparsers.add_parser(
        "synthesize", help="Synthesize executive summary and engineering tasks"
    )
    synth_p.add_argument("input_file", help="Path to cleaned transcript file")
    synth_p.add_argument("--summary", help="Path to save summary markdown")
    synth_p.add_argument("--tasks", help="Path to save tasks JSON")

    return parser


def main() -> int:
    """Execute main entrypoint."""
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "search":
        return handle_search(args)
    if args.command == "get":
        return handle_get(args)
    if args.command == "denoise":
        return handle_denoise(args)
    if args.command == "synthesize":
        return handle_synthesize(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
