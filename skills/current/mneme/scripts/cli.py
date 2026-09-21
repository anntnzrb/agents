# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""CLI entrypoint for Mneme meeting intelligence skill."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


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
    else:
        return proc.returncode


def handle_search(args: argparse.Namespace) -> int:
    """Handle search via qmd (hybrid by default, or exact BM25)."""
    if args.exact:
        cmd_args = ["search", args.query]
        if args.collection:
            cmd_args.extend(["-c", args.collection])
        if args.limit:
            cmd_args.extend(["-n", str(args.limit)])
        if args.json:
            cmd_args.extend(["--format", "json"])
        return run_qmd_command(cmd_args)

    cmd_args = ["query", args.query]
    if args.collection:
        cmd_args.extend(["-c", args.collection])
    if args.limit:
        cmd_args.extend(["-n", str(args.limit)])
    if args.json:
        cmd_args.extend(["--format", "json"])
    if args.no_rerank:
        cmd_args.append("--no-rerank")
    return run_qmd_command(cmd_args)


def handle_get(args: argparse.Namespace) -> int:
    """Handle snippet retrieval via qmd get."""
    cmd_args = ["get", args.target]
    return run_qmd_command(cmd_args)


def handle_denoise_stub(args: argparse.Namespace) -> int:
    """Validate denoise input file presence and output path."""
    input_path = Path(args.input_file)
    if not input_path.exists():
        sys.stderr.write(f"Error: Input file not found: {input_path}\n")
        return 2
    output_path = Path(args.output) if args.output else None
    target_name = output_path or "stdout"
    sys.stdout.write(
        f"Ready to denoise '{input_path}' losslessly. Target output: '{target_name}'.\n"
        f"Apply guidelines from references/lossless-cleaning.md.\n"
    )
    return 0


def handle_synthesize_stub(args: argparse.Namespace) -> int:
    """Validate synthesize input file presence."""
    input_path = Path(args.input_file)
    if not input_path.exists():
        sys.stderr.write(f"Error: Input file not found: {input_path}\n")
        return 2
    sum_t = args.summary or "none"
    task_t = args.tasks or "none"
    sys.stdout.write(
        f"Ready to synthesize '{input_path}'.\n"
        f"Summary target: '{sum_t}', Tasks target: '{task_t}'.\n"
        f"Apply schemas from references/spec-synthesis.md.\n"
    )
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
        "denoise", help="Validate and prepare lossless transcript denoising"
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
        return handle_denoise_stub(args)
    if args.command == "synthesize":
        return handle_synthesize_stub(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
