# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""CLI entrypoint for Mneme meeting intelligence skill."""

import argparse
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path


class MnemeArgs(argparse.Namespace):
    """Parsed command-line arguments for Mneme."""

    command: str | None = None
    query: str = ""
    collection: str | None = None
    limit: int = 5
    exact: bool = False
    no_rerank: bool = False
    json: bool = False
    target: str = ""
    input_file: str = ""
    output: str | None = None
    raw_file: str = ""
    clean_file: str = ""


# Regular expressions for lossless transcript denoising
# Letters only: repeated numbers such as "10, 10" can be real data.
_STUTTER_RE = re.compile(r"\b([^\W\d_]+)(?:[,\s]+\1\b)+", re.IGNORECASE)
# Cut-off word fragment followed by the full word: "escri- escribir".
_FALSE_START_RE = re.compile(r"\b([^\W\d_]{1,10})-\s*(?=\1)", re.IGNORECASE)
# Hyphen guards keep acknowledgements such as "Mm-hmm" intact.
_FILLERS = (
    "um",
    "uh",
    "er",
    "ah",
    "eh",
    "hmm",
    r"like,\s*you know",
    "you know what i mean",
    r"este\.\.\.",
    r"o sea,\s*o sea",
    r"tipo,\s*tipo",
)
_FILLER_RE = re.compile(
    rf"(?<![\w-])(?:{'|'.join(_FILLERS)})(?:\.\.\.)?(?![\w-]),?\s*",
    re.IGNORECASE,
)
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([,.;:?!])")
_REPEATED_COMMA_RE = re.compile(r",(?:\s*,)+")
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*")
_CLEAN_LABEL_RE = re.compile(r"^\*\*[^*\n]+:\*\*\s*$")
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
        _ = sys.stderr.write("Error: 'qmd' binary not found on PATH.\n")
        return 127
    cmd = ["qmd", *args]
    try:
        proc = subprocess.run(cmd, check=False)
    except OSError as exc:
        _ = sys.stderr.write(f"Error executing qmd: {exc}\n")
        return 1
    return proc.returncode


def handle_search(args: MnemeArgs) -> int:
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


def handle_get(args: MnemeArgs) -> int:
    """Handle snippet retrieval via qmd get preserving literal target."""
    cmd_args = ["get", "--", args.target]
    return run_qmd_command(cmd_args)


def denoise_line_text(line: str) -> str:
    """Remove repetitive stutter loops and verbal fillers from a line."""
    denoised = line
    while (step := _FALSE_START_RE.sub("", denoised)) != denoised:
        denoised = step
    denoised = _STUTTER_RE.sub(r"\1", denoised)
    denoised = _FILLER_RE.sub("", denoised)
    denoised = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", denoised)
    denoised = _REPEATED_COMMA_RE.sub(",", denoised)
    return re.sub(r"[ \t]+", " ", denoised).strip().lstrip(",;: ")


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


def handle_denoise(args: MnemeArgs) -> int:
    """Clean raw transcript losslessly and write to output file or stdout."""
    input_path = Path(args.input_file)
    if not input_path.exists():
        _ = sys.stderr.write(f"Error: Input file not found: {input_path}\n")
        return 2

    try:
        raw_text = input_path.read_text(encoding="utf-8")
    except OSError as exc:
        _ = sys.stderr.write(f"Error reading '{input_path}': {exc}\n")
        return 1

    cleaned_text = clean_text_lossless(raw_text)

    if args.output:
        out_path = Path(args.output)
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            _ = out_path.write_text(cleaned_text, encoding="utf-8")
        except OSError as exc:
            _ = sys.stderr.write(f"Error writing '{out_path}': {exc}\n")
            return 1
    else:
        _ = sys.stdout.write(cleaned_text)

    return 0


def count_numbers(text: str, *, clean: bool) -> Counter[str]:
    """Count number tokens in dialogue text, ignoring speaker labels."""
    counts: Counter[str] = Counter()
    for line in text.splitlines():
        if clean:
            if _CLEAN_LABEL_RE.match(line.strip()):
                continue
            body = line
        else:
            match = _SPEAKER_RE.match(line.strip())
            body = match.group(3) if match else line
        counts.update(_NUMBER_RE.findall(body))
    return counts


def handle_verify(args: MnemeArgs) -> int:
    """Report numbers present in the raw transcript but missing from the clean one."""
    texts: list[str] = []
    for name in (args.raw_file, args.clean_file):
        path = Path(name)
        try:
            texts.append(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            _ = sys.stderr.write(f"Error: Input file not found: {path}\n")
            return 2
        except OSError as exc:
            _ = sys.stderr.write(f"Error reading '{path}': {exc}\n")
            return 1
    missing = count_numbers(texts[0], clean=False) - count_numbers(texts[1], clean=True)
    if not missing:
        _ = sys.stdout.write("OK: every number in the raw transcript is preserved.\n")
        return 0
    _ = sys.stdout.write("MISSING numbers (token: count):\n")
    for token, count in sorted(missing.items()):
        _ = sys.stdout.write(f"  {token}: {count}\n")
    return 1


def build_parser() -> argparse.ArgumentParser:
    """Construct command-line parser."""
    parser = argparse.ArgumentParser(
        prog="mneme",
        description="Mneme: lossless transcript cleaning and QMD search.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    search_p = subparsers.add_parser(
        "search", help="Execute search across knowledge base (hybrid or exact)"
    )
    _ = search_p.add_argument("query", help="Search query string")
    _ = search_p.add_argument("-c", "--collection", help="Collection name")
    _ = search_p.add_argument("-n", "--limit", type=int, default=5, help="Result limit")
    _ = search_p.add_argument(
        "--exact",
        action="store_true",
        help="Execute exact BM25 keyword search instead of hybrid search",
    )
    _ = search_p.add_argument(
        "--no-rerank",
        action="store_true",
        help="Disable LLM reranking in hybrid search",
    )
    _ = search_p.add_argument(
        "--json",
        action="store_true",
        help="Output results in JSON format",
    )
    get_p = subparsers.add_parser(
        "get", help="Retrieve line-ranged snippet by docid or path"
    )
    _ = get_p.add_argument(
        "target", help="Document target (e.g. #docid:line:count or path)"
    )

    denoise_p = subparsers.add_parser(
        "denoise", help="Execute lossless transcript denoising"
    )
    _ = denoise_p.add_argument("input_file", help="Path to raw transcript file")
    _ = denoise_p.add_argument("-o", "--output", help="Path for cleaned output file")

    verify_p = subparsers.add_parser(
        "verify", help="Check that a clean transcript kept every raw number"
    )
    _ = verify_p.add_argument("raw_file", help="Path to raw transcript file")
    _ = verify_p.add_argument("clean_file", help="Path to cleaned transcript file")
    return parser


def main() -> int:
    """Execute main entrypoint."""
    parser = build_parser()
    args = parser.parse_args(namespace=MnemeArgs())
    if args.command == "search":
        return handle_search(args)
    if args.command == "get":
        return handle_get(args)
    if args.command == "denoise":
        return handle_denoise(args)
    if args.command == "verify":
        return handle_verify(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
