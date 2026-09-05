# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Internal adapters for harnesses understood by sync.

A matching directory under harnesses/ opts into an adapter. Users never need to
repeat launcher, platform, destination, or hook plumbing in configuration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Callable

type HostPlatform = Literal["darwin", "linux"]

type HarnessId = Literal["codex", "deepseek", "grok", "opencode", "pi", "omp"]


@dataclass(frozen=True, slots=True)
class HarnessLauncherSpec:
    """Launcher configuration specification for a harness."""

    package: str
    bin: str
    dist_tag: str | None = None
    smoke_check: str | None = None
    default_args: tuple[str, ...] | None = None
    env: dict[str, str] | Callable[[str], dict[str, str]] | None = None


@dataclass(frozen=True, slots=True)
class PackageBootstrapHook:
    """Hook specification for bootstrapping packages into a harness runtime."""

    manifest_file: str | None = None
    settings_file: str | None = None
    cache_subdir: str | None = None
    kind: Literal["PackageBootstrap"] = "PackageBootstrap"


@dataclass(frozen=True, slots=True)
class ExtensionDepsHook:
    """Hook specification for installing extension dependencies."""

    root_dir: str
    kind: Literal["ExtensionDeps"] = "ExtensionDeps"


type HarnessHookSpec = PackageBootstrapHook | ExtensionDepsHook


@dataclass(frozen=True, slots=True)
class HarnessAdapter:
    """Static harness adapter definition."""

    id: HarnessId
    home_segments: tuple[str, ...]
    platforms: tuple[HostPlatform, ...]
    launcher: HarnessLauncherSpec
    instruction_file: str | None = None
    runtime_subdir: str | None = None
    compat_managed_entries: tuple[str, ...] | None = None
    hooks: tuple[HarnessHookSpec, ...] | None = None


HARNESS_ADAPTERS: tuple[HarnessAdapter, ...] = (
    HarnessAdapter(
        id="codex",
        home_segments=(".codex",),
        platforms=("darwin", "linux"),
        launcher=HarnessLauncherSpec(
            package="@openai/codex",
            bin="codex",
        ),
    ),
    HarnessAdapter(
        id="deepseek",
        home_segments=(".dsh",),
        platforms=("darwin", "linux"),
        launcher=HarnessLauncherSpec(
            package="@deepseek-ai/dsh",
            bin="dsh",
        ),
    ),
    HarnessAdapter(
        id="grok",
        home_segments=(".grok",),
        platforms=("darwin", "linux"),
        launcher=HarnessLauncherSpec(
            package="@xai-official/grok",
            bin="grok",
        ),
    ),
    HarnessAdapter(
        id="opencode",
        home_segments=(".config", "opencode"),
        platforms=("darwin", "linux"),
        launcher=HarnessLauncherSpec(
            package="opencode-ai",
            bin="opencode",
        ),
        hooks=(ExtensionDepsHook(root_dir="."),),
    ),
    HarnessAdapter(
        id="pi",
        home_segments=(".pi",),
        platforms=("darwin", "linux"),
        launcher=HarnessLauncherSpec(
            package="@earendil-works/pi-coding-agent",
            bin="pi",
        ),
        runtime_subdir="agent",
        compat_managed_entries=("legacy",),
        hooks=(
            PackageBootstrapHook(
                manifest_file="packages.json",
                settings_file="settings.json",
            ),
            ExtensionDepsHook(root_dir="extensions"),
        ),
    ),
    HarnessAdapter(
        id="omp",
        home_segments=(".omp",),
        platforms=("darwin", "linux"),
        launcher=HarnessLauncherSpec(
            package="@oh-my-pi/pi-coding-agent",
            bin="omp",
        ),
        runtime_subdir="agent",
        hooks=(ExtensionDepsHook(root_dir="."),),
    ),
)

__all__ = [
    "HARNESS_ADAPTERS",
    "ExtensionDepsHook",
    "HarnessAdapter",
    "HarnessHookSpec",
    "HarnessId",
    "HarnessLauncherSpec",
    "HostPlatform",
    "PackageBootstrapHook",
]
