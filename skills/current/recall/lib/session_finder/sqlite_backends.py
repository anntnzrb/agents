# Copyright (c) 2026
"""Read-only adapters for T3 Code and OpenCode SQLite session stores."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import TYPE_CHECKING, cast
from urllib.parse import quote

from .model import Harness, Message, Session, make_session, timestamp_from_epoch_ms

if TYPE_CHECKING:
    from collections.abc import Iterable

_T3_SCHEMA: dict[str, frozenset[str]] = {
    "projection_threads": frozenset(
        {
            "thread_id",
            "project_id",
            "title",
            "worktree_path",
            "created_at",
            "updated_at",
            "archived_at",
            "deleted_at",
        }
    ),
    "projection_projects": frozenset({"project_id", "workspace_root"}),
    "projection_thread_messages": frozenset(
        {"message_id", "thread_id", "role", "text", "created_at"}
    ),
}
_OPEN_CODE_SESSION_SCHEMA = {
    "session": frozenset(
        {"id", "directory", "title", "time_created", "time_updated", "time_archived"}
    )
}
_OPEN_CODE_CURRENT_SCHEMA = {
    "session_message": frozenset({"session_id", "seq", "type", "data"})
}
_OPEN_CODE_LEGACY_SCHEMA = {
    "message": frozenset({"id", "session_id", "time_created", "data"}),
    "part": frozenset({"id", "message_id", "session_id", "data"}),
}
_TABLE_INFO_QUERIES = {
    "projection_threads": 'PRAGMA table_info("projection_threads")',
    "projection_projects": 'PRAGMA table_info("projection_projects")',
    "projection_thread_messages": ('PRAGMA table_info("projection_thread_messages")'),
    "session": 'PRAGMA table_info("session")',
    "session_message": 'PRAGMA table_info("session_message")',
    "message": 'PRAGMA table_info("message")',
    "part": 'PRAGMA table_info("part")',
}


def _database_uri(path: Path) -> str:
    resolved = path.expanduser().resolve()
    return f"file:{quote(str(resolved), safe='/')}?mode=ro"


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(_database_uri(path), uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _rows(cursor: sqlite3.Cursor) -> Iterable[sqlite3.Row]:
    """Iterate a row-factory cursor with precise element types."""
    yield from cast("Iterable[sqlite3.Row]", cursor)


def _record(row: sqlite3.Row) -> dict[str, object]:
    """Materialize one row with a single boundary cast."""
    # Row.__iter__ yields values, so .keys() is required for column names.
    return {key: cast("object", row[key]) for key in row.keys()}  # noqa: SIM118


def _columns(connection: sqlite3.Connection) -> dict[str, frozenset[str]]:
    tables = {
        str(_record(row)["name"])
        for row in _rows(
            connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        )
    }
    return {
        table: frozenset(
            str(_record(row)["name"])
            for row in _rows(connection.execute(_TABLE_INFO_QUERIES[table]))
        )
        for table in tables.intersection(_TABLE_INFO_QUERIES)
    }


def _has_schema(
    columns: dict[str, frozenset[str]], required: dict[str, frozenset[str]]
) -> bool:
    return all(
        fields <= columns.get(table, frozenset()) for table, fields in required.items()
    )


def _validate_connection(harness: Harness, connection: sqlite3.Connection) -> None:
    columns = _columns(connection)
    if harness == "t3code":
        valid = _has_schema(columns, _T3_SCHEMA)
    elif harness == "opencode":
        valid = _has_schema(columns, _OPEN_CODE_SESSION_SCHEMA) and (
            _has_schema(columns, _OPEN_CODE_CURRENT_SCHEMA)
            or _has_schema(columns, _OPEN_CODE_LEGACY_SCHEMA)
        )
    else:
        message = f"{harness} does not use a SQLite root"
        raise ValueError(message)
    if not valid:
        message = f"incompatible {harness} database schema"
        raise ValueError(message)


def validate_sqlite_root(harness: Harness, path: Path) -> None:
    """Raise ValueError unless path is a readable, compatible SQLite store."""
    try:
        with closing(_connect(path)) as connection:
            _validate_connection(harness, connection)
    except (OSError, sqlite3.Error) as error:
        message = f"invalid {harness} database {path}: {error}"
        raise ValueError(message) from error


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _message(role: object, text: object) -> Message | None:
    if not isinstance(text, str) or not text.strip():
        return None
    if role == "user":
        return Message(role="user", text=text)
    if role == "assistant":
        return Message(role="assistant", text=text)
    return None


def _t3_sessions(path: Path, connection: sqlite3.Connection) -> list[Session]:
    rows = connection.execute(
        """
        SELECT t.thread_id, t.title, t.worktree_path, t.created_at,
               t.updated_at, t.archived_at, p.workspace_root,
               m.message_id, m.role, m.text
        FROM projection_threads AS t
        LEFT JOIN projection_projects AS p ON p.project_id = t.project_id
        LEFT JOIN projection_thread_messages AS m ON m.thread_id = t.thread_id
        WHERE t.deleted_at IS NULL
        ORDER BY t.thread_id, m.created_at, m.message_id
        """
    )
    sessions: list[Session] = []
    current_id: object = None
    metadata: dict[str, object] | None = None
    messages: list[Message] = []

    def append_current() -> None:
        if metadata is None:
            return
        cwd = _text(metadata["worktree_path"]) or _text(metadata["workspace_root"])
        session = make_session(
            harness="t3code",
            session_id=metadata["thread_id"],
            title=metadata["title"],
            cwd=cwd,
            timestamp=metadata["created_at"],
            updated_at=metadata["updated_at"],
            archived=metadata["archived_at"] is not None,
            storage_path=path,
            resume_argv=None,
            messages=messages,
        )
        if session is not None:
            sessions.append(session)

    for raw in _rows(rows):
        row = _record(raw)
        if row["thread_id"] != current_id:
            append_current()
            current_id = row["thread_id"]
            metadata = row
            messages = []
        if message := _message(row["role"], row["text"]):
            messages.append(message)
    append_current()
    return sessions


def _json_object(value: object) -> dict[str, object] | None:
    if not isinstance(value, str):
        return None
    try:
        decoded = cast("object", json.loads(value))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(decoded, dict):
        return None
    raw = cast("dict[object, object]", decoded)
    return {str(key): item for key, item in raw.items()}


def _text_blocks(value: object) -> str:
    if not isinstance(value, list):
        return ""
    blocks = cast("list[object]", value)
    parts: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        mapping = cast("dict[str, object]", block)
        if mapping.get("type") != "text":
            continue
        text = mapping.get("text")
        if isinstance(text, str) and text.strip():
            parts.append(text)
    return "\n".join(parts)


def _current_messages(
    connection: sqlite3.Connection, session_id: object
) -> list[Message]:
    messages: list[Message] = []
    for raw in _rows(
        connection.execute(
            "SELECT type, data FROM session_message WHERE session_id = ? ORDER BY seq",
            (session_id,),
        )
    ):
        row = _record(raw)
        role = row["type"]
        data = _json_object(row["data"])
        if data is None:
            continue
        text = (
            _text(data.get("text"))
            if role == "user"
            else _text_blocks(data.get("content"))
            if role == "assistant"
            else ""
        )
        if message := _message(role, text):
            messages.append(message)
    return messages


def _legacy_messages(
    connection: sqlite3.Connection, session_id: object
) -> list[Message]:
    messages: list[Message] = []
    rows = connection.execute(
        """
        SELECT m.id AS message_id, m.data AS message_data, p.data AS part_data
        FROM message AS m
        LEFT JOIN part AS p ON p.message_id = m.id AND p.session_id = m.session_id
        WHERE m.session_id = ?
        ORDER BY m.time_created, m.id, p.id
        """,
        (session_id,),
    )
    current_id: object = None
    role: object = None
    parts: list[str] = []

    def append_current() -> None:
        if message := _message(role, "\n".join(parts)):
            messages.append(message)

    for raw in _rows(rows):
        row = _record(raw)
        if row["message_id"] != current_id:
            append_current()
            current_id = row["message_id"]
            data = _json_object(row["message_data"])
            role = data.get("role") if data is not None else None
            parts = []
        part = _json_object(row["part_data"])
        if part is not None and part.get("type") == "text":
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text)
    append_current()
    return messages


def _opencode_sessions(path: Path, connection: sqlite3.Connection) -> list[Session]:
    columns = _columns(connection)
    has_current = _has_schema(columns, _OPEN_CODE_CURRENT_SCHEMA)
    has_legacy = _has_schema(columns, _OPEN_CODE_LEGACY_SCHEMA)
    sessions: list[Session] = []
    for raw in _rows(
        connection.execute(
            """
            SELECT id, directory, title, time_created, time_updated, time_archived
            FROM session
            """
        )
    ):
        row = _record(raw)
        session_id = row["id"]
        messages = _current_messages(connection, session_id) if has_current else []
        if not messages and has_current:
            has_current_rows = (
                connection.execute(
                    "SELECT 1 FROM session_message WHERE session_id = ? LIMIT 1",
                    (session_id,),
                ).fetchone()
                is not None
            )
        else:
            has_current_rows = bool(messages)
        if not has_current_rows and has_legacy:
            messages = _legacy_messages(connection, session_id)
        cwd = _text(row["directory"])
        created = timestamp_from_epoch_ms(row["time_created"])
        updated = timestamp_from_epoch_ms(row["time_updated"])
        session = make_session(
            harness="opencode",
            session_id=session_id,
            title=row["title"],
            cwd=cwd,
            timestamp=created,
            updated_at=updated,
            archived=row["time_archived"] is not None,
            storage_path=path,
            resume_argv=("opencode", cwd, "--session", session_id)
            if cwd and isinstance(session_id, str)
            else ("opencode", "--session", session_id)
            if isinstance(session_id, str)
            else None,
            messages=messages,
        )
        if session is not None:
            sessions.append(session)
    return sessions


def _default_t3_paths() -> Iterable[Path]:
    base = Path(os.environ.get("T3CODE_HOME", "~/.t3")).expanduser()
    yield base / "userdata" / "state.sqlite"
    yield base / "dev" / "state.sqlite"


def _default_opencode_paths() -> Iterable[Path]:
    data_home = Path(os.environ.get("XDG_DATA_HOME", "~/.local/share")).expanduser()
    directory = data_home / "opencode"
    configured = os.environ.get("OPENCODE_DB")
    if configured is not None:
        if configured == ":memory:":
            return
        path = Path(configured).expanduser()
        yield path if path.is_absolute() else directory / path
        return
    yield directory / "opencode.db"
    yield from directory.glob("opencode-*.db")


def discover_sqlite_sessions(
    selected: set[Harness], roots: dict[Harness, tuple[Path, ...]]
) -> list[Session]:
    """Discover and parse selected T3 Code and OpenCode SQLite stores."""
    candidates: list[tuple[Harness, Path]] = []
    if "t3code" in selected:
        candidates.extend(
            ("t3code", path) for path in roots.get("t3code", tuple(_default_t3_paths()))
        )
    if "opencode" in selected:
        candidates.extend(
            ("opencode", path)
            for path in roots.get("opencode", tuple(_default_opencode_paths()))
        )

    sessions: list[Session] = []
    seen: set[tuple[Harness, Path]] = set()
    for harness, candidate in candidates:
        try:
            path = candidate.expanduser().resolve()
        except OSError:
            continue
        key = (harness, path)
        if key in seen or not path.is_file():
            continue
        seen.add(key)
        try:
            with closing(_connect(path)) as connection:
                _validate_connection(harness, connection)
                sessions.extend(
                    _t3_sessions(path, connection)
                    if harness == "t3code"
                    else _opencode_sessions(path, connection)
                )
        except (OSError, sqlite3.Error, ValueError):
            continue
    return sessions
