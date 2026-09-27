"""Resolve the omp binary and execute a single omp search."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from models import (
    OmpBinaryNotFoundError,
    SearchFailurePayload,
    SearchResult,
    SearchSuccessPayload,
)
from parser import parse_search_output, redact, strip_terminal_controls


@dataclass(frozen=True)
class SingleSearchExecutionOptions:
    """Options forwarded to one omp search invocation."""

    query_words: list[str]
    provider: str | None = None
    recency: Literal["day", "week", "month", "year"] | None = None
    limit: int | None = None
    full: bool | None = None
    include_raw: bool | None = None
    timeout_seconds: float | None = None
    omp_bin: str | None = None


@dataclass(frozen=True)
class _RunOutcome:
    """Captured result of one child process run."""

    is_timeout: bool
    stdout: str
    stderr: str
    exit_code: int


def _path_exists(file_path: str) -> bool:
    """Return True when the path exists; never raises."""
    try:
        return Path(file_path).exists()
    except Exception:
        return False


def resolve_omp(binary: str | None = None) -> str:
    """Resolve the omp executable path or raise OmpBinaryNotFoundError."""
    candidate = binary or os.environ.get("OMP_BIN")
    if candidate and _path_exists(candidate):
        return candidate

    on_path = shutil.which("omp")
    if on_path:
        return on_path

    raise OmpBinaryNotFoundError(
        "required executable 'omp' was not found on PATH or via OMP_BIN"
    )


def failure_message(cleaned_stdout: str, stderr: str, return_code: int) -> str:
    """Pick the last non-empty line of stderr, then stdout, else a default."""
    for value in (stderr, cleaned_stdout):
        lines = [line.strip() for line in value.split("\n")]
        lines = [line for line in lines if line]
        if lines:
            return lines[-1]
    return f"omp search exited with code {return_code}"


def _as_text(value: str | bytes | None) -> str:
    """Normalize captured process output to text."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _run_command(
    command: list[str], env: dict[str, str], timeout_seconds: float
) -> _RunOutcome:
    """Run the child process; capture output, timeout, and spawn failures."""
    try:
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            env=env,
            timeout=timeout_seconds,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        return _RunOutcome(
            is_timeout=False,
            stdout=completed.stdout,
            stderr=completed.stderr,
            exit_code=completed.returncode,
        )
    except subprocess.TimeoutExpired as exc:
        return _RunOutcome(
            is_timeout=True,
            stdout=_as_text(exc.stdout),
            stderr=_as_text(exc.stderr),
            exit_code=124,
        )
    except Exception as err:
        return _RunOutcome(
            is_timeout=False,
            stdout="",
            stderr=str(err),
            exit_code=1,
        )


def _format_seconds(timeout_seconds: float) -> str:
    """Format a timeout value the way a JS number interpolates."""
    if float(timeout_seconds).is_integer():
        return str(int(timeout_seconds))
    return repr(timeout_seconds)


def execute_single_search(
    options: SingleSearchExecutionOptions, resolved_binary: str
) -> SearchResult:
    """Run one omp search and shape the JSON envelope payload."""
    fallback_query = " ".join(options.query_words)
    command = [resolved_binary, "search"]

    if options.provider:
        command += ["--provider", options.provider]
    if options.recency:
        command += ["--recency", options.recency]
    if options.limit is not None:
        command += ["--limit", str(options.limit)]
    if not options.full:
        command.append("--compact")
    command += list(options.query_words)

    timeout_seconds = (
        options.timeout_seconds if options.timeout_seconds is not None else 300
    )

    env = {**os.environ, "NO_COLOR": "1", "FORCE_COLOR": "0"}
    result = _run_command(command, env, timeout_seconds)

    if result.is_timeout:
        partial = strip_terminal_controls(result.stdout or result.stderr)
        timeout_payload: SearchFailurePayload = {
            "ok": False,
            "query": fallback_query,
            "provider": options.provider or "unknown",
            "answer": "",
            "sources": [],
            "truncated": False,
            "compact": not options.full,
            "parsed": False,
            "error": {
                "code": "timeout",
                "message": (
                    f"omp search exceeded timeout ({_format_seconds(timeout_seconds)}s)"
                ),
            },
            "exit_code": 124,
        }
        if options.include_raw:
            timeout_payload["raw"] = partial
        return timeout_payload

    parsed = parse_search_output(result.stdout, fallback_query)
    cleaned_stdout = parsed.cleaned_raw

    if result.exit_code == 0:
        provider = (
            parsed.provider
            if parsed.provider != "unknown"
            else options.provider or "unknown"
        )
        success_payload: SearchSuccessPayload = {
            "ok": True,
            "query": parsed.query or fallback_query,
            "provider": provider,
            "providers": [provider],
            "providers_count": 1,
            "answer": parsed.answer,
            "sources": list(parsed.sources),
            "sources_count": len(parsed.sources),
            "truncated": parsed.truncated,
            "compact": not options.full,
            "parsed": parsed.parsed,
            "exit_code": 0,
        }
        if options.include_raw:
            success_payload["raw"] = cleaned_stdout
        return success_payload

    message = failure_message(cleaned_stdout, result.stderr, result.exit_code)
    fail_provider = (
        parsed.provider
        if parsed.provider != "unknown"
        else options.provider or "unknown"
    )
    failure_payload: SearchFailurePayload = {
        "ok": False,
        "query": parsed.query or fallback_query,
        "provider": fail_provider,
        "providers": [fail_provider],
        "providers_count": 1,
        "answer": "",
        "sources": list(parsed.sources),
        "sources_count": len(parsed.sources),
        "truncated": False,
        "compact": not options.full,
        "parsed": parsed.parsed,
        "exit_code": result.exit_code,
        "error": {
            "code": "omp_search_failed",
            "message": message,
        },
    }
    if options.include_raw and cleaned_stdout:
        failure_payload["raw"] = cleaned_stdout
    if result.stderr.strip():
        failure_payload["diagnostics"] = redact(strip_terminal_controls(result.stderr))[
            -2000:
        ]
    return failure_payload
