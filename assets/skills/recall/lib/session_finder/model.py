# Copyright (c) 2026
"""Normalized session records, matching, and ranking."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal, TypedDict

if TYPE_CHECKING:
    from pathlib import Path

Harness = Literal["omp", "pi", "codex", "t3code", "opencode"]
MatchType = Literal["title", "user_message", "transcript", "cwd"]


@dataclass(frozen=True, slots=True)
class Message:
    """One authored transcript message."""

    role: Literal["user", "assistant"]
    text: str


@dataclass(frozen=True, slots=True)
class Session:
    """One normalized persisted session."""

    harness: Harness
    session_id: str
    title: str
    cwd: str
    timestamp: str
    updated_at: str
    archived: bool
    storage_path: str
    resume_argv: tuple[str, ...] | None
    messages: tuple[Message, ...]


class Record(TypedDict):
    """Public ranked result contract."""

    harness: Harness
    session_id: str
    title: str
    cwd: str
    timestamp: str
    updated_at: str
    archived: bool
    storage_path: str
    resume_argv: tuple[str, ...] | None
    match_type: MatchType
    score: int
    snippet: str


def normalize_timestamp(value: object) -> str | None:
    """Normalize an ISO/RFC3339 timestamp to millisecond UTC."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    parsed = parsed.astimezone(UTC)
    return parsed.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def timestamp_from_epoch_ms(value: object) -> str | None:
    """Normalize a numeric millisecond epoch to UTC."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        parsed = datetime.fromtimestamp(value / 1000, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None
    return parsed.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def timestamp_from_mtime(path: Path, fallback: str) -> str:
    """Return a file mtime timestamp, falling back on a created timestamp."""
    try:
        parsed = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    except OSError:
        return fallback
    return parsed.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def make_session(  # noqa: PLR0913
    *,
    harness: Harness,
    session_id: object,
    title: object = "",
    cwd: object = "",
    timestamp: object,
    updated_at: object = None,
    archived: bool,
    storage_path: Path,
    resume_argv: tuple[str, ...] | None,
    messages: list[Message] | tuple[Message, ...] = (),
) -> Session | None:
    """Validate and construct a normalized session."""
    if not isinstance(session_id, str) or not session_id.strip():
        return None
    created = normalize_timestamp(timestamp)
    try:
        absolute_path = storage_path.expanduser().resolve()
    except OSError:
        return None
    if created is None or not absolute_path.is_absolute():
        return None
    updated = normalize_timestamp(updated_at) or created
    clean_messages = tuple(message for message in messages if message.text.strip())
    return Session(
        harness=harness,
        session_id=session_id.strip(),
        title=title if isinstance(title, str) else "",
        cwd=cwd if isinstance(cwd, str) else "",
        timestamp=created,
        updated_at=updated,
        archived=archived,
        storage_path=str(absolute_path),
        resume_argv=resume_argv,
        messages=clean_messages,
    )


def _compact(text: str, terms: tuple[str, ...], width: int = 180) -> str:
    flat = " ".join(text.split())
    if not flat:
        return ""
    folded = flat.casefold()
    positions = [position for term in terms if (position := folded.find(term)) >= 0]
    start = max(0, min(positions) - 45) if positions else 0
    end = min(len(flat), start + width)
    return f"{'…' if start else ''}{flat[start:end]}{'…' if end < len(flat) else ''}"


def match_session(session: Session, terms: tuple[str, ...]) -> Record | None:
    """Match a session against the highest-priority complete category."""
    user_text = "\n".join(
        message.text for message in session.messages if message.role == "user"
    )
    transcript = "\n".join(message.text for message in session.messages)
    categories: tuple[tuple[int, MatchType, str], ...] = (
        (4, "title", session.title),
        (3, "user_message", user_text),
        (2, "transcript", transcript),
        (1, "cwd", session.cwd),
    )
    for score, match_type, source in categories:
        folded = source.casefold()
        if all(term in folded for term in terms):
            return {
                "harness": session.harness,
                "session_id": session.session_id,
                "title": session.title,
                "cwd": session.cwd,
                "timestamp": session.timestamp,
                "updated_at": session.updated_at,
                "archived": session.archived,
                "storage_path": session.storage_path,
                "resume_argv": session.resume_argv,
                "match_type": match_type,
                "score": score,
                "snippet": _compact(source, terms),
            }
    return None


def deduplicate(sessions: list[Session]) -> list[Session]:
    """Choose the canonical artifact for each harness/session identity."""
    winners: dict[tuple[Harness, str], Session] = {}
    for session in sessions:
        key = (session.harness, session.session_id)
        current = winners.get(key)
        if current is None or (
            session.archived,
            _descending_text(session.updated_at),
            session.storage_path,
        ) < (
            current.archived,
            _descending_text(current.updated_at),
            current.storage_path,
        ):
            winners[key] = session
    return list(winners.values())


def _descending_text(value: str) -> tuple[int, ...]:
    return tuple(-ord(character) for character in value)


def rank(sessions: list[Session], terms: tuple[str, ...], limit: int) -> list[Record]:
    """Deduplicate, match, rank, and limit normalized sessions."""
    records = [
        record
        for session in deduplicate(sessions)
        if (record := match_session(session, terms))
    ]
    records.sort(
        key=lambda record: (
            -record["score"],
            _descending_text(record["updated_at"]),
            _descending_text(record["timestamp"]),
            record["harness"],
            record["session_id"],
            record["storage_path"],
        )
    )
    return records[:limit]
