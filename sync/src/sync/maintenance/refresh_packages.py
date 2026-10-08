# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Refresh installed launcher packages independently of interactive launches."""

from __future__ import annotations

import asyncio
from pathlib import Path

from sync.core.harness import (
    Harness,
    StaticRelease,
    StaticReleaseLauncher,
    SyncEnv,
    harness_from_adapter,
)
from sync.core.harness_adapters import HARNESS_ADAPTERS
from sync.core.launcher import (
    NpmPackageSpec,
    PreparePackageOptions,
    harness_package_spec,
    refresh_npm_package,
    refresh_static_release,
)
from sync.core.tool_launchers import TOOL_LAUNCHERS
from sync.core.wrappers import is_managed_wrapper
from sync.runtime.errors import err, panic_message, warn


def _host_harnesses(sync_env: SyncEnv) -> tuple[Harness, ...]:
    """Include configured harnesses and managed wrappers left without their SSOT."""
    harnesses = {h.id: h for h in sync_env.harnesses}
    # Installed wrappers remain usable when the SSOT is temporarily unavailable.
    for adapter in HARNESS_ADAPTERS:
        if sync_env.platform in adapter.platforms and is_managed_wrapper(
            str(Path(sync_env.home) / ".local/bin" / adapter.launcher.bin)
        ):
            _ = harnesses.setdefault(
                adapter.id, harness_from_adapter(adapter, sync_env.home)
            )

    return tuple(harnesses.values())


async def _refresh_packages(sync_env: SyncEnv) -> int:
    packages = [
        NpmPackageSpec(
            tool=tool.id,
            package=tool.package,
            bin=tool.bin,
            dist_tag=tool.dist_tag,
            smoke_check=tool.smoke_check,
        )
        for tool in TOOL_LAUNCHERS
    ]
    releases: list[tuple[str, StaticRelease]] = []
    for harness in _host_harnesses(sync_env):
        if isinstance(harness.launcher, StaticReleaseLauncher):
            releases.append((harness.source_name, harness.launcher.release))
        else:
            packages.append(harness_package_spec(harness))

    failures = 0
    successes = 0
    skipped = 0
    options = PreparePackageOptions(
        home=sync_env.home, timeout_ms=sync_env.install_timeout_ms
    )
    for spec in packages:
        try:
            refreshed = await refresh_npm_package(spec, options)
        except (OSError, RuntimeError, ValueError, TypeError) as error:
            warn(f"refresh-packages: {spec.tool}: {panic_message(error)}")
            failures += 1
        else:
            successes += int(refreshed)
            skipped += int(not refreshed)
    for name, release in releases:
        try:
            refreshed = await refresh_static_release(
                release, sync_env.home, sync_env.install_timeout_ms
            )
        except (OSError, RuntimeError, ValueError, TypeError) as error:
            warn(f"refresh-packages: {name}: {panic_message(error)}")
            failures += 1
        else:
            successes += int(refreshed)
            skipped += int(not refreshed)
    return int(failures > 0 and successes == 0 and skipped == 0)


def refresh_packages(sync_env: SyncEnv | None = None) -> int:
    """Refresh every host launcher; only a wholly failed round exits nonzero."""
    try:
        return asyncio.run(
            _refresh_packages(
                sync_env if sync_env is not None else SyncEnv.from_system()
            )
        )
    except (OSError, RuntimeError, ValueError, TypeError) as error:
        err(f"refresh-packages: {panic_message(error)}")
        return 1
