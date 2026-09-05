# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Extension dependency resolution and installation runner."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import TYPE_CHECKING

from sync.packages.process import install_inferred_import_packages
from sync.runtime.errors import assert_never, err
from sync.runtime.process import (
    CommandOutcome,
    Failure,
    MissingCommand,
    Success,
    TimedOut,
    command_exists,
    run_command_outcome,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    "install_extension_deps",
    "iter_extension_packages",
    "log_install_failure",
    "run_install",
]


def _walk_extension_packages_sync(root: str) -> list[str]:
    root_path = Path(root)
    if not root_path.is_dir():
        return []
    packages_found: list[str] = []
    try:
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            dirnames[:] = [d for d in dirnames if d != "node_modules"]
            if "package.json" in filenames:
                packages_found.append(dirpath)
    except OSError:
        return []
    return sorted(packages_found)


async def iter_extension_packages(root: str) -> list[str]:
    """Find all extension directories containing package.json excluding node_modules."""
    return await asyncio.to_thread(_walk_extension_packages_sync, root)


async def run_install(
    command: Sequence[str],
    package_dir: str,
    timeout_ms: int,
) -> bool:
    """Execute install command in package directory, logging failures."""
    outcome = await run_command_outcome(command, cwd=package_dir, timeout_ms=timeout_ms)
    if isinstance(outcome, Success):
        return True
    log_install_failure(command, package_dir, outcome)
    return False


async def _choose_installer() -> list[str] | None:
    return ["bun", "install"] if await command_exists("bun") else None


def _has_package_json(package_dir: Path) -> bool:
    return (package_dir / "package.json").is_file()


async def install_extension_deps(
    root: str,
    source_root: str,
    timeout_ms: int,
) -> bool:
    """Install dependencies for each extension and infer root imports."""
    command = await _choose_installer()
    if not command:
        err("bun is required for extension dependency install")
        return False

    results: list[bool] = []
    root_path = Path(root)
    source_root_path = Path(source_root)
    for source_package_dir in await iter_extension_packages(source_root):
        rel = Path(source_package_dir).relative_to(source_root_path)
        package_dir = root_path / rel
        has_pkg = await asyncio.to_thread(_has_package_json, package_dir)
        if not has_pkg:
            results.append(True)
            continue

        results.append(await run_install(command, str(package_dir), timeout_ms))

    results.append(
        await install_inferred_import_packages(root, timeout_ms, source_root)
    )
    return all(results)


def log_install_failure(
    command: Sequence[str],
    package_dir: str,
    outcome: CommandOutcome,
) -> None:
    """Log formatted error message describing failed extension install."""
    cmd_name = command[0] if command else ""
    match outcome:
        case Success():
            return
        case MissingCommand():
            err(f"missing installer: {cmd_name}")
        case Failure(detail=detail):
            err(f"deps install failed in {package_dir}: {cmd_name} ({detail})")
        case TimedOut():
            err(f"deps install timed out in {package_dir}: {cmd_name}")
        case _:
            assert_never(outcome)
