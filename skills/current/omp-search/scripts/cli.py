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
from concurrent.futures import ThreadPoolExecutor, as_completed
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
        "--provider", help="explicit single OMP provider name"
    )
    parser.add_argument(
        "--providers",
        help="comma-separated list of providers to query concurrently (defaults to OMP's configured active providers)",
    )
    parser.add_argument(
        "--single",
        action="store_true",
        help="force single-provider auto-fallback chain instead of parallel fan-out",
    )
    parser.add_argument(
        "--recency",
        choices=("day", "week", "month", "year"),
        help="recency filter (day, week, month, year)",
    )
    parser.add_argument(
        "--limit",
        type=positive_int,
        help="number of sources per provider (minimum 2; defaults to 2)",
    )
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


def extract_yaml_list(text: str, target_key: str) -> list[str]:
    lines = text.splitlines()
    in_section = False
    in_key = False
    items: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 0 and stripped.startswith("providers:"):
            in_section = True
            continue
        if in_section and indent == 0 and not stripped.startswith("providers:"):
            in_section = False
            in_key = False
        if in_section:
            if stripped.startswith(f"{target_key}:"):
                in_key = True
                continue
            if in_key:
                if stripped.startswith("- "):
                    items.append(stripped[2:].strip())
                elif indent <= 2 and not stripped.startswith("-"):
                    in_key = False
    return items


def discover_active_omp_providers() -> list[str]:
    candidates: list[Path] = []
    if custom := os.environ.get("OMP_CONFIG_DIR"):
        candidates.append(Path(custom).expanduser() / "config.yml")
    candidates.append(Path.home() / ".omp" / "agent" / "config.yml")
    candidates.append(Path.cwd() / "harnesses" / "omp" / "agent" / "config.yml")
    candidates.append(Path.cwd() / ".omp" / "agent" / "config.yml")
    candidates.append(Path.cwd() / ".omp" / "config.yml")

    for path in candidates:
        if path.is_file():
            try:
                content = path.read_text(encoding="utf-8")
                order = extract_yaml_list(content, "webSearchOrder")
                exclude = set(extract_yaml_list(content, "webSearchExclude"))
                if active := [p for p in order if p not in exclude]:
                    return active
            except Exception:  # noqa: BLE001, S110
                pass
    return []


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


def execute_single_search(  # noqa: C901, PLR0913
    binary: str,
    provider: str | None,
    query_words: Sequence[str],
    recency: str | None,
    limit: int | None,
    full: bool,
    timeout: float,
    include_raw: bool,
) -> dict[str, object]:
    fallback_query = " ".join(query_words)
    command = [binary, "search"]
    if provider:
        command.extend(("--provider", provider))
    if recency:
        command.extend(("--recency", recency))
    if limit is not None:
        command.extend(("--limit", str(limit)))
    if not full:
        command.append("--compact")
    command.extend(query_words)

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
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        partial = strip_terminal_controls(error.stdout or "")
        payload: dict[str, object] = {
            "ok": False,
            "query": fallback_query,
            "provider": provider,
            "answer": "",
            "sources": [],
            "truncated": False,
            "compact": not full,
            "parsed": False,
            "error": {
                "code": "timeout",
                "message": f"omp search exceeded {timeout:g}s",
            },
            "exit_code": 124,
        }
        if include_raw:
            payload["raw"] = partial
        return payload

    parsed = parse_search_output(result.stdout, fallback_query)
    payload = {
        "ok": result.returncode == 0,
        "query": parsed["query"],
        "provider": parsed["provider"] or provider,
        "answer": parsed["answer"],
        "sources": parsed["sources"],
        "sources_count": len(parsed["sources"]),
        "truncated": parsed["truncated"],
        "compact": not full,
        "parsed": parsed["parsed"],
        "exit_code": result.returncode,
    }
    if result.returncode != 0:
        payload["error"] = {
            "code": "omp_search_failed",
            "message": failure_message(
                str(parsed.get("cleaned_raw") or ""), result.stderr, result.returncode
            ),
        }
    if result.stderr.strip():
        payload["diagnostics"] = redact(result.stderr.strip())[-2000:]
    if include_raw:
        payload["raw"] = parsed.get("cleaned_raw") or ""
    return payload


def merge_parallel_results(  # noqa: C901
    query: str,
    results: Sequence[dict[str, object]],
    compact: bool,
) -> dict[str, object]:
    successful = [r for r in results if r.get("ok")]
    if not successful:
        first_error = next((r.get("error") for r in results if r.get("error")), None)
        return {
            "ok": False,
            "query": query,
            "provider": "+".join(str(r.get("provider") or "unknown") for r in results),
            "providers": [str(r.get("provider") or "unknown") for r in results],
            "answer": "",
            "sources": [],
            "truncated": False,
            "compact": compact,
            "parsed": False,
            "error": first_error
            or {"code": "all_providers_failed", "message": "all parallel providers failed"},
            "exit_code": 1,
        }

    merged_sources: list[dict[str, str | None]] = []
    seen_sources: set[tuple[str, str]] = set()
    answer_sections: list[str] = []
    used_providers: list[str] = []

    for r in successful:
        prov = str(r.get("provider") or "Unknown")
        used_providers.append(prov)
        ans = str(r.get("answer") or "").strip()
        if ans:
            answer_sections.append(f"### [{prov}]\n{ans}")

        raw_sources = r.get("sources")
        if isinstance(raw_sources, list):
            for src in raw_sources:
                if isinstance(src, dict):
                    title = str(src.get("title") or "").strip()
                    domain = str(src.get("domain") or "").strip()
                    key = (title.lower(), domain.lower())
                    if key not in seen_sources:
                        seen_sources.add(key)
                        merged_sources.append(
                            {
                                "title": title,
                                "domain": domain,
                                "age": src.get("age"),
                            }
                        )

    return {
        "ok": True,
        "query": query,
        "provider": "+".join(used_providers),
        "providers": used_providers,
        "providers_count": len(used_providers),
        "answer": "\n\n".join(answer_sections),
        "sources": merged_sources,
        "sources_count": len(merged_sources),
        "truncated": any(bool(r.get("truncated")) for r in successful),
        "compact": compact,
        "parsed": True,
        "exit_code": 0,
    }

def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    fallback_query = " ".join(args.query)
    binary = resolve_omp(args.omp_bin)
    if binary is None:
        sys.stderr.write(
            "omp-search: required executable 'omp' was not found "
            "on PATH or via OMP_BIN\n"
        )
        return 127

    provider_list: list[str | None] = []
    if args.provider:
        provider_list = [args.provider]
    elif args.providers:
        provider_list = [p.strip() for p in args.providers.split(",") if p.strip()]
    elif args.single:
        provider_list = [None]
    else:
        discovered = discover_active_omp_providers()
        provider_list = list(discovered) if discovered else [None]
    effective_limit = max(2, args.limit) if args.limit is not None else 2
    if len(provider_list) == 1:
        payload = execute_single_search(
            binary=binary,
            provider=provider_list[0],
            query_words=args.query,
            recency=args.recency,
            limit=effective_limit,
            full=args.full,
            timeout=args.timeout,
            include_raw=args.include_raw,
        )
        emit(payload)
        return int(payload.get("exit_code") or 0)

    results: list[dict[str, object]] = []
    with ThreadPoolExecutor(max_workers=min(len(provider_list), 8)) as executor:
        future_to_provider = {
            executor.submit(
                execute_single_search,
                binary,
                p,
                args.query,
                args.recency,
                effective_limit,
                args.full,
                args.timeout,
                args.include_raw,
            ): p
            for p in provider_list
        }
        for future in as_completed(future_to_provider):
            try:
                results.append(future.result())
            except Exception as exc:  # noqa: BLE001
                p_name = future_to_provider[future]
                results.append(
                    {
                        "ok": False,
                        "provider": p_name,
                        "error": {"code": "exception", "message": str(exc)},
                        "exit_code": 1,
                    }
                )

    merged = merge_parallel_results(fallback_query, results, compact=not args.full)
    emit(merged)
    return int(merged.get("exit_code") or 0)

if __name__ == "__main__":
    raise SystemExit(main())
