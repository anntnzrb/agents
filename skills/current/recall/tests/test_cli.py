# Copyright (c) 2026
"""Executable contracts for the multi-harness session finder."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import sqlite3
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Final, cast

import zstandard

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

SKILL: Final = Path(__file__).resolve().parents[1]
CLI: Final = SKILL / "scripts" / "cli.py"
RECORD_KEYS: Final = {
    "archived",
    "cwd",
    "harness",
    "match_type",
    "resume_argv",
    "score",
    "session_id",
    "snippet",
    "storage_path",
    "timestamp",
    "title",
    "updated_at",
}


def _jsonl(rows: Iterable[Mapping[str, object]]) -> bytes:
    return b"".join(
        json.dumps(row, separators=(",", ":")).encode() + b"\n" for row in rows
    )


def write_jsonl(path: Path, rows: Iterable[Mapping[str, object]]) -> Path:
    """Write deterministic JSONL fixture rows."""
    path.parent.mkdir(parents=True, exist_ok=True)
    _ = path.write_bytes(_jsonl(rows))
    return path.resolve()


def write_gzip(path: Path, rows: Iterable[Mapping[str, object]]) -> Path:
    """Write a deterministic gzip JSONL fixture."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with (
        path.open("wb") as stream,
        gzip.GzipFile(filename="", mode="wb", fileobj=stream, mtime=0) as compressed,
    ):
        _ = compressed.write(_jsonl(rows))
    return path.resolve()


def write_zstd(path: Path, rows: Iterable[Mapping[str, object]]) -> Path:
    """Write a deterministic zstd JSONL fixture."""
    path.parent.mkdir(parents=True, exist_ok=True)
    _ = path.write_bytes(zstandard.ZstdCompressor().compress(_jsonl(rows)))
    return path.resolve()


def set_mtime(path: Path, epoch: int) -> None:
    """Set fixture access and modification time."""
    os.utime(path, (epoch, epoch))


def clean_env(tmp_path: Path) -> dict[str, str]:
    """Return an environment with every default store isolated."""
    env = os.environ.copy()
    home = tmp_path / "home"
    xdg_data = tmp_path / "xdg-data"
    home.mkdir(exist_ok=True)
    xdg_data.mkdir(exist_ok=True)
    env.update(
        {
            "HOME": str(home),
            "XDG_DATA_HOME": str(xdg_data),
            "PI_CODING_AGENT_DIR": str(tmp_path / "pi-agent"),
            "CODEX_HOME": str(tmp_path / "codex-home"),
            "T3CODE_HOME": str(tmp_path / "t3-home"),
            "UV_QUIET": "1",
        }
    )
    _ = env.pop("PI_CODING_AGENT_SESSION_DIR", None)
    _ = env.pop("OPENCODE_DB", None)
    return env


def run_cli(
    tmp_path: Path,
    query: Sequence[str] = ("needle",),
    *options: str,
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Invoke the public PEP 723 entry point."""
    command = ["uv", "run", "--quiet", "--script", str(CLI), *query, *options]
    return subprocess.run(
        command,
        cwd=cwd or tmp_path,
        env=dict(env or clean_env(tmp_path)),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def records(result: subprocess.CompletedProcess[str]) -> list[dict[str, object]]:
    """Decode a successful compact-JSON result."""
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout.endswith("\n")
    assert "\n" not in result.stdout[:-1]
    value = cast("object", json.loads(result.stdout))
    assert isinstance(value, list)
    items = cast("list[object]", value)
    assert all(
        isinstance(item, dict)
        and all(isinstance(key, str) for key in cast("dict[object, object]", item))
        for item in items
    )
    return [
        {str(key): item for key, item in cast("dict[object, object]", record).items()}
        for record in items
        if isinstance(record, dict)
    ]


def assert_record_shape(record: Mapping[str, object]) -> None:
    """Assert the exact public record schema and field types."""
    assert set(record) == RECORD_KEYS
    assert record["harness"] in {"omp", "pi", "codex", "t3code", "opencode"}
    for key in (
        "session_id",
        "title",
        "cwd",
        "timestamp",
        "updated_at",
        "storage_path",
        "match_type",
        "snippet",
    ):
        assert isinstance(record[key], str)
    assert isinstance(record["archived"], bool)
    assert isinstance(record["score"], int)
    argv = record["resume_argv"]
    assert argv is None or isinstance(argv, list)
    if argv is not None:
        strings = cast("list[object]", argv)
        assert all(isinstance(item, str) for item in strings)


def omp_rows(
    session_id: str,
    *,
    title: str,
    user: str,
    assistant: str = "assistant transcript",
    timestamp: str = "2026-01-02T03:04:05.123456Z",
) -> list[dict[str, object]]:
    """Return an OMP v3 session with its authoritative title slot."""
    return [
        {
            "type": "session",
            "version": 3,
            "id": session_id,
            "timestamp": timestamp,
            "cwd": "/work/omp",
            "title": "ignored header title",
        },
        {"type": "title", "title": title},
        {
            "type": "message",
            "message": {"role": "user", "content": user},
        },
        {
            "type": "message",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": assistant}],
            },
        },
    ]


def pi_rows(
    session_id: str,
    *,
    name: str,
    user: str,
    timestamp: str = "2026-02-03T04:05:06.789Z",
) -> list[dict[str, object]]:
    """Return a Pi v3 session."""
    return [
        {
            "type": "session",
            "version": 3,
            "id": session_id,
            "timestamp": timestamp,
            "cwd": "/work/pi",
        },
        {"type": "session_info", "name": f"  {name}  "},
        {"type": "message", "message": {"role": "user", "content": user}},
        {
            "type": "message",
            "message": {"role": "assistant", "content": "pi transcript"},
        },
    ]


def codex_rows(
    session_id: str,
    *,
    cwd: str = "/work/codex",
    user: str = "codex event needle",
    assistant: str = "codex answer",
    timestamp: str = "2026-03-04T05:06:07.123456+00:00",
) -> list[dict[str, object]]:
    """Return a Codex rollout containing event and mirrored response messages."""
    return [
        {
            "timestamp": timestamp,
            "type": "session_meta",
            "payload": {"id": session_id, "cwd": cwd, "timestamp": timestamp},
        },
        {
            "type": "event_msg",
            "payload": {"type": "user_message", "message": user},
        },
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "mirrored-only"}],
            },
        },
        {
            "type": "event_msg",
            "payload": {"type": "agent_message", "message": assistant},
        },
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "mirrored answer"}],
            },
        },
    ]


def create_t3(path: Path) -> sqlite3.Connection:
    """Create the exact required T3 projection schema."""
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    _ = connection.executescript(
        """
        CREATE TABLE projection_projects (
          project_id TEXT PRIMARY KEY,
          workspace_root TEXT NOT NULL
        );
        CREATE TABLE projection_threads (
          thread_id TEXT PRIMARY KEY,
          project_id TEXT,
          title TEXT,
          worktree_path TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT,
          archived_at TEXT,
          deleted_at TEXT
        );
        CREATE TABLE projection_thread_messages (
          message_id TEXT PRIMARY KEY,
          thread_id TEXT NOT NULL,
          role TEXT NOT NULL,
          text TEXT,
          created_at TEXT NOT NULL
        );
        """
    )
    return connection


def create_opencode(path: Path) -> sqlite3.Connection:
    """Create current and legacy OpenCode transcript schemas."""
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    _ = connection.executescript(
        """
        CREATE TABLE session (
          id TEXT PRIMARY KEY,
          directory TEXT,
          title TEXT,
          time_created INTEGER NOT NULL,
          time_updated INTEGER,
          time_archived INTEGER
        );
        CREATE TABLE session_message (
          session_id TEXT NOT NULL,
          seq INTEGER NOT NULL,
          type TEXT NOT NULL,
          data TEXT NOT NULL
        );
        CREATE TABLE message (
          id TEXT PRIMARY KEY,
          session_id TEXT NOT NULL,
          time_created INTEGER NOT NULL,
          data TEXT NOT NULL
        );
        CREATE TABLE part (
          id TEXT PRIMARY KEY,
          message_id TEXT NOT NULL,
          session_id TEXT NOT NULL,
          data TEXT NOT NULL
        );
        """
    )
    return connection


def test_all_harnesses_exact_contract_timestamps_and_argv(tmp_path: Path) -> None:
    """All adapters normalize their native artifacts into the exact public contract."""
    env = clean_env(tmp_path)

    omp = write_jsonl(
        tmp_path / "omp" / "active.jsonl",
        omp_rows("omp-id", title="OMP needle", user="omp user"),
    )
    set_mtime(omp, 1_767_225_600)
    pi = write_jsonl(
        tmp_path / "pi" / "active.jsonl",
        pi_rows("pi-id", name="Pi needle", user="pi user"),
    )
    set_mtime(pi, 1_767_312_000)

    codex_home = tmp_path / "codex"
    codex = write_jsonl(
        codex_home / "sessions" / "2026" / "rollout-active.jsonl",
        codex_rows("codex-id", user="codex needle"),
    )
    set_mtime(codex, 1_767_398_400)
    _ = write_jsonl(
        codex_home / "session_index.jsonl",
        [{"id": "codex-id", "thread_name": "Codex needle"}],
    )

    t3 = tmp_path / "t3.sqlite"
    with create_t3(t3) as connection:
        _ = connection.execute(
            "INSERT INTO projection_projects VALUES (?, ?)",
            ("project", "/workspace/t3"),
        )
        _ = connection.execute(
            "INSERT INTO projection_threads VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "t3-id",
                "project",
                "T3 needle",
                None,
                "2026-04-05T06:07:08.999999+00:00",
                "2026-04-06T07:08:09+00:00",
                None,
                None,
            ),
        )
        _ = connection.execute(
            "INSERT INTO projection_thread_messages VALUES (?, ?, ?, ?, ?)",
            ("m1", "t3-id", "user", "t3 user", "2026-04-05T06:08:00Z"),
        )
    connection.close()

    opencode = tmp_path / "opencode.db"
    with create_opencode(opencode) as connection:
        _ = connection.execute(
            "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?)",
            (
                "oc-id",
                "/workspace/opencode",
                "OpenCode needle",
                1_775_347_200_123,
                1_775_433_600_456,
                None,
            ),
        )
        _ = connection.execute(
            "INSERT INTO session_message VALUES (?, ?, ?, ?)",
            ("oc-id", 1, "user", json.dumps({"text": "opencode user"})),
        )
    connection.close()

    result = run_cli(
        tmp_path,
        ("needle",),
        "--root",
        f"omp={omp.parent}",
        "--root",
        f"pi={pi.parent}",
        "--root",
        f"codex={codex_home}",
        "--root",
        f"t3code={t3}",
        "--root",
        f"opencode={opencode}",
        "--limit",
        "20",
        env=env,
    )
    found = {item["harness"]: item for item in records(result)}
    assert set(found) == {"omp", "pi", "codex", "t3code", "opencode"}
    for record in found.values():
        assert_record_shape(record)
        assert record["match_type"] == "title"
        assert record["score"] == 4
        storage_path = record["storage_path"]
        assert isinstance(storage_path, str)
        assert Path(storage_path).is_absolute()

    assert found["omp"]["timestamp"] == "2026-01-02T03:04:05.123Z"
    assert found["omp"]["updated_at"] == "2026-01-01T00:00:00.000Z"
    assert found["omp"]["resume_argv"] == ["omp", "--resume", str(omp)]
    assert found["pi"]["timestamp"] == "2026-02-03T04:05:06.789Z"
    assert found["pi"]["updated_at"] == "2026-01-02T00:00:00.000Z"
    assert found["pi"]["resume_argv"] == ["pi", "--session", str(pi)]
    assert found["codex"]["timestamp"] == "2026-03-04T05:06:07.123Z"
    assert found["codex"]["resume_argv"] == ["codex", "resume", "codex-id"]
    assert found["t3code"]["timestamp"] == "2026-04-05T06:07:08.999Z"
    assert found["t3code"]["cwd"] == "/workspace/t3"
    assert found["t3code"]["resume_argv"] is None
    assert found["opencode"]["timestamp"] == "2026-04-05T00:00:00.123Z"
    assert found["opencode"]["updated_at"] == "2026-04-06T00:00:00.456Z"
    assert found["opencode"]["resume_argv"] == [
        "opencode",
        "/workspace/opencode",
        "--session",
        "oc-id",
    ]


def test_archives_compression_and_transcript_selection(tmp_path: Path) -> None:
    """Archived gzip/zstd artifacts remain searchable with verified argv semantics."""
    omp_root = tmp_path / "omp"
    omp = write_gzip(
        omp_root / "cold.jsonl.gz",
        omp_rows("omp-cold", title="cold", user="omp archiveonly"),
    )
    codex_home = tmp_path / "codex"
    codex = write_zstd(
        codex_home / "archived_sessions" / "rollout-cold.jsonl.zst",
        codex_rows("codex-cold", user="## My request for Codex: archiveonly"),
    )
    _ = write_jsonl(
        codex_home / "session_index.jsonl",
        [{"id": "codex-cold", "thread_name": "cold codex"}],
    )

    omp_found = records(
        run_cli(
            tmp_path,
            ("archiveonly",),
            "--harness",
            "omp",
            "--root",
            f"omp={omp_root}",
        )
    )
    assert omp_found == [
        {
            **omp_found[0],
            "archived": True,
            "storage_path": str(omp),
            "resume_argv": None,
            "match_type": "user_message",
            "score": 3,
        }
    ]

    codex_found = records(
        run_cli(
            tmp_path,
            ("archiveonly",),
            "--harness",
            "codex",
            "--root",
            f"codex={codex_home}",
        )
    )
    assert len(codex_found) == 1
    assert codex_found[0]["archived"] is True
    assert codex_found[0]["storage_path"] == str(codex)
    assert codex_found[0]["resume_argv"] == ["codex", "resume", "codex-cold"]
    assert codex_found[0]["match_type"] == "user_message"
    assert codex_found[0]["score"] == 3
    snippet = codex_found[0]["snippet"]
    assert isinstance(snippet, str)
    assert "mirrored-only" not in snippet


def test_omp_custom_message_payload_is_searchable(tmp_path: Path) -> None:
    """OMP indexes authored text carried by a custom_message payload."""
    root = tmp_path / "omp"
    rows = omp_rows("custom", title="unrelated", user="ordinary")
    rows.append(
        {
            "type": "custom_message",
            "custom_message": {
                "role": "user",
                "content": [{"type": "text", "text": "custompayloadneedle"}],
            },
        }
    )
    artifact = write_jsonl(root / "custom.jsonl", rows)

    found = records(
        run_cli(
            tmp_path,
            ("custompayloadneedle",),
            "--harness",
            "omp",
            "--root",
            f"omp={root}",
        )
    )
    assert len(found) == 1
    assert found[0]["session_id"] == "custom"
    assert found[0]["storage_path"] == str(artifact)
    assert found[0]["match_type"] == "user_message"
    assert found[0]["score"] == 3
    snippet = found[0]["snippet"]
    assert isinstance(snippet, str)
    assert "custompayloadneedle" in snippet


def test_matching_scores_order_and_limit_after_sort(tmp_path: Path) -> None:
    """Use whitespace AND, highest category, and deterministic ranking."""
    root = tmp_path / "omp"
    fixtures = [
        ("title", "Alpha BETA", "none", "none", "/work/omp", 1_767_225_604),
        ("user", "none", "alpha xx beta", "none", "/work/omp", 1_767_225_603),
        ("transcript", "none", "alpha", "beta", "/work/omp", 1_767_225_602),
        ("cwd", "none", "none", "none", "/alpha/beta", 1_767_225_601),
    ]
    for session_id, title, user, assistant, cwd, mtime in fixtures:
        rows = omp_rows(session_id, title=title, user=user, assistant=assistant)
        rows[0]["cwd"] = cwd
        path = write_jsonl(root / f"{session_id}.jsonl", rows)
        set_mtime(path, mtime)

    found = records(
        run_cli(
            tmp_path,
            ("  ALPHA\t", "beta  "),
            "--harness",
            "omp",
            "--root",
            f"omp={root}",
            "--limit",
            "3",
        )
    )
    assert [
        (item["session_id"], item["match_type"], item["score"]) for item in found
    ] == [
        ("title", "title", 4),
        ("user", "user_message", 3),
        ("transcript", "transcript", 2),
    ]


def test_pi_settings_precedence_and_explicit_override(tmp_path: Path) -> None:
    """Project Pi settings override global settings; explicit roots override both."""
    env = clean_env(tmp_path)
    agent = Path(env["PI_CODING_AGENT_DIR"])
    project = tmp_path / "project"
    project.mkdir()
    global_root = tmp_path / "global-sessions"
    project_root = tmp_path / "project-sessions"
    explicit_root = tmp_path / "explicit-sessions"
    _ = write_jsonl(global_root / "g.jsonl", pi_rows("global", name="needle", user="x"))
    _ = write_jsonl(
        project_root / "p.jsonl", pi_rows("project", name="needle", user="x")
    )
    _ = write_jsonl(
        explicit_root / "e.jsonl", pi_rows("explicit", name="needle", user="x")
    )
    agent.mkdir(parents=True)
    _ = (agent / "settings.json").write_text(
        json.dumps({"sessionDir": str(global_root)})
    )
    (project / ".pi").mkdir()
    _ = (project / ".pi" / "settings.json").write_text(
        json.dumps({"sessionDir": str(project_root)})
    )

    default_found = records(
        run_cli(tmp_path, ("needle",), "--harness", "pi", env=env, cwd=project)
    )
    assert [item["session_id"] for item in default_found] == ["project"]

    override_found = records(
        run_cli(
            tmp_path,
            ("needle",),
            "--harness",
            "pi",
            "--root",
            f"pi={explicit_root}",
            env=env,
            cwd=project,
        )
    )
    assert [item["session_id"] for item in override_found] == ["explicit"]


def test_identity_and_candidate_deduplication(tmp_path: Path) -> None:
    """Artifact and identity dedup happen before matching with documented preference."""
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    active = write_jsonl(
        root_a / "same.jsonl",
        omp_rows("duplicate", title="kept", user="visible needle"),
    )
    archived = write_gzip(
        root_b / "same.jsonl.gz",
        omp_rows("duplicate", title="discarded needle-only", user="absent"),
    )
    set_mtime(active, 1_700_000_000)
    set_mtime(archived, 1_800_000_000)

    found = records(
        run_cli(
            tmp_path,
            ("needle",),
            "--harness",
            "omp",
            "--root",
            f"omp={root_a}",
            "--root",
            f"omp={root_a}",
            "--root",
            f"omp={root_b}",
        )
    )
    assert len(found) == 1
    assert found[0]["storage_path"] == str(active)
    assert found[0]["archived"] is False

    discarded_only = records(
        run_cli(
            tmp_path,
            ("discarded",),
            "--harness",
            "omp",
            "--root",
            f"omp={root_a}",
            "--root",
            f"omp={root_b}",
        )
    )
    assert discarded_only == []


def test_shared_jsonl_single_owner_and_conflicting_roots(tmp_path: Path) -> None:
    """Give one JSONL one owner and reject conflicting explicit ownership."""
    shared = tmp_path / "shared"
    _ = write_jsonl(shared / "pi.jsonl", pi_rows("pi-owner", name="needle", user="x"))
    found = records(
        run_cli(tmp_path, ("needle",), "--root", f"pi={shared}", "--limit", "20")
    )
    assert [(item["harness"], item["session_id"]) for item in found] == [
        ("pi", "pi-owner")
    ]

    conflict = run_cli(
        tmp_path,
        ("needle",),
        "--root",
        f"omp={shared}",
        "--root",
        f"pi={shared}",
    )
    assert conflict.returncode == 2
    assert conflict.stdout == ""
    assert conflict.stderr.startswith("session-finder: ")


def test_t3_archived_deleted_order_and_read_only(tmp_path: Path) -> None:
    """Include archives, exclude tombstones, order messages, and never write."""
    database = tmp_path / "state.sqlite"
    with create_t3(database) as connection:
        _ = connection.execute(
            "INSERT INTO projection_projects VALUES ('p', '/workspace')"
        )
        for values in (
            (
                "active",
                "p",
                "active",
                "/worktree",
                "2026-01-01T00:00:00Z",
                "2026-01-03T00:00:00Z",
                None,
                None,
            ),
            (
                "archived",
                "p",
                "archived",
                None,
                "2026-01-02T00:00:00Z",
                "2026-01-04T00:00:00Z",
                "2026-01-05T00:00:00Z",
                None,
            ),
            (
                "deleted",
                "p",
                "needle",
                None,
                "2026-01-03T00:00:00Z",
                "2026-01-05T00:00:00Z",
                None,
                "2026-01-06T00:00:00Z",
            ),
        ):
            _ = connection.execute(
                "INSERT INTO projection_threads VALUES (?, ?, ?, ?, ?, ?, ?, ?)", values
            )
        _ = connection.executemany(
            "INSERT INTO projection_thread_messages VALUES (?, ?, ?, ?, ?)",
            [
                ("z", "archived", "assistant", "second", "2026-01-02T02:00:00Z"),
                ("a", "archived", "user", "archiveonly needle", "2026-01-02T01:00:00Z"),
                ("x", "active", "user", "needle", "2026-01-01T01:00:00Z"),
            ],
        )
    connection.close()
    before = hashlib.sha256(database.read_bytes()).digest()
    found = records(
        run_cli(
            tmp_path,
            ("needle",),
            "--harness",
            "t3code",
            "--root",
            f"t3code={database}",
            "--limit",
            "20",
        )
    )
    assert [(item["session_id"], item["archived"]) for item in found] == [
        ("archived", True),
        ("active", False),
    ]
    archived = found[0]
    assert archived["cwd"] == "/workspace"
    assert archived["resume_argv"] is None
    snippet = archived["snippet"]
    assert isinstance(snippet, str)
    assert "archiveonly" in snippet
    assert hashlib.sha256(database.read_bytes()).digest() == before


def test_opencode_current_legacy_fallback_and_argv(tmp_path: Path) -> None:
    """Prefer current rows and fall back per session to legacy rows."""
    database = tmp_path / "opencode.db"
    with create_opencode(database) as connection:
        _ = connection.executemany(
            "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    "current",
                    "/repo",
                    "current",
                    1_700_000_000_000,
                    1_700_000_001_000,
                    None,
                ),
                (
                    "legacy",
                    "",
                    "legacy",
                    1_700_000_002_000,
                    1_700_000_003_000,
                    1_700_000_004_000,
                ),
            ],
        )
        _ = connection.executemany(
            "INSERT INTO session_message VALUES (?, ?, ?, ?)",
            [
                (
                    "current",
                    2,
                    "assistant",
                    json.dumps({"content": [{"type": "text", "text": "answer"}]}),
                ),
                ("current", 1, "user", json.dumps({"text": "needle current"})),
            ],
        )
        _ = connection.execute(
            "INSERT INTO message VALUES (?, ?, ?, ?)",
            ("mirror", "current", 1, json.dumps({"role": "user"})),
        )
        _ = connection.execute(
            "INSERT INTO part VALUES (?, ?, ?, ?)",
            (
                "mirror-part",
                "mirror",
                "current",
                json.dumps({"type": "text", "text": "mirroronly"}),
            ),
        )
        _ = connection.execute(
            "INSERT INTO message VALUES (?, ?, ?, ?)",
            ("legacy-message", "legacy", 2, json.dumps({"role": "user"})),
        )
        _ = connection.execute(
            "INSERT INTO part VALUES (?, ?, ?, ?)",
            (
                "legacy-part",
                "legacy-message",
                "legacy",
                json.dumps({"type": "text", "text": "archiveonly needle"}),
            ),
        )
    connection.close()
    before = hashlib.sha256(database.read_bytes()).digest()
    found = records(
        run_cli(
            tmp_path,
            ("needle",),
            "--harness",
            "opencode",
            "--root",
            f"opencode={database}",
            "--limit",
            "20",
        )
    )
    by_id = {item["session_id"]: item for item in found}
    assert by_id["current"]["resume_argv"] == [
        "opencode",
        "/repo",
        "--session",
        "current",
    ]
    assert by_id["legacy"]["resume_argv"] == ["opencode", "--session", "legacy"]
    assert by_id["legacy"]["archived"] is True
    snippet = by_id["current"]["snippet"]
    assert isinstance(snippet, str)
    assert "mirroronly" not in snippet
    assert hashlib.sha256(database.read_bytes()).digest() == before


def test_filters_empty_results_and_root_validation(tmp_path: Path) -> None:
    """Filters isolate harnesses; missing and incompatible explicit roots are errors."""
    omp_root = tmp_path / "omp"
    _ = write_jsonl(omp_root / "x.jsonl", omp_rows("omp", title="needle", user="x"))
    assert records(run_cli(tmp_path, ("absent",), "--root", f"omp={omp_root}")) == []
    assert records(run_cli(tmp_path, ("needle",), "--harness", "codex")) == []

    for mapping in (
        f"omp={tmp_path / 'missing'}",
        "unknown=/tmp",
        "omp=",
    ):
        result = run_cli(tmp_path, ("needle",), "--root", mapping)
        assert result.returncode == 2
        assert result.stdout == ""
        assert result.stderr.startswith("session-finder: ")

    incompatible = tmp_path / "bad.sqlite"
    sqlite3.connect(incompatible).close()
    corrupt = tmp_path / "corrupt.sqlite"
    _ = corrupt.write_bytes(b"not sqlite")
    for harness, path in (("t3code", incompatible), ("opencode", corrupt)):
        result = run_cli(tmp_path, ("needle",), "--root", f"{harness}={path}")
        assert result.returncode == 2
        assert result.stdout == ""
        assert result.stderr.startswith("session-finder: ")


def test_malformed_artifacts_and_incompatible_defaults_are_skipped(
    tmp_path: Path,
) -> None:
    """One corrupt default artifact/store cannot poison otherwise valid discovery."""
    env = clean_env(tmp_path)
    omp_root = Path(env["XDG_DATA_HOME"]) / "omp" / "sessions"
    omp_root.mkdir(parents=True)
    _ = (omp_root / "bad.jsonl").write_text("{broken\n")
    _ = write_jsonl(omp_root / "good.jsonl", omp_rows("good", title="needle", user="x"))

    t3_default = Path(env["T3CODE_HOME"]) / "userdata" / "state.sqlite"
    t3_default.parent.mkdir(parents=True)
    _ = t3_default.write_bytes(b"corrupt")
    opencode_default = Path(env["XDG_DATA_HOME"]) / "opencode" / "opencode.db"
    opencode_default.parent.mkdir(parents=True)
    sqlite3.connect(opencode_default).close()

    found = records(run_cli(tmp_path, ("needle",), "--limit", "20", env=env))
    assert [(item["harness"], item["session_id"]) for item in found] == [
        ("omp", "good")
    ]


def test_duplicate_identity_latest_then_smallest_path(tmp_path: Path) -> None:
    """Equal-state duplicate identities prefer latest update then smallest path."""
    older_root = tmp_path / "z-root"
    newer_a_root = tmp_path / "a-root"
    newer_b_root = tmp_path / "b-root"
    older = write_jsonl(
        older_root / "s.jsonl", pi_rows("same", name="needle", user="x")
    )
    newer_a = write_jsonl(
        newer_a_root / "s.jsonl", pi_rows("same", name="needle", user="x")
    )
    newer_b = write_jsonl(
        newer_b_root / "s.jsonl", pi_rows("same", name="needle", user="x")
    )
    set_mtime(older, 1_700_000_000)
    set_mtime(newer_a, 1_800_000_000)
    set_mtime(newer_b, 1_800_000_000)
    found = records(
        run_cli(
            tmp_path,
            ("needle",),
            "--harness",
            "pi",
            "--root",
            f"pi={older_root}",
            "--root",
            f"pi={newer_b_root}",
            "--root",
            f"pi={newer_a_root}",
        )
    )
    assert len(found) == 1
    assert found[0]["storage_path"] == str(newer_a)


def test_invalid_limit_is_invocation_error(tmp_path: Path) -> None:
    """The public CLI rejects non-positive limits before discovery."""
    result = run_cli(tmp_path, ("needle",), "--limit", "0")
    assert result.returncode == 2
    assert result.stdout == ""
    assert "limit must be a positive integer" in result.stderr


def test_missing_explicit_root_validated_even_when_filtered_out(
    tmp_path: Path,
) -> None:
    """Validate every explicit mapping, including filtered-out harness roots."""
    for harness in ("omp", "pi", "codex", "t3code", "opencode"):
        result = run_cli(
            tmp_path,
            ("needle",),
            "--harness",
            "omp" if harness != "omp" else "pi",
            "--root",
            f"{harness}={tmp_path / 'missing'}",
        )
        assert result.returncode == 2
        assert result.stdout == ""
        assert result.stderr.startswith("session-finder: ")
