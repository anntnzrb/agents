# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Package source resolution, FNV-1a64 hashing, atomic operations, and Git cloning."""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING

from sync.runtime.fs import rm_entry
from sync.runtime.process import command_exists, run_command

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

__all__ = [
    "clone_package",
    "clone_package_with_runner",
    "fnv1a64",
    "package_cache_dir",
    "replace_dir_atomically",
    "rm_entry",
    "source_slug",
    "staging_dir_for",
]

_ALPHANUMERIC_PATTERN = re.compile(r"[A-Za-z0-9]")
_SOURCE_SEPARATOR_PATTERN = re.compile(r"[/:]")
_TRAILING_PATH_SEPARATOR_PATTERN = re.compile(r"/+$")
_FNV_OFFSET_BASIS = 0xCBF29CE484222325
_FNV_PRIME = 0x100000001B3
_MASK_64 = 0xFFFFFFFFFFFFFFFF
_OWNER_REPO_PARTS_COUNT = 2


def package_cache_dir(cache_root: str, source: str) -> str:
    """Compute local cache directory path for a given package source."""
    slug = source_slug(source)
    return str(Path(cache_root) / f"{slug}-{fnv1a64(source)}")


def staging_dir_for(final_dir: str) -> str:
    """Generate a unique staging directory path for atomic package installation."""
    now = time.time_ns()
    return _with_extension(final_dir, f"staging-{os.getpid()}-{now}")


def _replace_dir_atomically_sync(src: str, dst: str) -> None:
    now = time.time_ns()
    backup = _with_extension(dst, f"backup-{os.getpid()}-{now}")
    legacy_backup = _with_extension(dst, "backup")

    if _exists(legacy_backup):
        rm_entry(legacy_backup)
    rm_entry(backup)

    moved_to_backup = False
    if _exists(dst):
        Path(dst).replace(backup)
        moved_to_backup = True

    try:
        Path(src).replace(dst)
        if moved_to_backup:
            rm_entry(backup)
    except Exception:
        if moved_to_backup and _exists(backup):
            with contextlib.suppress(OSError):
                Path(backup).replace(dst)
        raise


async def replace_dir_atomically(src: str, dst: str) -> None:
    """Atomically replace dst with src directory, rolling back on failure."""
    await asyncio.to_thread(_replace_dir_atomically_sync, src, dst)


async def clone_package(
    source: str,
    target_dir: str,
    timeout_ms: int,
) -> bool:
    """Clone git repository package into target directory using gh or git."""
    gh_available = await command_exists("gh")

    async def runner(command: Sequence[str]) -> bool:
        return await run_command(
            command, cwd=None, timeout_ms=timeout_ms, action="clone"
        )

    return await clone_package_with_runner(
        source, target_dir, gh_available=gh_available, runner=runner
    )


def source_slug(source: str) -> str:
    """Generate a clean alphanumeric slug from a package source URL or path."""
    trimmed = _TRAILING_PATH_SEPARATOR_PATTERN.sub("", source.strip())
    normalized = trimmed.removesuffix(".git")
    if _is_local_path_source(normalized):
        source_parts = [_local_path_basename(normalized)]
    else:
        parts = [p for p in _SOURCE_SEPARATOR_PATTERN.split(normalized) if p]
        source_parts = parts[-2:]

    joined = "-".join(source_parts) if source_parts else "package"
    sanitized = "".join(
        ch.lower() if _ALPHANUMERIC_PATTERN.match(ch) else "-" for ch in joined
    )
    compact = "-".join(part for part in sanitized.split("-") if part)
    return compact or "package"


def fnv1a64(input_str: str) -> str:
    """Compute 64-bit FNV-1a hash formatted as 16 lowercase hex digits."""
    hash_val = _FNV_OFFSET_BASIS
    for byte in input_str.encode("utf-8"):
        hash_val ^= byte
        hash_val = (hash_val * _FNV_PRIME) & _MASK_64
    return f"{hash_val:016x}"


def _local_path_basename(source: str) -> str:
    return Path(source).name


def _is_local_path_source(source: str) -> bool:
    return Path(source).is_absolute()


def _with_extension(target: str, extension: str) -> str:
    target_path = Path(target)
    return str(target_path.parent / f"{target_path.stem}.{extension}")


async def clone_package_with_runner(
    source: str,
    target_dir: str,
    *,
    gh_available: bool,
    runner: Callable[[Sequence[str]], Awaitable[bool]],
) -> bool:
    """Attempt clone commands sequentially, removing target on failure/retry."""
    commands = _clone_commands(source, target_dir, gh_available=gh_available)
    for index, command in enumerate(commands):
        if index > 0:
            rm_entry(target_dir)
        if await runner(command):
            return True
        rm_entry(target_dir)
    return False


def _clone_commands(
    source: str,
    target_dir: str,
    *,
    gh_available: bool,
) -> list[list[str]]:
    commands: list[list[str]] = []
    slug = _github_repo_slug(source)
    if slug and gh_available:
        commands.append(["gh", "repo", "clone", slug, target_dir, "--", "--depth=1"])
    commands.append(["git", "clone", "--depth=1", source, target_dir])
    return commands


def _github_repo_slug(source: str) -> str | None:
    trimmed = source.strip()
    normalized = trimmed.removesuffix(".git")
    if normalized.startswith("https://github.com/"):
        return _split_owner_repo(normalized.removeprefix("https://github.com/"))
    if normalized.startswith("http://github.com/"):
        return _split_owner_repo(normalized.removeprefix("http://github.com/"))
    if normalized.startswith("git@github.com:"):
        return _split_owner_repo(normalized.removeprefix("git@github.com:"))
    return None


def _split_owner_repo(rest: str) -> str | None:
    parts = [part for part in rest.split("/") if part][:_OWNER_REPO_PARTS_COUNT]
    if len(parts) != _OWNER_REPO_PARTS_COUNT:
        return None
    return f"{parts[0]}/{parts[1]}"


def _exists(target: str) -> bool:
    try:
        return Path(target).exists()
    except OSError:
        return False
