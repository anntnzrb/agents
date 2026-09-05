# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Sync engine orchestrator: environment bootstrap, reconciliation, and launch."""

from __future__ import annotations

import asyncio
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

from sync.core.harness import Harness, SyncEnv, supported_harness
from sync.core.hook_state import (
    PreparedExtensionHookState,
    clear_extension_hook_state,
    prepare_extension_hook_state,
    record_extension_hook_state,
)
from sync.core.jobs import (
    prune_unreferenced_releases,
    remove_legacy_runtime_install,
    run_jobs_with_preserve,
)
from sync.core.launcher import (
    NpmPackageSpec,
    launch_harness,
    launch_npm_package,
)
from sync.core.managed_state import (
    clean_managed_entries,
    plan_managed_entries_for_sync_plan,
    record_managed_entries,
)
from sync.core.managed_tools import (
    PreparedManagedTool,
    is_cli_proxy_running,
    prepare_managed_tools,
)
from sync.core.plan import (
    ExtensionDepsHookPlan,
    SyncHookPlan,
    build_sync_plan,
)
from sync.core.tool_launchers import ToolLauncherSpec, tool_launcher
from sync.core.wrappers import (
    WrapperRuntime,
    managed_tool_wrapper_destination,
    reconcile_wrappers,
)
from sync.extensions.install import install_extension_deps
from sync.packages.index import (
    PackageBootstrapTarget,
    bootstrap_package_target,
)
from sync.runtime.errors import assert_never, err, panic_message, warn
from sync.runtime.fs import copy_tree, is_symlink, rm_entry
from sync.runtime.lock import (
    SyncLock,
    release_sync_lock,
)
from sync.runtime.lock import (
    try_acquire_sync_lock as try_acquire_sync_lock_impl,
)
from sync.runtime.process import (
    RunProcessOptions,
    command_exists,
    run_process,
)

__all__ = [
    "DEFAULT_SYNC_TIMEOUT_SECONDS",
    "SYNC_LOCK_FILE",
    "ExtensionHookRuntimeState",
    "SyncLock",
    "copy_tree",
    "ensure_python_env",
    "err",
    "is_symlink",
    "launch_main",
    "main",
    "panic_message",
    "parse_timeout_seconds",
    "rm_entry",
    "run_sync",
    "start_sync_watchdog",
    "sync_lock_path",
    "sync_timeout",
    "try_acquire_sync_lock",
    "warn",
]

DEFAULT_SYNC_TIMEOUT_SECONDS: int = 15 * 60
SYNC_LOCK_FILE: str = "sync.lock"
EXIT_OK: int = 0
EXIT_ERROR: int = 1
EXIT_UNSUPPORTED: int = 2
EXIT_TIMED_OUT: int = 124


@dataclass(frozen=True, slots=True)
class ExtensionHookRuntimeState:
    """Runtime tracking state for an extension dependencies hook."""

    hook: ExtensionDepsHookPlan
    state: PreparedExtensionHookState


async def ensure_python_env(home: str, timeout_ms: int) -> None:
    """Ensure ~/.omp/python-env exists, installing uv/python if required."""
    venv_python = Path(home) / ".omp" / "python-env" / "bin" / "python"
    if await asyncio.to_thread(venv_python.exists):
        return

    if not await command_exists("uv"):
        warn("uv not found; skipping python-env bootstrap.")
        return

    install = await run_process(
        ["uv", "python", "install"],
        RunProcessOptions(timeout_ms=timeout_ms),
    )
    if install.timed_out or install.exit_code != 0:
        warn("uv python install failed; skipping.")
        return

    find = await run_process(
        ["uv", "python", "find"],
        RunProcessOptions(timeout_ms=timeout_ms, stdio="pipe"),
    )
    latest = find.stdout.strip()
    if not latest:
        warn("uv python find returned empty; skipping.")
        return

    venv_target = str(Path(home) / ".omp" / "python-env")
    venv = await run_process(
        ["uv", "venv", "--python", latest, venv_target],
        RunProcessOptions(timeout_ms=timeout_ms),
    )
    if venv.timed_out or venv.exit_code != 0:
        warn("failed to create python-env")


def parse_timeout_seconds(value: str | None, default_seconds: int) -> int:
    """Parse a timeout string in seconds, falling back to default if invalid."""
    if value is None:
        return default_seconds
    try:
        parsed = int(value)
    except ValueError:
        return default_seconds
    else:
        return parsed if parsed > 0 else default_seconds


def sync_timeout() -> int:
    """Return the default sync execution timeout in seconds."""
    return DEFAULT_SYNC_TIMEOUT_SECONDS


def sync_lock_path(sync_env: SyncEnv) -> str:
    """Return the absolute path to the sync lockfile."""
    return str(Path(sync_env.managed_state_home) / SYNC_LOCK_FILE)


def try_acquire_sync_lock(sync_env: SyncEnv) -> SyncLock | None:
    """Attempt to acquire the global sync lock for the environment."""
    return try_acquire_sync_lock_impl(
        sync_env.managed_state_home, sync_lock_path(sync_env)
    )


def start_sync_watchdog(timeout_seconds: int) -> Callable[[], None]:
    """Start a watchdog timer that aborts the process on timeout."""

    def on_timeout() -> None:
        err(f"timed out after {timeout_seconds}s")
        os._exit(EXIT_TIMED_OUT)

    timer = threading.Timer(float(timeout_seconds), on_timeout)
    timer.daemon = True
    timer.start()

    def cancel() -> None:
        timer.cancel()

    return cancel


async def run_sync(
    sync_env: SyncEnv,
    *,
    warn_managed_services: bool = False,
) -> bool:
    """Execute complete synchronization lifecycle in the strict plan order."""
    await ensure_python_env(sync_env.home, sync_env.install_timeout_ms)

    try:
        sync_plan = build_sync_plan(sync_env)
        managed_plan = plan_managed_entries_for_sync_plan(sync_env, sync_plan)
        extension_hook_states = prepare_extension_hook_states(sync_plan.hooks)
    except (OSError, RuntimeError, ValueError, TypeError) as error:
        err(panic_message(error))
        return False

    cleanup_success = clean_managed_entries(managed_plan)
    base_success = False
    if cleanup_success:
        try:
            base_success = run_jobs_with_preserve(
                sync_plan.jobs,
                preserve_paths_by_dst(extension_hook_states),
            )
        except (OSError, RuntimeError, ValueError, TypeError) as error:
            err(panic_message(error))

    managed_tools: list[PreparedManagedTool] = []
    managed_tool_success = base_success
    if base_success and sync_plan.gateway_host:
        try:
            managed_tools = list(prepare_managed_tools(sync_env))
        except (OSError, RuntimeError, ValueError, TypeError) as error:
            err(panic_message(error))
            managed_tool_success = False

    wrapper_success = (
        reconcile_wrappers(
            sync_env,
            WrapperRuntime(
                additional_destinations=tuple(
                    managed_tool_wrapper_destination(sync_env, tool)
                    for tool in managed_tools
                )
            ),
        )
        if managed_tool_success
        else False
    )

    legacy_cleanup_success = (
        remove_legacy_runtime_install(sync_env.runtime_home)
        if (base_success and wrapper_success)
        else True
    )

    if base_success and wrapper_success:
        prune_unreferenced_releases(
            str(Path(sync_env.runtime_home) / "sync-releases"),
            str(Path(sync_env.runtime_home) / "sync-current"),
            sync_env.install_timeout_ms,
        )

    managed_state_success = (
        record_managed_entries(managed_plan)
        if (base_success and wrapper_success)
        else True
    )

    hook_success = (
        await run_sync_hooks(sync_plan.hooks, extension_hook_states)
        if (base_success and wrapper_success and managed_state_success)
        else True
    )

    success = (
        base_success
        and managed_tool_success
        and wrapper_success
        and managed_state_success
        and hook_success
        and legacy_cleanup_success
    )

    if (
        success
        and warn_managed_services
        and any(tool.name == "cliproxyapi" for tool in managed_tools)
        and not is_cli_proxy_running(sync_plan.cli_proxy_deployment)
    ):
        warn("CLIProxyAPI is installed but not running; start it with: cli-proxy-api")

    return success


def main() -> int:
    """CLI entrypoint for sync reconciliation; returns exit code."""
    return asyncio.run(_async_main())


async def _async_main() -> int:
    try:
        sync_env = SyncEnv.from_system()
    except (OSError, RuntimeError, ValueError, TypeError) as error:
        err(panic_message(error))
        return EXIT_ERROR

    try:
        lock = try_acquire_sync_lock(sync_env)
    except (OSError, RuntimeError, ValueError, TypeError) as error:
        err(panic_message(error))
        return EXIT_ERROR

    if lock is None:
        err("another sync is already running; skipping")
        return EXIT_OK

    try:
        stop_watchdog = start_sync_watchdog(sync_timeout())
        try:
            success = await run_sync(sync_env, warn_managed_services=True)
            return EXIT_OK if success else EXIT_ERROR
        finally:
            stop_watchdog()
    finally:
        release_sync_lock(lock)


def launch_main(source_name: str, args: Sequence[str]) -> int:
    """CLI entrypoint for launching a harness or tool; returns exit code."""
    return asyncio.run(_async_launch_main(source_name, args))


async def _sync_before_launch(sync_env: SyncEnv) -> None:
    lock = None
    try:
        lock = try_acquire_sync_lock(sync_env)
    except (OSError, RuntimeError, ValueError, TypeError) as error:
        message = panic_message(error)
        warn(f"sync before launch unavailable: {message}")

    if lock is not None:
        try:
            success = await run_sync(sync_env)
            if not success:
                warn("continuing launch without completed sync")
        finally:
            release_sync_lock(lock)
    else:
        warn("another sync is already running; continuing launch")


def _resolve_launch_target(
    sync_env: SyncEnv,
    source_name: str,
    *,
    ssot_available: bool,
) -> tuple[Harness | None, ToolLauncherSpec | None]:
    harness = next(
        (c for c in sync_env.harnesses if c.source_name == source_name),
        None,
    )
    if harness is None and not ssot_available:
        harness = supported_harness(sync_env.home, source_name, sync_env.platform)
    tool = None if harness is not None else tool_launcher(source_name)
    return harness, tool


async def _async_launch_main(
    source_name: str,
    args: Sequence[str],
) -> int:
    try:
        sync_env = SyncEnv.from_system()
    except (OSError, RuntimeError, ValueError, TypeError) as error:
        err(panic_message(error))
        return EXIT_ERROR

    ssot_available = await asyncio.to_thread(Path(sync_env.ssot_home).exists)
    harness, tool = _resolve_launch_target(
        sync_env, source_name, ssot_available=ssot_available
    )

    if harness is None and tool is None:
        err(f"unsupported launch target: {source_name}")
        return EXIT_UNSUPPORTED

    if ssot_available:
        await _sync_before_launch(sync_env)
    else:
        warn(
            "agent configuration source is unavailable; "
            "continuing with installed runtime"
        )

    try:
        if tool is not None:
            spec = NpmPackageSpec(
                tool=tool.id,
                package=tool.package,
                bin=tool.bin,
                dist_tag=tool.dist_tag,
                smoke_check=tool.smoke_check,
            )
            return await launch_npm_package(sync_env, spec, args)
        if harness is not None:
            return await launch_harness(sync_env, harness, args)
    except (OSError, RuntimeError, ValueError, TypeError) as error:
        message = panic_message(error)
        err(f"launch failed: {message}")
        return EXIT_ERROR

    err(f"unsupported launch target: {source_name}")
    return EXIT_UNSUPPORTED


async def run_sync_hooks(
    hooks: Sequence[SyncHookPlan],
    extension_hook_states: Mapping[str, ExtensionHookRuntimeState],
) -> bool:
    """Run all sync hook plans, returning True if all succeeded."""
    success = True
    for hook in hooks:
        hook_state: PreparedExtensionHookState | None = None
        if hook.kind == "ExtensionDeps":
            runtime_state = extension_hook_states.get(hook.state_path)
            if runtime_state is not None:
                hook_state = runtime_state.state
        if not await run_sync_hook(hook, hook_state):
            success = False
    return success


async def run_sync_hook(
    hook: SyncHookPlan,
    extension_hook_state: PreparedExtensionHookState | None = None,
) -> bool:
    """Execute a single sync hook plan and record updated state."""
    try:
        match hook.kind:
            case "PackageBootstrap":
                target = PackageBootstrapTarget(
                    manifest_path=hook.manifest_path,
                    runtime_settings_path=hook.runtime_settings_path,
                    cache_root=hook.cache_root,
                    timeout_ms=hook.timeout_ms,
                )
                return await bootstrap_package_target(target)
            case "ExtensionDeps":
                if (
                    extension_hook_state is not None
                    and extension_hook_state.should_skip
                ):
                    if extension_hook_state.should_refresh_state:
                        record_extension_hook_state(hook, extension_hook_state)
                    return True
                success = await install_extension_deps(
                    hook.root, hook.source_root, hook.timeout_ms
                )
                if success:
                    state_to_record = (
                        extension_hook_state
                        if extension_hook_state is not None
                        else prepare_extension_hook_state(hook)
                    )
                    record_extension_hook_state(hook, state_to_record)
                else:
                    clear_extension_hook_state(hook.state_path)
                return success
            case _:
                assert_never(hook)
    except (OSError, RuntimeError, ValueError, TypeError) as error:
        if hook.kind == "ExtensionDeps":
            clear_extension_hook_state(hook.state_path)
        err(panic_message(error))
        return False


def prepare_extension_hook_states(
    hooks: Sequence[SyncHookPlan],
) -> dict[str, ExtensionHookRuntimeState]:
    """Compute prepared states for all ExtensionDeps hooks."""
    states: dict[str, ExtensionHookRuntimeState] = {}
    for hook in hooks:
        if hook.kind != "ExtensionDeps":
            continue
        states[hook.state_path] = ExtensionHookRuntimeState(
            hook=hook,
            state=prepare_extension_hook_state(hook),
        )
    return states


def preserve_paths_by_dst(
    states: Mapping[str, ExtensionHookRuntimeState],
) -> dict[str, list[str]]:
    """Index preserved paths by job root destination directory."""
    preserve_by_dst: dict[str, list[str]] = {}
    for runtime_state in states.values():
        hook = runtime_state.hook
        state = runtime_state.state
        if not state.should_skip or not state.preserve_paths:
            continue
        existing = preserve_by_dst.setdefault(hook.job_root, [])
        existing.extend(state.preserve_paths)
        preserve_by_dst[hook.job_root] = sorted(set(existing))
    return preserve_by_dst
