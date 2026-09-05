# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Subprocess execution for package dependency installation and builds."""

from __future__ import annotations

import asyncio
from pathlib import Path

from sync.packages.validate import missing_package_roots
from sync.runtime.errors import err, panic_message
from sync.runtime.process import (
    Success,
    log_command_failure,
    resolve_executable,
    run_command,
    run_command_outcome,
)

__all__ = [
    "install_inferred_import_packages",
    "install_package_deps",
    "pick_bun_runner",
    "run_command",
    "run_package_build",
]

_EMPTY_PACKAGE_JSON: str = '{\n  "name": "pi-extension-deps",\n  "private": true\n}\n'


async def pick_bun_runner() -> str | None:
    """Resolve path to bun binary on system PATH or local environment."""
    return await resolve_executable("bun")


def _has_package_json(target_dir: str) -> bool:
    return (Path(target_dir) / "package.json").is_file()


async def install_package_deps(target_dir: str, timeout_ms: int) -> bool:
    """Install package dependencies via bun install or inferred imports."""
    if not await asyncio.to_thread(_has_package_json, target_dir):
        return await install_inferred_import_packages(target_dir, timeout_ms)

    tool = await pick_bun_runner()
    if not tool:
        err(f"bun is required for dependency install in {target_dir}")
        return False

    install_command = [tool, "install"]
    if not await run_command(
        install_command, cwd=target_dir, timeout_ms=timeout_ms, action="install"
    ):
        return False
    return await install_inferred_import_packages(target_dir, timeout_ms)


async def install_inferred_import_packages(
    target_dir: str,
    timeout_ms: int,
    source_dir: str | None = None,
) -> bool:
    """Detect uninstalled imports and install them using bun add --no-save."""
    effective_source_dir = target_dir if source_dir is None else source_dir
    try:
        missing = missing_package_roots(effective_source_dir)
    except (OSError, ValueError) as error:
        err(f"dependency scan failed in {target_dir}: {panic_message(error)}")
        return False

    if not missing:
        return True

    if not await _ensure_install_project(target_dir):
        return False

    tool = await pick_bun_runner()
    if not tool:
        err(f"bun is required for inferred imports in {target_dir}")
        return False

    command = [tool, "add", "--no-save", *missing]
    outcome = await run_command_outcome(command, cwd=target_dir, timeout_ms=timeout_ms)
    if isinstance(outcome, Success):
        return True

    log_command_failure(command, "install inferred packages", outcome)
    return False


async def run_package_build(target_dir: str, timeout_ms: int) -> bool:
    """Execute bun run build in the specified package directory."""
    tool = await pick_bun_runner()
    if not tool:
        err(f"bun is required for build in {target_dir}")
        return False

    return await run_command(
        [tool, "run", "build"], cwd=target_dir, timeout_ms=timeout_ms, action="build"
    )


def _write_empty_package_json(target_dir: str) -> bool:
    package_json_path = Path(target_dir) / "package.json"
    if package_json_path.exists():
        return True

    try:
        _ = package_json_path.write_text(_EMPTY_PACKAGE_JSON, encoding="utf-8")
    except OSError as error:
        err(f"write {target_dir}/package.json ({panic_message(error)})")
        return False
    else:
        return True


async def _ensure_install_project(target_dir: str) -> bool:
    return await asyncio.to_thread(_write_empty_package_json, target_dir)
