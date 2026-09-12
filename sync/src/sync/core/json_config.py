# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Managed JSON configuration copy preserving declared destination keys."""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Sequence

from sync.runtime.fs import (
    existing_file_mode,
    is_identical_file,
    rm_entry,
    sync_text_file,
)
from sync.runtime.jsonc import is_obj_dict, strip_jsonc

__all__ = [
    "sync_json_config",
]

_MISSING: Final = object()


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


def _get_path(root: dict[str, object], path: str) -> object:
    """Return the value at a dot-separated path, or _MISSING when undefined."""
    node: object = root
    for segment in path.split("."):
        if not is_obj_dict(node) or segment not in node:
            return _MISSING
        node = node[segment]
    return node


def _inject_preserved(
    result: dict[str, object],
    source: dict[str, object],
    previous: dict[str, object],
    path: str,
) -> None:
    """Re-inject a declared path's destination value when the source omits it."""
    if _get_path(source, path) is not _MISSING:
        return
    value = _get_path(previous, path)
    if value is _MISSING:
        return
    node = result
    segments = path.split(".")
    for segment in segments[:-1]:
        if segment not in node:
            node[segment] = {}
        child = node[segment]
        if not is_obj_dict(child):
            return
        node = child
    node[segments[-1]] = value


def _copy_file_verbatim(src: Path, dst: Path) -> None:
    try:
        src_stat = src.stat()
    except OSError:
        src_stat = None
    if src_stat is not None and is_identical_file(src, src_stat, dst):
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    rm_entry(dst)
    _ = shutil.copy2(src, dst)


def sync_json_config(src: str, dst: str, preserve_paths: Sequence[str] = ()) -> None:
    """Copy managed JSON config, re-injecting declared destination-only keys."""
    src_path = Path(src)
    dst_path = Path(dst)
    source = _read_json_object(src_path)
    if source is None:
        message = f"missing source: {src}"
        raise RuntimeError(message)
    previous = _read_json_object(dst_path) or {}
    result = copy.deepcopy(source)
    for path in preserve_paths:
        _inject_preserved(result, source, previous, path)
    if result == source:
        _copy_file_verbatim(src_path, dst_path)
        return
    content = f"{json.dumps(result, indent=2)}\n"
    sync_text_file(dst_path, content, existing_file_mode(dst_path))
