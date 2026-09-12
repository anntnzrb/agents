# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Deep merge of managed JSON configuration over local machine state."""

from __future__ import annotations

import json
from pathlib import Path

from sync.runtime.fs import existing_file_mode, sync_text_file
from sync.runtime.jsonc import is_obj_dict, strip_jsonc

__all__ = [
    "merge_json_objects",
    "sync_merged_json_config",
]


def merge_json_objects(base: object, overlay: object) -> object:
    """Recursively merge overlay over base; overlay scalars and arrays win."""
    if not is_obj_dict(base) or not is_obj_dict(overlay):
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
    if not is_obj_dict(parsed):
        message = f"expected JSON object: {path}"
        raise ValueError(message)
    return parsed


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
    sync_text_file(dst_path, content, existing_file_mode(dst_path))
