# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Managed state planning, record tracking, and orphan cleanup."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import TypeAdapter, ValidationError

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from sync.core.plan import SyncPlan

from sync.core.harness import (
    HarnessSpec,
    SyncEnv,
    build_harness,
    harness_managed_state_path,
    harness_root,
)
from sync.core.harness_adapters import HARNESS_ADAPTERS
from sync.core.plan import build_sync_plan
from sync.runtime.errors import err, panic_message, warn
from sync.runtime.fs import is_ignored_sync_entry, rm_entry

__all__ = [
    "ManagedHarnessPlan",
    "ManagedSyncPlan",
    "clean_managed_entries",
    "is_safe_managed_entry_name",
    "load_recorded_entry_names",
    "plan_managed_entries",
    "plan_managed_entries_for_sync_plan",
    "record_managed_entries",
    "top_level_entry_names",
    "unique_sorted",
    "write_recorded_entry_names",
]


@dataclass(frozen=True, slots=True)
class ManagedHarnessPlan:
    """Managed entry plan for a single harness."""

    state_path: str
    cleanup_paths: list[str]
    current_entry_names: list[str]
    active: bool


@dataclass(frozen=True, slots=True)
class ManagedSyncPlan:
    """Full synchronization plan for managed entries across all harnesses."""

    harnesses: list[ManagedHarnessPlan]


def is_safe_managed_entry_name(entry_name: str) -> bool:
    """Check whether entry name is a safe top-level relative name."""
    return (
        len(entry_name) > 0
        and not Path(entry_name).is_absolute()
        and "/" not in entry_name
        and "\\" not in entry_name
        and entry_name not in {".", ".."}
    )


def top_level_entry_names(root: str | os.PathLike[str]) -> list[str]:
    """Return filtered entry names in a directory, ignoring internal sync paths."""
    try:
        entries = [
            entry.name
            for entry in os.scandir(root)
            if not is_ignored_sync_entry(entry.name)
        ]
    except OSError:
        return []
    else:
        return entries


def unique_sorted(names: Iterable[str]) -> list[str]:
    """Return unique strings sorted in ascending code-point order."""
    return sorted(set(names))


def _cleanup_path(root: str, entry_name: str) -> str | None:
    if not is_safe_managed_entry_name(entry_name):
        warn(f"skipping unsafe recorded managed entry name: {entry_name}")
        return None
    return str(Path(root) / entry_name)


def _parse_managed_entry_names(content: str) -> list[str]:
    parsed: object = json.loads(content)
    if not isinstance(parsed, list):
        message = "expected array of strings"
        raise TypeError(message)
    try:
        raw_entries = TypeAdapter(list[str]).validate_python(parsed)
    except ValidationError as error:
        message = "expected array of strings"
        raise ValueError(message) from error
    return unique_sorted(
        entry for entry in raw_entries if is_safe_managed_entry_name(entry)
    )


def load_recorded_entry_names(path: str | os.PathLike[str]) -> list[str]:
    """Load and validate recorded managed entry names from a state JSON file."""
    path_str = str(path)
    try:
        content = Path(path_str).read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except OSError as error:
        warn(f"ignoring malformed managed state {path_str} ({panic_message(error)})")
        return []

    try:
        return _parse_managed_entry_names(content)
    except (json.JSONDecodeError, ValueError, TypeError) as error:
        warn(f"ignoring malformed managed state {path_str} ({panic_message(error)})")
        return []


def write_recorded_entry_names(
    path: str | os.PathLike[str],
    entry_names: Sequence[str],
) -> None:
    """Write sorted unique managed entry names to JSON file atomically."""
    path_str = str(path)
    payload = f"{json.dumps(unique_sorted(entry_names), indent=2)}\n"
    target_path = Path(path_str)
    try:
        if (
            target_path.is_file()
            and not target_path.is_symlink()
            and target_path.read_text(encoding="utf-8") == payload
        ):
            return
    except OSError:
        pass

    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = Path(f"{path_str}.{os.getpid()}.tmp")
    try:
        temp_path.write_text(payload, encoding="utf-8")
        temp_path.replace(target_path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


def plan_managed_entries_for_sync_plan(
    sync_env: SyncEnv,
    sync_plan: SyncPlan,
) -> ManagedSyncPlan:
    """Compute cleanup and record plans for all active and inactive harnesses."""
    active_ids = {plan.harness.id for plan in sync_plan.harnesses}
    harnesses: list[ManagedHarnessPlan] = []
    for harness_plan in sync_plan.harnesses:
        current_entry_names = list(harness_plan.current_entry_names)
        current_entry_set = set(current_entry_names)
        stale_entry_names = [
            entry_name
            for entry_name in unique_sorted(
                [
                    *harness_plan.cleanup_entry_names,
                    *load_recorded_entry_names(harness_plan.state_path),
                ]
            )
            if entry_name not in current_entry_set
        ]
        cleanup_paths: list[str] = []
        for entry in stale_entry_names:
            resolved = _cleanup_path(harness_plan.root, entry)
            if resolved is not None:
                cleanup_paths.append(resolved)
        harnesses.append(
            ManagedHarnessPlan(
                state_path=harness_plan.state_path,
                cleanup_paths=cleanup_paths,
                current_entry_names=current_entry_names,
                active=True,
            )
        )

    for adapter in HARNESS_ADAPTERS:
        if sync_env.platform not in adapter.platforms:
            continue
        if adapter.id in active_ids:
            continue

        harness = build_harness(
            HarnessSpec(
                id=adapter.id,
                source_name=adapter.id,
                home=str(Path(sync_env.home).joinpath(*adapter.home_segments)),
                launcher=adapter.launcher,
                instruction_file=adapter.instruction_file,
                runtime_subdir=adapter.runtime_subdir,
                compat_managed_entries=adapter.compat_managed_entries,
                hooks=adapter.hooks,
            )
        )
        state_path = harness_managed_state_path(harness, sync_env.managed_state_home)
        if not Path(state_path).exists():
            continue

        root = harness_root(harness)
        recorded = load_recorded_entry_names(state_path)
        compat_entries = harness.compat_managed_entries or ()
        stale_entry_names = [
            entry_name
            for entry_name in unique_sorted([*compat_entries, *recorded])
            if is_safe_managed_entry_name(entry_name)
        ]
        harnesses.append(
            ManagedHarnessPlan(
                state_path=state_path,
                cleanup_paths=[
                    str(Path(root) / entry_name) for entry_name in stale_entry_names
                ],
                current_entry_names=[],
                active=False,
            )
        )

    return ManagedSyncPlan(harnesses=harnesses)


def plan_managed_entries(sync_env: SyncEnv) -> ManagedSyncPlan:
    """Build a sync plan and compute managed entry cleanup/record plan."""
    return plan_managed_entries_for_sync_plan(sync_env, build_sync_plan(sync_env))


def clean_managed_entries(plan: ManagedSyncPlan) -> bool:
    """Clean obsolete managed entry paths."""
    success = True
    for harness in plan.harnesses:
        for cleanup_path in harness.cleanup_paths:
            try:
                rm_entry(cleanup_path)
            except OSError as error:
                err(f"cleanup failed: {cleanup_path} ({panic_message(error)})")
                success = False
    return success


def record_managed_entries(plan: ManagedSyncPlan) -> bool:
    """Record managed state files or remove stale state files for inactive harnesses."""
    success = True
    for harness in plan.harnesses:
        if not harness.active:
            try:
                Path(harness.state_path).unlink(missing_ok=True)
            except OSError as error:
                err(
                    f"managed state removal failed: {harness.state_path} "
                    f"({panic_message(error)})"
                )
                success = False
            continue
        try:
            write_recorded_entry_names(harness.state_path, harness.current_entry_names)
        except (OSError, ValueError) as error:
            err(f"managed state write failed: {panic_message(error)}")
            success = False
    return success
