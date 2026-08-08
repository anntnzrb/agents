# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Headless adapter for the installed OMP search CLI."""

# ruff: noqa: CPY001, D103
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


ANSI_RE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
OSC_RE = re.compile(r"\x1b\][^\x07]*(?:\x07|\x1b\\)")
HEADER_RE = re.compile(r"Web Search:\s*(?P<provider>.+?)\s+(?P<count>\d+)\s+sources?\b")
SOURCE_RE = re.compile(
    r"^[├└]─\s*(?P<title>.+?)\s+\((?P<domain>[^()]+)\)"
    r"(?:\s+·\s+(?P<age>.+))?$"
)
MORE_LINES_RE = re.compile(r"(?:…|\.\.\.)\s*\d+\s+more\s+lines")
SECRET_RE = re.compile(r"(?i)\bsk-[a-z0-9_-]{8,}\b")
ASSIGNMENT_SECRET_RE = re.compile(
    r"(?i)(\b[A-Z][A-Z0-9_]*(?:API_KEY|TOKEN|SECRET)\b\s*[=:]\s*)\S+"
)
AUTH_SECRET_RE = re.compile(r"(?i)(\bAuthorization\s*:\s*Bearer\s+)\S+")


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        message = "must be at least 1"
        raise argparse.ArgumentTypeError(message)
    return parsed


def positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        message = "must be greater than 0"
        raise argparse.ArgumentTypeError(message)
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run OMP search and emit an agent-shaped JSON envelope."
    )
    parser.add_argument("query", nargs="+", help="search query words")
    parser.add_argument(
        "--provider", help="OMP provider name; omit for automatic provider selection"
    )
    parser.add_argument("--recency", choices=("day", "week", "month", "year"))
    parser.add_argument("--limit", type=positive_int, help="maximum number of sources")
    parser.add_argument(
        "--full",
        action="store_true",
        help="request the complete OMP answer instead of compact output",
    )
    parser.add_argument(
        "--include-raw",
        action="store_true",
        help="include ANSI-stripped raw OMP output for debugging",
    )
    parser.add_argument(
        "--timeout",
        type=positive_float,
        default=300.0,
        help="outer timeout in seconds (default: 300)",
    )
    parser.add_argument(
        "--omp-bin",
        help="OMP executable path; defaults to OMP_BIN or omp on PATH",
    )
    return parser


def strip_terminal_controls(value: str) -> str:
    value = OSC_RE.sub("", value)
    value = ANSI_RE.sub("", value)
    return value.replace("\r\n", "\n").replace("\r", "\n")


def redact(value: str) -> str:
    value = SECRET_RE.sub("<redacted>", value)
    value = ASSIGNMENT_SECRET_RE.sub(r"\1<redacted>", value)
    return AUTH_SECRET_RE.sub(r"\1<redacted>", value)


def frame_content(line: str) -> str:
    content = line
    if "│" in content:
        content = content.split("│", 1)[1]
        if "│" in content:
            content = content.rsplit("│", 1)[0]
    content = content.removeprefix(" ")
    return content.rstrip()


def parse_search_output(  # noqa: C901, PLR0912
    raw: str, fallback_query: str
) -> dict[str, object]:
    cleaned = strip_terminal_controls(raw)
    lines = cleaned.splitlines()
    provider: str | None = None
    actual_query = fallback_query
    answer_lines: list[str] = []
    sources: list[dict[str, str | None]] = []
    section: str | None = None
    started = False

    for line in lines:
        header = HEADER_RE.search(line)
        if header:
            provider = header.group("provider").strip()
            started = True
            continue
        if not started:
            continue
        if "├───" in line:
            section_match = re.search(r"├───\s*(Answer|Sources|Metadata)\b", line)
            if section_match:
                section = section_match.group(1).lower()
                continue
        if "╰───" in line:
            break

        content = frame_content(line)
        if content.startswith("Query:"):
            actual_query = content.removeprefix("Query:").strip() or fallback_query
            continue
        if section == "answer":
            answer_lines.append(content)
        elif section == "sources":
            match = SOURCE_RE.match(content)
            if match:
                sources.append(
                    {
                        "title": match.group("title").strip(),
                        "domain": match.group("domain").strip(),
                        "age": (match.group("age") or "").strip() or None,
                    }
                )
        elif section == "metadata" and content.startswith("Provider:"):
            provider = content.removeprefix("Provider:").strip() or provider

    while answer_lines and not answer_lines[0]:
        answer_lines.pop(0)
    while answer_lines and not answer_lines[-1]:
        answer_lines.pop()
    answer = "\n".join(answer_lines)
    return {
        "query": actual_query,
        "provider": provider,
        "answer": answer,
        "sources": sources,
        "truncated": bool(MORE_LINES_RE.search(answer)),
        "parsed": started,
        "cleaned_raw": cleaned,
    }


def resolve_omp(binary: str | None) -> str | None:
    candidate = binary or os.environ.get("OMP_BIN")
    if candidate:
        path = Path(candidate).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
        return shutil.which(candidate)
    return shutil.which("omp")


def emit(payload: dict[str, object]) -> None:
    sys.stdout.write(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    )


def failure_message(cleaned_stdout: str, stderr: str, return_code: int) -> str:
    for value in (stderr, cleaned_stdout):
        lines = [line.strip() for line in value.splitlines() if line.strip()]
        if lines:
            return redact(lines[-1])[:1000]
    return f"omp search exited with code {return_code}"


def main(argv: Sequence[str] | None = None) -> int:  # noqa: C901
    args = build_parser().parse_args(argv)
    fallback_query = " ".join(args.query)
    binary = resolve_omp(args.omp_bin)
    if binary is None:
        sys.stderr.write(
            "omp-search: required executable 'omp' was not found "
            "on PATH or via OMP_BIN\n"
        )
        return 127

    command = [binary, "search"]
    if args.provider:
        command.extend(("--provider", args.provider))
    if args.recency:
        command.extend(("--recency", args.recency))
    if args.limit is not None:
        command.extend(("--limit", str(args.limit)))
    if not args.full:
        command.append("--compact")
    command.extend(args.query)

    env = os.environ.copy()
    env["NO_COLOR"] = "1"
    env["FORCE_COLOR"] = "0"
    try:
        result = subprocess.run(  # noqa: S603
            command,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=args.timeout,
        )
    except subprocess.TimeoutExpired as error:
        partial = strip_terminal_controls(error.stdout or "")
        payload: dict[str, object] = {
            "ok": False,
            "query": fallback_query,
            "provider": args.provider,
            "answer": "",
            "sources": [],
            "truncated": False,
            "compact": not args.full,
            "parsed": False,
            "error": {
                "code": "timeout",
                "message": f"omp search exceeded {args.timeout:g}s",
            },
            "exit_code": 124,
        }
        if args.include_raw:
            payload["raw"] = partial
        emit(payload)
        return 124

    parsed = parse_search_output(result.stdout, fallback_query)
    payload = {
        "ok": result.returncode == 0,
        "query": parsed["query"],
        "provider": parsed["provider"] or args.provider,
        "answer": parsed["answer"],
        "sources": parsed["sources"],
        "truncated": parsed["truncated"],
        "compact": not args.full,
        "parsed": parsed["parsed"],
        "exit_code": result.returncode,
    }
    if result.returncode != 0:
        payload["error"] = {
            "code": "omp_search_failed",
            "message": failure_message(
                parsed["cleaned_raw"], result.stderr, result.returncode
            ),
        }
    if result.stderr.strip():
        payload["diagnostics"] = redact(result.stderr.strip())[-2000:]
    if args.include_raw:
        payload["raw"] = parsed["cleaned_raw"]
    emit(payload)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
