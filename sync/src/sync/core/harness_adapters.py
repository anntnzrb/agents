# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Internal adapters for harnesses understood by sync.

A matching directory under harnesses/ opts into an adapter. Users never need to
repeat launcher, platform, destination, or hook plumbing in configuration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

type HostPlatform = Literal["darwin", "linux"]

type HarnessId = Literal["codex", "deepseek", "devin", "opencode", "pi", "omp"]

DEFAULT_INSTRUCTION_FILE: str = "AGENTS.md"
DEFAULT_PACKAGE_CACHE_SUBDIR: str = ".local/share/agents/pi-packages"

type LauncherEnv = dict[str, str] | Callable[[str], dict[str, str]]


@dataclass(frozen=True, slots=True)
class StaticReleaseSpec:
    """Static CDN release specification resolved from a versioned manifest."""

    manifest_url: str
    install_segments: tuple[str, ...]
    executable_segments: tuple[str, ...]
    targets: Mapping[str, str]
    man_segments: tuple[str, ...] | None = None
    man_dest_segments: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class NpmLauncherSpec:
    """Launcher configuration for an npm-distributed harness."""

    package: str
    bin: str
    dist_tag: str | None = None
    smoke_check: str | None = None
    default_args: tuple[str, ...] | None = None
    env: LauncherEnv | None = None


@dataclass(frozen=True, slots=True)
class StaticReleaseLauncherSpec:
    """Launcher configuration for a static-manifest harness."""

    bin: str
    release: StaticReleaseSpec
    smoke_check: str | None = None
    default_args: tuple[str, ...] | None = None
    env: LauncherEnv | None = None


type HarnessLauncherSpec = NpmLauncherSpec | StaticReleaseLauncherSpec


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
    merge_json_files: tuple[str, ...] | None = None
    hooks: tuple[HarnessHookSpec, ...] | None = None


HARNESS_ADAPTERS: tuple[HarnessAdapter, ...] = (
    HarnessAdapter(
        id="codex",
        home_segments=(".codex",),
        platforms=("darwin", "linux"),
        launcher=NpmLauncherSpec(
            package="@openai/codex",
            bin="codex",
        ),
    ),
    HarnessAdapter(
        id="deepseek",
        home_segments=(".dsh",),
        platforms=("darwin", "linux"),
        launcher=NpmLauncherSpec(
            package="@deepseek-ai/dsh",
            bin="dsh",
        ),
    ),
    HarnessAdapter(
        id="devin",
        home_segments=(".config", "devin"),
        platforms=("darwin", "linux"),
        launcher=StaticReleaseLauncherSpec(
            bin="devin",
            release=StaticReleaseSpec(
                manifest_url="https://static.devin.ai/cli/current/manifest.json",
                install_segments=(".local", "share", "devin", "cli"),
                executable_segments=("bin", "devin"),
                targets={
                    "darwin-arm64": "aarch64-apple-darwin",
                    "darwin-x64": "x86_64-apple-darwin",
                    "linux-arm64": "aarch64-unknown-linux",
                    "linux-x64": "x86_64-unknown-linux",
                },
                man_segments=("share", "man", "man1"),
                man_dest_segments=(".local", "share", "man", "man1"),
            ),
            env={"DEVIN_PERMISSION_MODE": "bypass"},
        ),
        merge_json_files=("config.json",),
    ),
    HarnessAdapter(
        id="opencode",
        home_segments=(".config", "opencode"),
        platforms=("darwin", "linux"),
        launcher=NpmLauncherSpec(
            package="opencode-ai",
            bin="opencode",
        ),
        hooks=(ExtensionDepsHook(root_dir="."),),
    ),
    HarnessAdapter(
        id="pi",
        home_segments=(".pi",),
        platforms=("darwin", "linux"),
        launcher=NpmLauncherSpec(
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
        launcher=NpmLauncherSpec(
            package="@oh-my-pi/pi-coding-agent",
            bin="omp",
        ),
        runtime_subdir="agent",
        hooks=(ExtensionDepsHook(root_dir="."),),
    ),
)

__all__ = [
    "DEFAULT_INSTRUCTION_FILE",
    "DEFAULT_PACKAGE_CACHE_SUBDIR",
    "HARNESS_ADAPTERS",
    "ExtensionDepsHook",
    "HarnessAdapter",
    "HarnessHookSpec",
    "HarnessId",
    "HarnessLauncherSpec",
    "HostPlatform",
    "LauncherEnv",
    "NpmLauncherSpec",
    "PackageBootstrapHook",
    "StaticReleaseLauncherSpec",
]
