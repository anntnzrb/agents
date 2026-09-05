# Copyright (c) 2026
"""Discovery and parsing for the OMP, Pi, and Codex JSONL stores."""

from __future__ import annotations

import gzip
import io
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from typing import TextIO

import zstandard

from .model import Harness, Message, Session, make_session, timestamp_from_mtime

_JSON_DECODER = json.JSONDecoder()

type JsonValue = (
    bool | int | float | str | list[JsonValue] | dict[str, JsonValue] | None
)
type AuthoredRole = Literal["user", "assistant"]


@dataclass(slots=True)
class _CompatibleCandidate:
    path: Path
    archived: bool = False
    explicit: set[Harness] = field(default_factory=set)
    provenance: set[Harness] = field(default_factory=set)


def _objects(lines: Iterable[str]) -> Iterator[dict[str, JsonValue]]:
    """Decode JSON objects, including objects embedded in prefixed log lines."""
    for line in lines:
        offset = 0
        while True:
            start = line.find("{", offset)
            if start < 0:
                break
            try:
                decoded: tuple[object, int] = _JSON_DECODER.raw_decode(line, start)
            except (json.JSONDecodeError, RecursionError):
                offset = start + 1
                continue
            value, end = decoded
            offset = end
            if isinstance(value, dict):
                raw = cast("dict[object, object]", value)
                if all(isinstance(key, str) for key in raw):
                    # Decoder is untyped; nested values are validated lazily.
                    yield cast("dict[str, JsonValue]", value)
                    break


def _flatten_text(value: object) -> str:
    """Flatten the polymorphic text/content shapes used by compatible stores."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        items = cast("list[object]", value)
        return "\n".join(
            part for item in items if (part := _flatten_text(item)).strip()
        )
    if not isinstance(value, dict):
        return ""
    mapping = cast("dict[str, object]", value)
    for key in ("text", "content", "message", "value"):
        if key in mapping and (text := _flatten_text(mapping[key])).strip():
            return text
    return ""


def _resolved(path: Path) -> Path | None:
    try:
        return path.expanduser().resolve()
    except OSError:
        return None


def _glob_pattern(root: Path, pattern: str) -> Iterator[Path]:
    try:
        yield from root.rglob(pattern)
    except OSError:
        return


def _files(root: Path, patterns: tuple[str, ...]) -> Iterator[Path]:
    """Traverse a store lazily; an unreadable subtree does not abort other stores."""
    for pattern in patterns:
        yield from _glob_pattern(root, pattern)


def _read_json(path: Path) -> dict[str, JsonValue]:
    try:
        value = cast("object", json.loads(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    if not isinstance(value, dict):
        return {}
    # Decoder is untyped; nested values are validated lazily.
    return cast("dict[str, JsonValue]", value)


def _pi_root() -> tuple[Path, str]:
    agent_dir_text = os.environ.get("PI_CODING_AGENT_DIR", "").strip()
    agent_dir = (
        Path(agent_dir_text).expanduser()
        if agent_dir_text
        else Path.home() / ".pi" / "agent"
    )
    global_settings = _read_json(agent_dir / "settings.json")
    project_settings = _read_json(Path.cwd() / ".pi" / "settings.json")
    configured = global_settings.get("sessionDir")
    if "sessionDir" in project_settings:
        configured = project_settings["sessionDir"]
    if isinstance(configured, str) and configured.strip():
        path = Path(configured).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        return path, "configured"
    return agent_dir / "sessions", "standard"


def _add_compatible(
    registry: dict[Path, _CompatibleCandidate],
    path: Path,
    *,
    owner: Harness,
    explicit: bool,
    archived: bool = False,
) -> None:
    resolved = _resolved(path)
    if resolved is None or not resolved.is_file():
        return
    candidate = registry.setdefault(resolved, _CompatibleCandidate(resolved))
    candidate.archived = candidate.archived or archived
    (candidate.explicit if explicit else candidate.provenance).add(owner)


def _discover_compatible(  # noqa: C901, PLR0912
    roots: dict[Harness, tuple[Path, ...]],
) -> dict[Path, _CompatibleCandidate]:
    registry: dict[Path, _CompatibleCandidate] = {}
    explicit_omp = roots.get("omp")
    if explicit_omp is not None:
        for root in explicit_omp:
            for path in _files(root, ("*.jsonl", "*.jsonl.gz")):
                _add_compatible(
                    registry,
                    path,
                    owner="omp",
                    explicit=True,
                    archived=path.name.endswith(".gz"),
                )
    else:
        xdg = Path(
            os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
        )
        omp_roots = [
            xdg / "omp" / "sessions",
            Path.home() / ".omp" / "agent" / "sessions",
        ]
        agent_dir = os.environ.get("PI_CODING_AGENT_DIR", "").strip()
        if agent_dir:
            omp_roots.append(Path(agent_dir).expanduser() / "sessions")
        for root in omp_roots:
            for path in _files(root, ("*.jsonl",)):
                _add_compatible(registry, path, owner="omp", explicit=False)
            archive = root.parent / "archive" / "sessions"
            for path in _files(archive, ("*.jsonl.gz",)):
                _add_compatible(
                    registry, path, owner="omp", explicit=False, archived=True
                )

    explicit_pi = roots.get("pi")
    if explicit_pi is not None:
        pi_roots = tuple((root, True) for root in explicit_pi)
    else:
        environment_root = os.environ.get("PI_CODING_AGENT_SESSION_DIR", "").strip()
        if environment_root:
            path = Path(environment_root).expanduser()
            if not path.is_absolute():
                path = Path.cwd() / path
            pi_roots = ((path, False),)
        else:
            path, _kind = _pi_root()
            pi_roots = ((path, False),)
    for root, explicit in pi_roots:
        for path in _files(root, ("*.jsonl",)):
            _add_compatible(registry, path, owner="pi", explicit=explicit)
    return registry


def _open_text(path: Path) -> TextIO:
    if path.name.endswith(".jsonl.gz"):
        return gzip.open(path, mode="rt", encoding="utf-8")
    if path.name.endswith(".zst"):
        raw = path.open("rb")
        reader = zstandard.ZstdDecompressor().stream_reader(raw, closefd=True)
        return io.TextIOWrapper(reader, encoding="utf-8")
    return path.open(encoding="utf-8")


def _compatible_owner(
    candidate: _CompatibleCandidate,
    records: list[dict[str, JsonValue]],
) -> Harness | None:
    if len(candidate.explicit) == 1:
        return next(iter(candidate.explicit))
    omp_marker = any(
        record.get("type") in {"title", "title_change"}
        or (record.get("type") == "session" and isinstance(record.get("title"), str))
        for record in records
    )
    if omp_marker:
        return "omp"
    if any(record.get("type") == "session_info" for record in records):
        return "pi"
    owners = candidate.explicit or candidate.provenance
    if len(owners) == 1:
        return next(iter(owners))
    # Shared ancestry makes Pi's standard session directory the more specific hint.
    if "pi" in owners:
        return "pi"
    return "omp" if "omp" in owners else None


def _authored_role(value: object) -> AuthoredRole | None:
    if value == "user":
        return "user"
    if value == "assistant":
        return "assistant"
    return None


def _message(record: dict[str, JsonValue]) -> Message | None:
    payload = record.get("message")
    if record.get("type") == "custom_message":
        payload = record.get("custom_message", payload)
    source = payload if isinstance(payload, dict) else record
    role = _authored_role(source.get("role"))
    if role is None:
        return None
    text_value = (
        payload
        if record.get("type") == "custom_message" and not isinstance(payload, dict)
        else source.get("content", source.get("text", source.get("message")))
    )
    text = _flatten_text(text_value)
    if not text.strip():
        return None
    return Message(role, text)


def _parse_compatible(candidate: _CompatibleCandidate) -> Session | None:
    try:
        with _open_text(candidate.path) as stream:
            records = list(_objects(stream))
    except (OSError, UnicodeError, EOFError, zstandard.ZstdError):
        return None
    owner = _compatible_owner(candidate, records)
    if owner not in {"omp", "pi"}:
        return None
    header = next(
        (record for record in records if record.get("type") == "session"), None
    )
    if header is None:
        return None
    messages = [
        message
        for record in records
        if record.get("type") in {"message", "custom_message"}
        if (message := _message(record))
    ]
    title = ""
    if owner == "omp":
        fixed_title = next(
            (record for record in records if record.get("type") == "title"), None
        )
        title_changes = [
            record for record in records if record.get("type") == "title_change"
        ]
        if fixed_title is not None:
            title = _flatten_text(fixed_title.get("title", fixed_title.get("name")))
        if not title and title_changes:
            title = _flatten_text(
                title_changes[-1].get("title", title_changes[-1].get("name"))
            )
        if not title:
            title = _flatten_text(header.get("title"))
    else:
        infos = [record for record in records if record.get("type") == "session_info"]
        if infos:
            title = _flatten_text(infos[-1].get("name")).strip()
    session_id = header.get("id", header.get("session_id"))
    created = header.get("timestamp", header.get("created_at"))
    updated = timestamp_from_mtime(candidate.path, "")
    archived = candidate.archived if owner == "omp" else False
    argv = (
        None
        if archived
        else (
            ("omp", "--resume", str(candidate.path))
            if owner == "omp"
            else ("pi", "--session", str(candidate.path))
        )
    )
    return make_session(
        harness=owner,
        session_id=session_id,
        title=title,
        cwd=header.get("cwd", ""),
        timestamp=created,
        updated_at=updated,
        archived=archived,
        storage_path=candidate.path,
        resume_argv=argv,
        messages=messages,
    )


def _codex_names(home: Path) -> dict[str, str]:
    names: dict[str, str] = {}
    try:
        with (home / "session_index.jsonl").open(encoding="utf-8") as stream:
            for record in _objects(stream):
                session_id = record.get("id", record.get("session_id"))
                name = record.get("thread_name")
                if isinstance(session_id, str) and isinstance(name, str):
                    names[session_id] = name
    except (OSError, UnicodeError):
        return names
    return names


def _codex_content(content: object) -> str:
    if not isinstance(content, list):
        return ""
    blocks = cast("list[object]", content)
    texts: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        mapping = cast("dict[str, object]", block)
        if mapping.get("type") in {"input_text", "output_text"}:
            text = mapping.get("text")
            if isinstance(text, str) and text.strip():
                texts.append(text)
    return "\n".join(texts)


def _legacy_user_text(text: str) -> str:
    prefix = "## My request for Codex:"
    stripped = text.lstrip()
    return stripped[len(prefix) :].lstrip() if stripped.startswith(prefix) else text


def _parse_codex(
    path: Path, *, archived: bool, names: dict[str, str]
) -> Session | None:
    try:
        with _open_text(path) as stream:
            records = list(_objects(stream))
    except (OSError, UnicodeError, EOFError, zstandard.ZstdError):
        return None
    meta_record = next(
        (record for record in records if record.get("type") == "session_meta"), None
    )
    meta = meta_record.get("payload") if meta_record is not None else None
    if not isinstance(meta, dict):
        return None
    event_messages: list[Message] = []
    response_messages: list[Message] = []
    for record in records:
        payload = record.get("payload")
        if not isinstance(payload, dict):
            continue
        if record.get("type") == "event_msg" and payload.get("type") in {
            "user_message",
            "agent_message",
        }:
            text = payload.get("message")
            if isinstance(text, str) and text.strip():
                role: AuthoredRole = (
                    "user" if payload["type"] == "user_message" else "assistant"
                )
                event_messages.append(
                    Message(role, _legacy_user_text(text) if role == "user" else text)
                )
        elif record.get("type") == "response_item" and payload.get("type") == "message":
            response_role = _authored_role(payload.get("role"))
            if (
                response_role is not None
                and (text := _codex_content(payload.get("content"))).strip()
            ):
                response_messages.append(
                    Message(
                        response_role,
                        _legacy_user_text(text) if response_role == "user" else text,
                    )
                )
    session_id = meta.get("id")
    cwd = meta.get("cwd")
    if not isinstance(session_id, str) or not isinstance(cwd, str):
        return None
    created = meta.get("timestamp")
    updated = timestamp_from_mtime(path, "")
    return make_session(
        harness="codex",
        session_id=session_id,
        title=names.get(session_id, ""),
        cwd=cwd,
        timestamp=created,
        updated_at=updated,
        archived=archived,
        storage_path=path,
        resume_argv=("codex", "resume", session_id),
        messages=event_messages or response_messages,
    )


def _discover_codex(roots: dict[Harness, tuple[Path, ...]]) -> list[Session]:
    explicit = roots.get("codex")
    if explicit is not None:
        homes = explicit
    else:
        configured = os.environ.get("CODEX_HOME", "").strip()
        homes = (
            Path(configured).expanduser() if configured else Path.home() / ".codex",
        )
    sessions: list[Session] = []
    seen: set[tuple[str, Path]] = set()
    for home in homes:
        names = _codex_names(home)
        for directory, archived in (
            (home / "sessions", False),
            (home / "archived_sessions", True),
        ):
            for path in _files(directory, ("rollout-*.jsonl", "rollout-*.jsonl.zst")):
                resolved = _resolved(path)
                if resolved is None or not resolved.is_file():
                    continue
                key = ("codex", resolved)
                if key in seen:
                    continue
                seen.add(key)
                if session := _parse_codex(resolved, archived=archived, names=names):
                    sessions.append(session)
    return sessions


def discover_jsonl_sessions(
    selected: set[Harness],
    roots: dict[Harness, tuple[Path, ...]],
) -> list[Session]:
    """Discover and normalize sessions from every selected JSONL backend."""
    sessions: list[Session] = []
    if selected.intersection({"omp", "pi"}):
        sessions.extend(
            session
            for candidate in _discover_compatible(roots).values()
            if (session := _parse_compatible(candidate)) and session.harness in selected
        )
    if "codex" in selected:
        sessions.extend(_discover_codex(roots))
    return sessions
