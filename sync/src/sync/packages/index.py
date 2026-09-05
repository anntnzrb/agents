# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Package manifest decoding, bootstrap coordination, and runtime settings."""

from __future__ import annotations

import asyncio
import json
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from pydantic import BaseModel, ConfigDict, field_validator

from sync.packages.process import (
    install_inferred_import_packages as install_inferred_import_packages_impl,
)
from sync.packages.process import (
    install_package_deps,
    run_package_build,
)
from sync.packages.source import (
    clone_package,
    package_cache_dir,
    replace_dir_atomically,
    rm_entry,
    staging_dir_for,
)
from sync.packages.validate import (
    extract_import_specifiers,
    missing_package_roots,
    package_has_build_script,
    package_is_healthy,
)
from sync.runtime.errors import err, is_errno, panic_message
from sync.runtime.fs import sync_text_file
from sync.runtime.jsonc import strip_jsonc

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    "PackageBootstrapTarget",
    "PackageManifest",
    "bootstrap_package_target",
    "extract_import_specifiers",
    "missing_package_roots",
    "package_cache_dir",
    "package_has_build_script",
    "package_is_healthy",
    "patch_runtime_settings",
    "read_package_manifest",
]

_DEFAULT_FILE_MODE = 0o600


class PackageManifest(BaseModel):
    """Manifest describing package bootstrap sources."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    packages: list[str]

    @field_validator("packages", mode="before")
    @classmethod
    def _normalize_packages(cls, value: object) -> list[str]:
        if not isinstance(value, list):
            message = "packages must be a list"
            raise TypeError(message)
        raw_items = cast("list[object]", value)
        result: list[str] = []
        seen: set[str] = set()
        for item in raw_items:
            if not isinstance(item, str):
                message = "package source must be a string"
                raise TypeError(message)
            trimmed = item.strip()
            if not trimmed:
                message = "package source must not be empty"
                raise ValueError(message)
            if trimmed not in seen:
                seen.add(trimmed)
                result.append(trimmed)
        return result


@dataclass(frozen=True, slots=True)
class PackageBootstrapTarget:
    """Target paths and timeout configuration for package bootstrap."""

    manifest_path: str
    runtime_settings_path: str
    cache_root: str
    timeout_ms: int


def read_package_manifest(file_path: str) -> PackageManifest:
    """Read and validate package bootstrap manifest JSON/JSONC file."""
    try:
        content = Path(file_path).read_text(encoding="utf-8")
    except OSError as error:
        if is_errno(error, "ENOENT"):
            return PackageManifest(packages=[])
        message = f"{file_path} ({error})"
        raise ValueError(message) from error

    try:
        data = json.loads(strip_jsonc(content))
    except (ValueError, TypeError) as error:
        message = f"invalid JSON in {file_path}: {error}"
        raise ValueError(message) from error

    try:
        return PackageManifest.model_validate(data)
    except (ValueError, TypeError) as error:
        message = f"{file_path} ({panic_message(error)})"
        raise ValueError(message) from error


def patch_runtime_settings(file_path: str, package_paths: Sequence[str]) -> None:
    """Update packages array in settings.json preserving mode and other fields."""
    current = "{}"
    try:
        current = Path(file_path).read_text(encoding="utf-8")
    except OSError as error:
        if not is_errno(error, "ENOENT"):
            message = f"read {file_path} ({error})"
            raise ValueError(message) from error

    try:
        value = json.loads(strip_jsonc(current))
    except (ValueError, TypeError) as error:
        message = f"parse {file_path} ({error})"
        raise ValueError(message) from error

    raw_dict: dict[object, object] = (
        cast("dict[object, object]", value) if isinstance(value, dict) else {}
    )
    settings: dict[str, object] = {str(k): v for k, v in raw_dict.items()}
    settings["packages"] = list(package_paths)

    try:
        metadata = Path(file_path).lstat()
        mode = (
            metadata.st_mode & 0o777
            if stat.S_ISREG(metadata.st_mode)
            else _DEFAULT_FILE_MODE
        )
    except OSError as error:
        if not is_errno(error, "ENOENT"):
            message = f"lstat {file_path} ({error})"
            raise ValueError(message) from error
        mode = _DEFAULT_FILE_MODE

    formatted = f"{json.dumps(settings, indent=2)}\n"
    sync_text_file(file_path, formatted, mode)


def _prepare_staging(cache_root: str, staging_dir: str) -> None:
    Path(cache_root).mkdir(parents=True, exist_ok=True)
    rm_entry(staging_dir)
    Path(staging_dir).parent.mkdir(parents=True, exist_ok=True)


async def ensure_package(
    source: str,
    cache_root: str,
    timeout_ms: int,
) -> str:
    """Ensure a package is cloned, dependencies installed, built, and cached."""
    final_dir = package_cache_dir(cache_root, source)
    if package_is_healthy(final_dir):
        return final_dir

    staging_dir = staging_dir_for(final_dir)
    await asyncio.to_thread(_prepare_staging, cache_root, staging_dir)

    success = False
    try:
        if not await clone_package(source, staging_dir, timeout_ms):
            message = "clone failed"
            raise RuntimeError(message)
        if not await install_package_deps(staging_dir, timeout_ms):
            message = "dependency install failed"
            raise RuntimeError(message)

        healthy = package_is_healthy(staging_dir)
        if not healthy and package_has_build_script(staging_dir):
            if not await run_package_build(staging_dir, timeout_ms):
                message = "build failed"
                raise RuntimeError(message)
            if not await install_inferred_import_packages_impl(staging_dir, timeout_ms):
                message = "install inferred packages after build failed"
                raise RuntimeError(message)
            healthy = package_is_healthy(staging_dir)

        if not healthy:
            message = "package resources failed validation"
            raise RuntimeError(message)

        await replace_dir_atomically(staging_dir, final_dir)
        success = True
        return final_dir
    finally:
        if not success:
            rm_entry(staging_dir)


async def bootstrap_package_target(target: PackageBootstrapTarget) -> bool:
    """Bootstrap all packages declared in target manifest into cache and settings."""
    try:
        manifest = read_package_manifest(target.manifest_path)
    except (OSError, ValueError) as error:
        err(f"package bootstrap failed: {panic_message(error)}")
        return False

    installed_paths: list[str] = []
    success = True
    for source in manifest.packages:
        try:
            installed = await ensure_package(
                source, target.cache_root, target.timeout_ms
            )
            installed_paths.append(installed)
        except (OSError, ValueError, RuntimeError) as error:
            err(f"package bootstrap failed for {source}: {panic_message(error)}")
            success = False

    if success:
        try:
            patch_runtime_settings(target.runtime_settings_path, installed_paths)
        except (OSError, ValueError) as error:
            err(f"package settings patch failed: {panic_message(error)}")
            success = False

    return success
