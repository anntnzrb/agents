# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Subprocess execution for inferred extension dependency installation."""

from __future__ import annotations

import asyncio
from pathlib import Path

from sync.packages.validate import missing_package_roots
from sync.runtime.errors import err, panic_message
from sync.runtime.process import (
    Success,
    log_command_failure,
    resolve_executable,
    run_command_outcome,
)

__all__ = [
    "install_inferred_import_packages",
]

_EMPTY_PACKAGE_JSON: str = '{\n  "name": "pi-extension-deps",\n  "private": true\n}\n'


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

    tool = await resolve_executable("bun")
    if not tool:
        err(f"bun is required for inferred imports in {target_dir}")
        return False

    command = [tool, "add", "--no-save", *missing]
    outcome = await run_command_outcome(command, cwd=target_dir, timeout_ms=timeout_ms)
    if isinstance(outcome, Success):
        return True

    log_command_failure(command, "install inferred packages", outcome)
    return False


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
