#!/usr/bin/env -S uv run --script
# Copyright (c) 2026
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///

# SPDX-License-Identifier: GPL-3.0-or-later
"""Find resumable sessions across project directories."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from collections.abc import Iterator


class Record(TypedDict):
    """A ranked session search result."""

    session_id: str
    title: str
    cwd: str
    timestamp: str
    resume_path: str
    match_type: str
    score: int
    snippet: str


def positive_int(value: str) -> int:
    """Parse a positive result limit."""
    message = "limit must be a positive integer"
    try:
        if (number := int(value)) < 1:
            raise argparse.ArgumentTypeError(message)
    except ValueError as error:
        raise argparse.ArgumentTypeError(message) from error
    return number


def arguments() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Find saved sessions")
    parser.add_argument("query", nargs="+", metavar="QUERY")
    parser.add_argument("--limit", type=positive_int, default=10, metavar="N")
    parser.add_argument("--root", action="append", type=Path, metavar="PATH")
    return parser.parse_args()


def roots(requested: list[Path] | None) -> list[Path]:
    """Return existing, distinct OMP session roots."""
    match requested, (agent_dir := os.environ.get("PI_CODING_AGENT_DIR")):
        case list() as explicit, _:
            candidates = explicit
        case None, str() if agent_dir:
            candidates = [Path(agent_dir) / "sessions"]
        case _:
            candidates = [
                *(
                    [Path(xdg_dir) / "omp" / "sessions"]
                    if (xdg_dir := os.environ.get("XDG_DATA_HOME"))
                    else []
                ),
                Path.home() / ".omp" / "agent" / "sessions",
            ]

    return list(
        dict.fromkeys(
            path
            for candidate in candidates
            if (path := candidate.expanduser().resolve()).is_dir()
        )
    )


def _decode_object(
    decoder: json.JSONDecoder,
    line: str,
    start: int,
) -> dict[str, object] | None:
    try:
        value = decoder.raw_decode(line, start)[0]
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def json_object(line: str) -> dict[str, object] | None:
    """Decode the first JSON object embedded in a line."""
    decoder = json.JSONDecoder()
    return next(
        (
            value
            for start, character in enumerate(line)
            if character == "{"
            and (value := _decode_object(decoder, line, start)) is not None
        ),
        None,
    )


def text_content(value: object) -> str:
    """Flatten textual content from an OMP event value."""
    match value:
        case str():
            return value
        case list():
            return "\n".join(filter(None, map(text_content, value)))
        case dict():
            return "\n".join(
                text
                for key in ("text", "content", "message")
                if key in value and (text := text_content(value[key]))
            )
        case _:
            return ""


def compact(text: str, terms: list[str], width: int = 180) -> str:
    """Build a compact snippet around the earliest query term."""
    if not (flat := " ".join(text.split())):
        return ""
    start = (
        max(0, min(found) - 45)
        if (
            found := [
                position
                for term in terms
                if (position := flat.casefold().find(term)) >= 0
            ]
        )
        else 0
    )
    end = min(len(flat), start + width)
    return f"{'…' if start else ''}{flat[start:end]}{'…' if end < len(flat) else ''}"


def _event_message(event: dict[str, object]) -> tuple[str, str]:
    message = event.get("message")
    role = (
        role_value
        if isinstance(
            role_value := message.get("role") if isinstance(message, dict) else None,
            str,
        )
        else ""
    )
    return role, text_content(message if message is not None else event.get("content"))


def _read_session(
    path: Path,
) -> tuple[dict[str, object], str, list[tuple[str, str]]] | None:
    header: dict[str, object] | None = None
    slot_title = ""
    header_title = ""
    last_title_change = ""
    messages: list[tuple[str, str]] = []
    try:
        with path.open(encoding="utf-8", errors="ignore") as stream:
            for line in stream:
                if (event := json_object(line)) is None:
                    continue
                match event.get("type"), event.get("title"):
                    case "title", str(session_title):
                        slot_title = session_title
                    case "session", str(session_title) if header is None:
                        header, header_title = event, session_title
                    case "session", _ if header is None:
                        header = event
                    case "title_change", str(session_title):
                        last_title_change = session_title
                    case _:
                        pass
                match _event_message(event):
                    case role, content if content:
                        messages.append((role, content))
                    case _:
                        pass
    except OSError:
        return None
    title = slot_title or last_title_change or header_title or ""
    return (header, title, messages) if header is not None else None


def _string_field(event: dict[str, object], key: str) -> str:
    return value if isinstance(value := event.get(key), str) else ""


def _match_source(
    title: str,
    messages: list[tuple[str, str]],
    cwd: str,
    terms: list[str],
) -> tuple[int, str, str] | None:
    """Return the highest-priority category containing every query term."""
    user_text = "\n".join(text for role, text in messages if role == "user")
    transcript = "\n".join(text for _, text in messages)
    categories = (
        (4, "title", title),
        (3, "user_message", user_text),
        (2, "transcript", transcript),
        (1, "cwd", cwd),
    )
    return next(
        (
            (score, match_type, source)
            for score, match_type, source in categories
            if all(term in source.casefold() for term in terms)
        ),
        None,
    )


def inspect(
    path: Path,
    terms: list[str],
) -> Record | None:
    """Inspect one root session and return a ranked match."""
    if (session := _read_session(path)) is None:
        return None
    header, title, messages = session
    session_id = _string_field(header, "id")
    cwd = _string_field(header, "cwd")
    timestamp = _string_field(header, "timestamp")
    if (match := _match_source(title, messages, cwd, terms)) is None:
        return None

    score, match_type, source = match
    return {
        "session_id": session_id,
        "title": title,
        "cwd": cwd,
        "timestamp": timestamp,
        "resume_path": str(path),
        "match_type": match_type,
        "score": score,
        "snippet": compact(source, terms),
    }


def _session_files(search_root: Path) -> Iterator[Path]:
    try:
        yield from search_root.glob("*/*.jsonl")
    except OSError:
        return


def _resolve(path: Path) -> Path | None:
    try:
        return path.resolve()
    except OSError:
        return None


def _find_matches(
    search_roots: list[Path],
    terms: list[str],
) -> list[Record]:
    paths = dict.fromkeys(
        resolved
        for search_root in search_roots
        for path in _session_files(search_root)
        if (resolved := _resolve(path)) is not None
    )
    return sorted(
        (match for path in paths if (match := inspect(path, terms)) is not None),
        key=lambda record: (
            record["score"],
            record["timestamp"],
            record["session_id"],
            record["resume_path"],
        ),
        reverse=True,
    )


def main() -> int:
    """Search sessions and return the documented status."""
    args = arguments()
    if not (search_roots := roots(args.root)):
        sys.stderr.write("session-finder: no existing session roots\n")
        return 2

    if not (
        terms := [
            term.casefold() for query in args.query for term in query.split() if term
        ]
    ):
        sys.stderr.write("session-finder: query must not be empty\n")
        return 2

    records = _find_matches(search_roots, terms)[: args.limit]
    sys.stdout.write(
        json.dumps(records, ensure_ascii=False, separators=(",", ":")) + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
