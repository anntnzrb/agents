#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, TypeVar

import tomllib

DEFAULT_SPAWN_CAP = 16
DEFAULT_EVIDENCE_RETRIES = 1
DEFAULT_SESSION_TRANSCRIPT_TAIL_BYTES = 64 * 1024
DEFAULT_AGENT_TRANSCRIPT_TAIL_BYTES = 32 * 1024
DEFAULT_LOCK_ATTEMPTS = 40
DEFAULT_LOCK_STALE_SECONDS = 5.0
DEFAULT_LOCK_SLEEP_MILLISECONDS = 5
DEFAULT_CONFIG_FILE_NAME = "orchestration.toml"
DEFAULT_STATE_DIRECTORY = "state/agent-orchestration"
UTC_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
MIN_POSITIVE_INTEGER = 1
MIN_NONNEGATIVE_INTEGER = 0
MIN_NONNEGATIVE_FLOAT = 0.0
MILLISECONDS_PER_SECOND = 1000
JSON_FILE_MODE = 0o600
RECOVERY_MARKER = "<codex-orchestrator>"
EVIDENCE_MARKER = "EVIDENCE_RECORDED:"
RECOVERY_CONTEXT = f"""{RECOVERY_MARKER}
You are the main coordinator after compaction.
Stay read-only: do not edit files or run mutating commands.
Delegate execution to the appropriate subagent, then inspect its evidence and integrate the result.
Resume the current task; do not restart completed work.
</codex-orchestrator>"""
SAFE_KEY_PATTERN = re.compile(r"[^a-zA-Z0-9._-]+")
EDGE_HYPHEN_PATTERN = re.compile(r"^-+|-+$")

HookInput = dict[str, object]
T = TypeVar("T")


@dataclass(frozen=True)
class Settings:
    spawn_cap: int
    evidence_retries: int
    session_transcript_tail_bytes: int
    agent_transcript_tail_bytes: int
    lock_attempts: int
    lock_stale_seconds: float
    lock_sleep_milliseconds: int

    @classmethod
    def defaults(cls) -> Settings:
        return cls(
            spawn_cap=DEFAULT_SPAWN_CAP,
            evidence_retries=DEFAULT_EVIDENCE_RETRIES,
            session_transcript_tail_bytes=DEFAULT_SESSION_TRANSCRIPT_TAIL_BYTES,
            agent_transcript_tail_bytes=DEFAULT_AGENT_TRANSCRIPT_TAIL_BYTES,
            lock_attempts=DEFAULT_LOCK_ATTEMPTS,
            lock_stale_seconds=DEFAULT_LOCK_STALE_SECONDS,
            lock_sleep_milliseconds=DEFAULT_LOCK_SLEEP_MILLISECONDS,
        )

    @classmethod
    def load(cls) -> Settings:
        defaults = cls.defaults()
        config_path = Path(__file__).with_name(DEFAULT_CONFIG_FILE_NAME)
        configured_values: Mapping[str, object] = {}

        try:
            with config_path.open("rb") as stream:
                document = tomllib.load(stream)
            section = document.get("orchestration")
            if isinstance(section, dict):
                configured_values = section
        except (OSError, tomllib.TOMLDecodeError):
            pass

        def raw_value(name: str, environment_name: str, fallback: object) -> object:
            return os.environ.get(
                environment_name,
                configured_values.get(name, fallback),
            )

        def integer_value(
            name: str,
            environment_name: str,
            fallback: int,
            minimum: int,
        ) -> int:
            raw = raw_value(name, environment_name, fallback)
            if isinstance(raw, bool) or not isinstance(raw, (str, int, float)):
                return fallback
            try:
                value = int(raw)
            except (TypeError, ValueError):
                return fallback
            return value if value >= minimum else fallback

        def float_value(
            name: str,
            environment_name: str,
            fallback: float,
            minimum: float,
        ) -> float:
            raw = raw_value(name, environment_name, fallback)
            if isinstance(raw, bool) or not isinstance(raw, (str, int, float)):
                return fallback
            try:
                value = float(raw)
            except (TypeError, ValueError):
                return fallback
            return value if value >= minimum else fallback

        return cls(
            spawn_cap=integer_value(
                "spawn_cap",
                "CODEX_ORCHESTRATION_SPAWN_CAP",
                defaults.spawn_cap,
                MIN_POSITIVE_INTEGER,
            ),
            evidence_retries=integer_value(
                "evidence_retries",
                "CODEX_ORCHESTRATION_EVIDENCE_RETRIES",
                defaults.evidence_retries,
                MIN_NONNEGATIVE_INTEGER,
            ),
            session_transcript_tail_bytes=integer_value(
                "session_transcript_tail_bytes",
                "CODEX_ORCHESTRATION_SESSION_TRANSCRIPT_TAIL_BYTES",
                defaults.session_transcript_tail_bytes,
                MIN_POSITIVE_INTEGER,
            ),
            agent_transcript_tail_bytes=integer_value(
                "agent_transcript_tail_bytes",
                "CODEX_ORCHESTRATION_AGENT_TRANSCRIPT_TAIL_BYTES",
                defaults.agent_transcript_tail_bytes,
                MIN_POSITIVE_INTEGER,
            ),
            lock_attempts=integer_value(
                "lock_attempts",
                "CODEX_ORCHESTRATION_LOCK_ATTEMPTS",
                defaults.lock_attempts,
                MIN_POSITIVE_INTEGER,
            ),
            lock_stale_seconds=float_value(
                "lock_stale_seconds",
                "CODEX_ORCHESTRATION_LOCK_STALE_SECONDS",
                defaults.lock_stale_seconds,
                MIN_NONNEGATIVE_FLOAT,
            ),
            lock_sleep_milliseconds=integer_value(
                "lock_sleep_milliseconds",
                "CODEX_ORCHESTRATION_LOCK_SLEEP_MILLISECONDS",
                defaults.lock_sleep_milliseconds,
                MIN_NONNEGATIVE_INTEGER,
            ),
        )


@dataclass(frozen=True)
class LockResult(Generic[T]):
    locked: bool
    value: T | None = None


def read_input() -> HookInput:
    try:
        raw = sys.stdin.read().strip()
        if not raw:
            return {}
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}


def emit(value: Mapping[str, object]) -> None:
    sys.stdout.write(json.dumps(value, separators=(",", ":")) + "\n")


def string_value(value: object) -> str:
    return value if isinstance(value, str) else ""


def safe_key(value: object) -> str:
    key = SAFE_KEY_PATTERN.sub("-", string_value(value))
    key = EDGE_HYPHEN_PATTERN.sub("", key)
    return key or "unknown"


def codex_home() -> Path:
    configured = os.environ.get("CODEX_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".codex"


def state_root() -> Path:
    return codex_home() / DEFAULT_STATE_DIRECTORY


def ensure_state_root() -> Path:
    root = state_root()
    root.mkdir(parents=True, exist_ok=True)
    return root


def read_json(file_path: Path, fallback: HookInput) -> HookInput:
    try:
        value = json.loads(file_path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else fallback
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return fallback


def write_json_atomic(file_path: Path, value: Mapping[str, object]) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = file_path.with_name(f"{file_path.name}.{os.getpid()}.tmp")

    try:
        file_descriptor = os.open(
            temporary_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            JSON_FILE_MODE,
        )
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, separators=(",", ":"))
            stream.write("\n")
        os.replace(temporary_path, file_path)
    except (OSError, TypeError, ValueError):
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass
        raise


def remove_file(file_path: Path) -> None:
    try:
        file_path.unlink()
    except FileNotFoundError:
        pass


def remove_lock(lock_path: Path) -> None:
    try:
        shutil.rmtree(lock_path)
    except FileNotFoundError:
        pass
    except NotADirectoryError:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def with_lock(
    lock_path: Path,
    callback: Callable[[], T],
    settings: Settings,
) -> LockResult[T]:
    acquired = False

    for _ in range(settings.lock_attempts):
        try:
            lock_path.mkdir()
            acquired = True
            break
        except FileExistsError:
            try:
                if (
                    time.time() - lock_path.stat().st_mtime
                    > settings.lock_stale_seconds
                ):
                    remove_lock(lock_path)
                    continue
            except OSError:
                continue
            time.sleep(settings.lock_sleep_milliseconds / MILLISECONDS_PER_SECOND)
        except OSError:
            return LockResult(False)

    if not acquired:
        return LockResult(False)

    try:
        return LockResult(True, callback())
    finally:
        remove_lock(lock_path)


def session_id(input_data: Mapping[str, object]) -> str:
    return string_value(input_data.get("session_id"))


def spawn_state_path(input_data: Mapping[str, object]) -> Path:
    return state_root() / f"spawn-{safe_key(session_id(input_data))}.json"


def evidence_state_path(input_data: Mapping[str, object]) -> Path:
    worker_key = string_value(input_data.get("agent_id")) or string_value(
        input_data.get("agent_type")
    )
    return state_root() / (
        f"evidence-{safe_key(session_id(input_data))}-{safe_key(worker_key)}.json"
    )


def nonnegative_number(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return 0
    return int(value)


def handle_spawn_guard(input_data: HookInput, settings: Settings) -> None:
    if not session_id(input_data):
        return

    ensure_state_root()
    state_path = spawn_state_path(input_data)

    def update_state() -> dict[str, object]:
        current = read_json(state_path, {"count": 0})
        count = nonnegative_number(current.get("count"))
        cap = settings.spawn_cap

        if count >= cap:
            return {"denied": True, "count": count, "cap": cap}

        write_json_atomic(
            state_path,
            {
                "count": count + 1,
                "updatedAt": time.strftime(UTC_TIMESTAMP_FORMAT, time.gmtime()),
            },
        )
        return {"denied": False, "count": count + 1, "cap": cap}

    result = with_lock(
        state_path.with_name(state_path.name + ".lock"),
        update_state,
        settings,
    )
    if (
        not result.locked
        or not isinstance(result.value, dict)
        or not result.value.get("denied")
    ):
        return

    emit(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    f"Session agent fan-out cap reached ({result.value['cap']} total spawn "
                    "attempts). Integrate existing worker results before spawning more."
                ),
            }
        }
    )


def read_tail(file_path: Path, maximum_bytes: int) -> str:
    with file_path.open("rb") as stream:
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(max(0, size - maximum_bytes))
        return stream.read().decode("utf-8", errors="replace")


def handle_session_start(input_data: HookInput, settings: Settings) -> None:
    if string_value(input_data.get("source")) != "compact" or string_value(
        input_data.get("agent_type")
    ):
        return

    transcript_path = string_value(input_data.get("transcript_path"))
    if transcript_path:
        try:
            if RECOVERY_MARKER in read_tail(
                Path(transcript_path), settings.session_transcript_tail_bytes
            ):
                return
        except OSError:
            pass

    emit(
        {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": RECOVERY_CONTEXT,
            }
        }
    )


def last_assistant_message(input_data: Mapping[str, object], settings: Settings) -> str:
    direct_message = input_data.get("last_assistant_message")
    if isinstance(direct_message, str):
        return direct_message

    transcript_path = string_value(input_data.get("agent_transcript_path"))
    if not transcript_path:
        return ""

    try:
        return read_tail(Path(transcript_path), settings.agent_transcript_tail_bytes)
    except OSError:
        return ""


def evidence_path_from_message(message: str) -> str:
    last_line = message.replace("\r\n", "\n").rstrip().split("\n")[-1]
    if not last_line.startswith(EVIDENCE_MARKER):
        return ""
    return last_line[len(EVIDENCE_MARKER) :].strip()


def absolute_without_symlink_resolution(file_path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(file_path)))


def is_nonempty_regular_file(candidate: str, cwd: str) -> bool:
    candidate_path = Path(candidate).expanduser()
    if not candidate_path.is_absolute():
        candidate_path = (
            Path(cwd).expanduser() / candidate_path
            if cwd
            else Path.cwd() / candidate_path
        )

    try:
        stats = absolute_without_symlink_resolution(candidate_path).lstat()
    except OSError:
        return False

    return (
        stat.S_ISREG(stats.st_mode)
        and not stat.S_ISLNK(stats.st_mode)
        and stats.st_size > 0
    )


def handle_subagent_stop(input_data: HookInput, settings: Settings) -> None:
    if (
        input_data.get("stop_hook_active")
        or not session_id(input_data)
        or not string_value(input_data.get("agent_type"))
    ):
        return

    evidence_path = evidence_path_from_message(
        last_assistant_message(input_data, settings)
    )
    valid = bool(evidence_path) and is_nonempty_regular_file(
        evidence_path,
        string_value(input_data.get("cwd")),
    )
    state_path = evidence_state_path(input_data)
    ensure_state_root()

    def update_state() -> dict[str, object]:
        if valid:
            remove_file(state_path)
            return {"block": False}

        current = read_json(state_path, {"attempts": 0})
        attempts = nonnegative_number(current.get("attempts"))
        if attempts < settings.evidence_retries:
            write_json_atomic(
                state_path,
                {
                    "attempts": attempts + 1,
                    "updatedAt": time.strftime(UTC_TIMESTAMP_FORMAT, time.gmtime()),
                },
            )
            return {"block": True, "attempts": attempts + 1}

        remove_file(state_path)
        return {"block": False}

    result = with_lock(
        state_path.with_name(state_path.name + ".lock"),
        update_state,
        settings,
    )
    if (
        not result.locked
        or not isinstance(result.value, dict)
        or not result.value.get("block")
    ):
        return

    emit(
        {
            "decision": "block",
            "reason": (
                "Record a non-empty evidence file and finish the response with exactly "
                f"{EVIDENCE_MARKER} <path>. The hook applies a bounded retry policy; "
                "do not claim "
                "completion without the artifact."
            ),
        }
    )


def handle_session_end(input_data: HookInput) -> None:
    if not session_id(input_data):
        return

    root = state_root()
    prefix = safe_key(session_id(input_data))
    spawn_file = f"spawn-{prefix}.json"
    evidence_prefix = f"evidence-{prefix}-"

    try:
        entries = list(root.iterdir())
    except OSError:
        return

    for entry in entries:
        if entry.name == spawn_file or (
            entry.name.startswith(evidence_prefix) and entry.name.endswith(".json")
        ):
            remove_file(entry)


def main() -> None:
    input_data = read_input()
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    settings = Settings.load()

    try:
        if command == "session-start":
            handle_session_start(input_data, settings)
        elif command == "pre-tool-use":
            handle_spawn_guard(input_data, settings)
        elif command == "subagent-stop":
            handle_subagent_stop(input_data, settings)
        elif command == "session-end":
            handle_session_end(input_data)
    except (OSError, TypeError, ValueError, RuntimeError):
        # Hooks are guardrails, not a reason to break Codex. Fail open on hook errors.
        return


if __name__ == "__main__":
    main()
