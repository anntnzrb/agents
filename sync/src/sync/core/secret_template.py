# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Secret template rendering."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import TypeAdapter, ValidationError

if TYPE_CHECKING:
    from collections.abc import Mapping

from sync.runtime.errors import panic_message
from sync.runtime.fs import sync_private_text_file
from sync.runtime.jsonc import strip_jsonc

_PLACEHOLDER_PATTERN = re.compile(r"\$\{([^{}]+)\}")
_SECRET_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")


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
        return json.dumps(value, ensure_ascii=False)

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
    except (OSError, ValueError, RuntimeError) as error:
        message = (
            f"render secret template {src_str} -> {dst_str} ({panic_message(error)})"
        )
        raise RuntimeError(message) from error


def _read_text(path: str, label: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError as error:
        message = f"read {label} {path} ({panic_message(error)})"
        raise RuntimeError(message) from error


def _read_secrets(path: str) -> dict[str, str]:
    raw_text = _read_text(path, "secrets")
    cleaned = strip_jsonc(raw_text)
    try:
        parsed: object = json.loads(cleaned)  # pyright: ignore[reportAny]
    except (ValueError, TypeError) as error:
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
