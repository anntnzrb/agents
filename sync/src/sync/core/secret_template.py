# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Secret template rendering and atomic file synchronization."""

from __future__ import annotations

import contextlib
import json
import os
import re
import stat
import time
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import TypeAdapter, ValidationError

if TYPE_CHECKING:
    from collections.abc import Mapping

from sync.runtime.errors import is_errno, panic_message

OUTPUT_MODE = 0o600
_PLACEHOLDER_PATTERN = re.compile(r"\$\{([^{}]+)\}")
_SECRET_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")
_TRAILING_COMMA_PATTERN = re.compile(r",(?=\s*[}\]])")
_MAX_TEMP_ATTEMPTS = 16


def _consume_line_comment(content: str, i: int, n: int, result: list[str]) -> int:
    while i < n:
        if content[i] == "\n":
            result.append("\n")
            return i + 1
        i += 1
    return i


def _consume_block_comment(content: str, i: int, n: int, result: list[str]) -> int:
    while i < n:
        if content[i] == "\n":
            result.append("\n")
            i += 1
        elif content[i : i + 2] == "*/":
            return i + 2
        else:
            i += 1
    return i


def _consume_string(content: str, i: int, n: int, result: list[str]) -> int:
    result.append('"')
    i += 1
    while i < n:
        ch = content[i]
        result.append(ch)
        if ch == "\\":
            i += 1
            if i < n:
                result.append(content[i])
                i += 1
            continue
        if ch == '"':
            return i + 1
        i += 1
    return i


def _strip_jsonc_comments(content: str) -> str:
    result: list[str] = []
    i = 0
    n = len(content)

    while i < n:
        ch = content[i]
        if ch == '"':
            i = _consume_string(content, i, n, result)
        elif content[i : i + 2] == "//":
            i = _consume_line_comment(content, i + 2, n, result)
        elif content[i : i + 2] == "/*":
            i = _consume_block_comment(content, i + 2, n, result)
        else:
            result.append(ch)
            i += 1

    return "".join(result)


def strip_jsonc(content: str) -> str:
    """Strip comments (// and /* */) and trailing commas from JSONC content."""
    cleaned = _strip_jsonc_comments(content)
    return _TRAILING_COMMA_PATTERN.sub("", cleaned)


def render_secret_template(
    template: str,
    secrets: Mapping[str, str],
) -> str:
    """Render secret template replacing ${NAME} with json.dumps(secret_value)."""

    def replace_match(match: re.Match[str]) -> str:
        raw_name = match.group(1)
        if not _SECRET_NAME_PATTERN.match(raw_name):
            message = f"invalid secret placeholder: {raw_name}"
            raise ValueError(message)
        value = secrets.get(raw_name)
        if not isinstance(value, str) or len(value) == 0:
            message = f"missing secret: {raw_name}"
            raise ValueError(message)
        return json.dumps(value)

    return _PLACEHOLDER_PATTERN.sub(replace_match, template)


def sync_secret_template(
    src: str | os.PathLike[str],
    dst: str | os.PathLike[str],
    secrets_path: str | os.PathLike[str],
) -> None:
    """Read template and secrets, render placeholders, and write private destination."""
    src_str = os.fspath(src)
    dst_str = os.fspath(dst)
    secrets_path_str = os.fspath(secrets_path)

    template = _read_text(src_str, "template")
    secrets = _read_secrets(secrets_path_str)
    content = render_secret_template(template, secrets)

    try:
        sync_private_text_file(dst_str, content)
    except Exception as error:
        message = (
            f"render secret template {src_str} -> {dst_str} ({panic_message(error)})"
        )
        raise RuntimeError(message) from error


def sync_private_text_file(
    dst: str | os.PathLike[str],
    content: str,
) -> None:
    """Write text file atomically with 0600 mode."""
    sync_text_file(dst, content, OUTPUT_MODE)


def sync_text_file(
    dst: str | os.PathLike[str],
    content: str,
    mode: int = OUTPUT_MODE,
) -> None:
    """Write text file atomically with mode, skipping if content and mode match."""
    dst_str = os.fspath(dst)
    if _matches_output(dst_str, content, mode):
        return

    parent_dir = Path(dst_str).parent
    parent_dir.mkdir(parents=True, exist_ok=True)

    fd, temp_path = _create_temp_file(dst_str, mode)
    closed = False
    try:
        content_bytes = content.encode("utf-8")
        os.write(fd, content_bytes)
        os.fchmod(fd, mode)
        os.fsync(fd)
        os.close(fd)
        closed = True
        Path(temp_path).replace(dst_str)
    except Exception:
        if not closed:
            with contextlib.suppress(OSError):
                os.close(fd)
        with contextlib.suppress(OSError):
            Path(temp_path).unlink()
        raise


def _read_text(path: str, label: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError as error:
        message = f"read {label} {path} ({panic_message(error)})"
        raise RuntimeError(message) from error


def _read_secrets(path: str) -> dict[str, str]:
    raw_text = _read_text(path, "secrets")
    try:
        parsed: object = json.loads(strip_jsonc(raw_text))
    except Exception as error:
        message = f"parse secrets {path} ({panic_message(error)})"
        raise RuntimeError(message) from error

    if not isinstance(parsed, dict):
        message = f"invalid secrets file: {path} (expected object)"
        raise TypeError(message)

    try:
        raw_dict = TypeAdapter(dict[str, object]).validate_python(parsed)
    except ValidationError as error:
        message = f"invalid secrets file: {path} (expected object)"
        raise TypeError(message) from error

    secrets: dict[str, str] = {}
    for key, value in raw_dict.items():
        if not _SECRET_NAME_PATTERN.match(key):
            message = f"invalid secret entry: {key}"
            raise ValueError(message)
        if not isinstance(value, str) or len(value) == 0:
            message = f"invalid secret entry for {key}: expected non-empty string"
            raise ValueError(message)
        secrets[key] = value
    return secrets


def _matches_output(path: str, content: str, mode: int) -> bool:
    try:
        metadata = os.lstat(path)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or (metadata.st_mode & 0o777) != mode
        ):
            return False
        return Path(path).read_text(encoding="utf-8") == content
    except OSError:
        return False


def _create_temp_file(path: str, mode: int) -> tuple[int, str]:
    now_ms = int(time.time() * 1000)
    nonce = format(now_ms, "x")
    pid = os.getpid()
    base_name = Path(path).name or "config"
    dir_name = Path(path).parent

    for attempt in range(_MAX_TEMP_ATTEMPTS):
        temp_path = str(dir_name / f".{base_name}.{pid}.{nonce}-{attempt}.tmp")
        try:
            fd = os.open(
                temp_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                mode,
            )
        except OSError as error:
            if not is_errno(error, "EEXIST"):
                raise
        else:
            return fd, temp_path
    message = f"create temporary config near {path} (name collision)"
    raise RuntimeError(message)
