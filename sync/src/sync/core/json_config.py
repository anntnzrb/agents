# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Deep merge of managed JSON configuration over local machine state."""

from __future__ import annotations

import json
import stat
from pathlib import Path
from typing import TypeGuard

from sync.runtime.fs import OUTPUT_MODE, sync_text_file
from sync.runtime.jsonc import strip_jsonc

__all__ = [
    "merge_json_objects",
    "sync_merged_json_config",
]


def _is_json_object(value: object) -> TypeGuard[dict[str, object]]:
    return isinstance(value, dict)


def merge_json_objects(base: object, overlay: object) -> object:
    """Recursively merge overlay over base; overlay scalars and arrays win."""
    if not _is_json_object(base) or not _is_json_object(overlay):
        return overlay
    merged: dict[str, object] = dict(base)
    for key, value in overlay.items():
        if key in merged:
            merged[key] = merge_json_objects(merged[key], value)
        else:
            merged[key] = value
    return merged


def _read_json_object(path: Path) -> dict[str, object] | None:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    parsed: object = json.loads(strip_jsonc(text))  # pyright: ignore[reportAny]
    if not _is_json_object(parsed):
        message = f"expected JSON object: {path}"
        raise ValueError(message)
    return parsed


def _existing_mode(path: Path) -> int:
    try:
        metadata = path.lstat()
    except OSError:
        return OUTPUT_MODE
    if stat.S_ISREG(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode):
        return metadata.st_mode & 0o777
    return OUTPUT_MODE


def sync_merged_json_config(src: str, dst: str) -> None:
    """Merge managed source JSON over destination JSON, preserving local keys."""
    src_path = Path(src)
    dst_path = Path(dst)
    overlay = _read_json_object(src_path)
    if overlay is None:
        message = f"missing source: {src}"
        raise RuntimeError(message)
    base = _read_json_object(dst_path) or {}
    merged = merge_json_objects(base, overlay)
    content = f"{json.dumps(merged, indent=2)}\n"
    sync_text_file(dst_path, content, _existing_mode(dst_path))
