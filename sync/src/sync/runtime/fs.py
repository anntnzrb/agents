# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Filesystem primitives for sync runtime."""

from __future__ import annotations

import contextlib
import os
import shutil
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import NoReturn

from sync.runtime.errors import is_errno

IGNORED_SYNC_NAMES: frozenset[str] = frozenset(
    {
        ".venv",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".hypothesis",
        ".DS_Store",
        ".git",
    }
)
OUTPUT_MODE = 0o600
_MAX_TEMP_ATTEMPTS = 16


def is_safe_managed_entry_name(entry_name: str) -> bool:
    """Check whether entry name is a safe top-level relative name."""
    return (
        len(entry_name) > 0
        and not Path(entry_name).is_absolute()
        and "/" not in entry_name
        and "\\" not in entry_name
        and entry_name not in {".", ".."}
    )


@dataclass(frozen=True, slots=True)
class CachedSourceContent:
    """Cached file metadata and raw content."""

    metadata: os.stat_result
    content: bytes


SourceContentCache = dict[str, CachedSourceContent]


def is_ignored_sync_entry(name: str) -> bool:
    """Return True if entry name should be excluded from sync operations."""
    return name in IGNORED_SYNC_NAMES or name.endswith((".pyc", ".pyo"))


def is_symlink(target_path: str | os.PathLike[str]) -> bool:
    """Return True if path is a symlink, False if non-symlink or ENOENT."""
    try:
        return stat.S_ISLNK(os.lstat(os.fspath(target_path)).st_mode)
    except OSError as error:
        if is_errno(error, "ENOENT"):
            return False
        raise


def _resolve_source_entry(src: str) -> os.stat_result:
    metadata = os.lstat(src)
    if stat.S_ISLNK(metadata.st_mode):
        target_metadata = Path(src).stat()
        if stat.S_ISDIR(target_metadata.st_mode):
            message = f"refusing source directory symlink: {src}"
            raise RuntimeError(message)
        return target_metadata
    return metadata


def rm_entry(target_path: str | os.PathLike[str]) -> None:
    """Remove a file, symlink, or directory tree if it exists."""
    path_str = os.fspath(target_path)
    try:
        metadata = os.lstat(path_str)
    except OSError as error:
        if is_errno(error, "ENOENT"):
            return
        raise

    if stat.S_ISDIR(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode):
        try:
            shutil.rmtree(path_str)
        except OSError as error:
            if not is_errno(error, "ENOENT"):
                raise
        return

    try:
        Path(path_str).unlink()
    except OSError as error:
        if not is_errno(error, "ENOENT"):
            raise


def copy_tree(
    src: str | os.PathLike[str],
    dst: str | os.PathLike[str],
) -> None:
    """Recursively copy directory or file from src to dst, ignoring artifacts."""
    src_str = os.fspath(src)
    dst_str = os.fspath(dst)
    metadata = _resolve_source_entry(src_str)
    if stat.S_ISDIR(metadata.st_mode):
        _copy_tree_recursive(src_str, dst_str)
        return
    Path(dst_str).parent.mkdir(parents=True, exist_ok=True)
    _ = shutil.copy2(src_str, dst_str)


def _copy_tree_recursive(src: str, dst: str) -> None:
    Path(dst).mkdir(parents=True, exist_ok=True)
    with os.scandir(src) as entries:
        for entry in entries:
            if is_ignored_sync_entry(entry.name):
                continue
            child_src = str(Path(src) / entry.name)
            child_dst = str(Path(dst) / entry.name)
            child_metadata = _resolve_source_entry(child_src)
            if stat.S_ISDIR(child_metadata.st_mode):
                _copy_tree_recursive(child_src, child_dst)
            else:
                Path(child_dst).parent.mkdir(parents=True, exist_ok=True)
                _ = shutil.copy2(child_src, child_dst)


def _get_dst_metadata(dst_str: str) -> os.stat_result | None:
    try:
        dst_lstat = os.lstat(dst_str)
        if stat.S_ISLNK(dst_lstat.st_mode):
            return None
        return Path(dst_str).stat()
    except OSError:
        return None


def _read_cached_source_content(
    src_str: str,
    src_metadata: os.stat_result,
    source_content_cache: SourceContentCache | None,
) -> bytes:
    cached = (
        source_content_cache.get(src_str) if source_content_cache is not None else None
    )
    if (
        cached is not None
        and cached.metadata.st_size == src_metadata.st_size
        and cached.metadata.st_mode == src_metadata.st_mode
        and cached.metadata.st_mtime_ns == src_metadata.st_mtime_ns
        and cached.metadata.st_ctime_ns == src_metadata.st_ctime_ns
    ):
        return cached.content
    content = Path(src_str).read_bytes()
    if source_content_cache is not None:
        source_content_cache[src_str] = CachedSourceContent(
            metadata=src_metadata,
            content=content,
        )
    return content


def is_identical_file(
    src: str | os.PathLike[str],
    src_metadata: os.stat_result,
    dst: str | os.PathLike[str],
    source_content_cache: SourceContentCache | None = None,
) -> bool:
    """Check if dst is an existing regular non-symlink file with matching content."""
    src_str = os.fspath(src)
    dst_str = os.fspath(dst)
    if stat.S_ISDIR(src_metadata.st_mode):
        return False

    dst_metadata = _get_dst_metadata(dst_str)
    if dst_metadata is None or not stat.S_ISREG(dst_metadata.st_mode):
        return False
    if src_metadata.st_size != dst_metadata.st_size:
        return False
    if (src_metadata.st_mode & 0o777) != (dst_metadata.st_mode & 0o777):
        return False
    if src_metadata.st_size == 0:
        return True

    src_content = _read_cached_source_content(
        src_str, src_metadata, source_content_cache
    )
    dst_content = Path(dst_str).read_bytes()
    return src_content == dst_content


def _sync_managed_file(
    src: str,
    dst: str,
    src_metadata: os.stat_result,
    source_content_cache: SourceContentCache | None = None,
) -> None:
    if is_identical_file(src, src_metadata, dst, source_content_cache):
        return

    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    rm_entry(dst)
    _ = shutil.copy2(src, dst)


def _ensure_directory(dst: str) -> None:
    try:
        metadata = os.lstat(dst)
        if stat.S_ISDIR(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode):
            return
        rm_entry(dst)
    except OSError as error:
        if not is_errno(error, "ENOENT"):
            raise
    Path(dst).mkdir(parents=True, exist_ok=True)


def _safe_scandir(target_path: str) -> list[os.DirEntry[str]]:
    try:
        with os.scandir(target_path) as it:
            return list(it)
    except OSError as error:
        if is_errno(error, "ENOENT"):
            return []
        raise


def _child_preserve(
    preserve_paths: Sequence[str],
    child_name: str,
) -> list[str]:
    prefix = f"{child_name}/"
    return [
        candidate.removeprefix(prefix)
        for candidate in preserve_paths
        if candidate.startswith(prefix)
    ]


def _preserves_entry(paths: Sequence[str], name: str) -> bool:
    prefix = f"{name}/"
    return any(entry == name or entry.startswith(prefix) for entry in paths)


def _normalize_preserve_paths(preserve_paths: Sequence[str]) -> list[str]:
    return sorted({candidate for candidate in preserve_paths if candidate})


def _prune_managed_tree(dst: str, preserve_paths: Sequence[str]) -> None:
    for dst_entry in _safe_scandir(dst):
        if dst_entry.name in preserve_paths:
            continue
        child_dst = str(Path(dst) / dst_entry.name)
        if (
            _preserves_entry(preserve_paths, dst_entry.name)
            and dst_entry.is_dir(follow_symlinks=False)
            and not dst_entry.is_symlink()
        ):
            _prune_managed_tree(
                child_dst,
                _child_preserve(preserve_paths, dst_entry.name),
            )
            continue
        rm_entry(child_dst)


def _sync_managed_tree_recursive(
    src: str,
    dst: str,
    preserve_paths: Sequence[str],
    source_content_cache: SourceContentCache | None = None,
) -> None:
    metadata = _resolve_source_entry(src)
    if not stat.S_ISDIR(metadata.st_mode):
        _sync_managed_file(src, dst, metadata, source_content_cache)
        return

    _ensure_directory(dst)

    with os.scandir(src) as it:
        src_entries = [entry for entry in it if not is_ignored_sync_entry(entry.name)]
    src_names = {entry.name for entry in src_entries}

    for dst_entry in _safe_scandir(dst):
        if dst_entry.name in src_names:
            continue
        if dst_entry.name in preserve_paths:
            continue
        child_dst = str(Path(dst) / dst_entry.name)
        if (
            _preserves_entry(preserve_paths, dst_entry.name)
            and dst_entry.is_dir(follow_symlinks=False)
            and not dst_entry.is_symlink()
        ):
            _prune_managed_tree(
                child_dst,
                _child_preserve(preserve_paths, dst_entry.name),
            )
            continue
        rm_entry(child_dst)

    for src_entry in src_entries:
        if src_entry.name in preserve_paths:
            continue
        child_src = str(Path(src) / src_entry.name)
        child_dst = str(Path(dst) / src_entry.name)
        child_preserve_paths = _child_preserve(preserve_paths, src_entry.name)
        child_metadata = _resolve_source_entry(child_src)
        if stat.S_ISDIR(child_metadata.st_mode):
            _sync_managed_tree_recursive(
                child_src,
                child_dst,
                child_preserve_paths,
                source_content_cache,
            )
            continue
        _sync_managed_file(
            child_src,
            child_dst,
            child_metadata,
            source_content_cache,
        )


def _sync_managed_children_recursive(
    src: str,
    dst: str,
    preserve_paths: Sequence[str],
    source_content_cache: SourceContentCache | None = None,
) -> None:
    metadata = _resolve_source_entry(src)
    if not stat.S_ISDIR(metadata.st_mode):
        _sync_managed_file(src, dst, metadata, source_content_cache)
        return

    with os.scandir(src) as it:
        src_entries = list(it)

    for src_entry in src_entries:
        if is_ignored_sync_entry(src_entry.name) or src_entry.name in preserve_paths:
            continue
        child_src = str(Path(src) / src_entry.name)
        child_dst = str(Path(dst) / src_entry.name)
        child_preserve_paths = _child_preserve(preserve_paths, src_entry.name)
        child_metadata = _resolve_source_entry(child_src)
        if stat.S_ISDIR(child_metadata.st_mode):
            _sync_managed_tree_recursive(
                child_src,
                child_dst,
                child_preserve_paths,
                source_content_cache,
            )
            continue
        _sync_managed_file(
            child_src,
            child_dst,
            child_metadata,
            source_content_cache,
        )


def sync_managed_tree(
    src: str | os.PathLike[str],
    dst: str | os.PathLike[str],
    preserve_paths: Sequence[str] = (),
    source_content_cache: SourceContentCache | None = None,
) -> None:
    """Synchronize source tree to destination, pruning unmanaged files."""
    src_str = os.fspath(src)
    dst_str = os.fspath(dst)
    metadata = _resolve_source_entry(src_str)
    if not stat.S_ISDIR(metadata.st_mode):
        _sync_managed_file(src_str, dst_str, metadata, source_content_cache)
        return
    _sync_managed_tree_recursive(
        src_str,
        dst_str,
        _normalize_preserve_paths(preserve_paths),
        source_content_cache,
    )


def sync_managed_children(
    src: str | os.PathLike[str],
    dst: str | os.PathLike[str],
    preserve_paths: Sequence[str] = (),
    source_content_cache: SourceContentCache | None = None,
) -> None:
    """Synchronize only direct children of source tree to destination."""
    src_str = os.fspath(src)
    dst_str = os.fspath(dst)
    metadata = _resolve_source_entry(src_str)
    if not stat.S_ISDIR(metadata.st_mode):
        _sync_managed_file(src_str, dst_str, metadata, source_content_cache)
        return
    _sync_managed_children_recursive(
        src_str,
        dst_str,
        _normalize_preserve_paths(preserve_paths),
        source_content_cache,
    )


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
    except (OSError, UnicodeDecodeError):
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


def _raise_zero_write(temp_path: str) -> NoReturn:
    """Raise for a zero-byte os.write during atomic file sync."""
    message = f"write {temp_path} (zero bytes written)"
    raise OSError(message)


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
        view = memoryview(content_bytes)
        total_written = 0
        total_bytes = len(content_bytes)
        while total_written < total_bytes:
            written = os.write(fd, view[total_written:])
            if written == 0:
                _raise_zero_write(temp_path)
            total_written += written
        os.fchmod(fd, mode)
        os.fsync(fd)
        os.close(fd)
        closed = True
        _ = Path(temp_path).replace(dst_str)
    except Exception:
        if not closed:
            with contextlib.suppress(OSError):
                os.close(fd)
        with contextlib.suppress(OSError):
            Path(temp_path).unlink()
        raise


def sync_private_text_file(
    dst: str | os.PathLike[str],
    content: str,
) -> None:
    """Write text file atomically with 0600 mode."""
    sync_text_file(dst, content, OUTPUT_MODE)
