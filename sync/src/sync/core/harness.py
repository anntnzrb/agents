# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Harness definitions, environment discovery, and root configuration loader."""

from __future__ import annotations

import io
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING

import dotenv

from sync.core.harness_adapters import (
    DEFAULT_INSTRUCTION_FILE,
    DEFAULT_PACKAGE_CACHE_SUBDIR,
    HARNESS_ADAPTERS,
    ExtensionDepsHook,
    HarnessAdapter,
    HarnessHookSpec,
    HarnessId,
    HarnessLauncherSpec,
    HostPlatform,
    LauncherEnv,
    PackageBootstrapHook,
    StaticReleaseLauncherSpec,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

SOURCE_AGENT_FILE: str = "HARNESS.md"
INSTALL_TIMEOUT_MS: int = 120_000
MANAGED_STATE_SUBDIR: str = ".local/share/agents/sync-managed"
SKILLS_DST_DIR: str = "skills"
SKILLS_SOURCE_SUBDIR: str = "current"
PATH_COMPONENT_PATTERN: re.Pattern[str] = re.compile(r"^[A-Za-z0-9._-]+$")

type HarnessHook = PackageBootstrapHook | ExtensionDepsHook


@dataclass(frozen=True, slots=True)
class StaticRelease:
    """Resolved static CDN release source for a harness launcher."""

    manifest_url: str
    install_segments: tuple[str, ...]
    executable_segments: tuple[str, ...]
    targets: Mapping[str, str]
    man_segments: tuple[str, ...] | None = None
    man_dest_segments: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class NpmLauncher:
    """Resolved npm package launcher configuration."""

    package: str
    bin: str
    dist_tag: str = "latest"
    smoke_check: str = "--version"
    default_args: tuple[str, ...] = ()
    env: dict[str, str] | None = None


@dataclass(frozen=True, slots=True)
class StaticReleaseLauncher:
    """Resolved static release launcher configuration."""

    bin: str
    release: StaticRelease
    smoke_check: str = "--version"
    default_args: tuple[str, ...] = ()
    env: dict[str, str] | None = None


type HarnessLauncher = NpmLauncher | StaticReleaseLauncher


@dataclass(frozen=True, slots=True)
class HarnessSpec:
    """Input specification for building a resolved Harness."""

    id: HarnessId
    source_name: str
    home: str
    launcher: HarnessLauncherSpec
    instruction_file: str | None = None
    runtime_subdir: str | None = None
    compat_managed_entries: tuple[str, ...] | None = None
    preserve_json_keys: Mapping[str, tuple[str, ...]] | None = None
    hooks: tuple[HarnessHookSpec, ...] | None = None


@dataclass(frozen=True, slots=True)
class Harness:
    """Fully resolved harness configuration."""

    id: HarnessId
    source_name: str
    home: str
    launcher: HarnessLauncher
    instruction_file: str = DEFAULT_INSTRUCTION_FILE
    runtime_subdir: str | None = None
    compat_managed_entries: tuple[str, ...] = ()
    preserve_json_keys: Mapping[str, tuple[str, ...]] = MappingProxyType({})
    hooks: tuple[HarnessHook, ...] = ()


@dataclass(frozen=True, slots=True)
class SyncEnv:
    """Environment layout and configuration for a sync run."""

    home: str
    ssot_home: str
    runtime_home: str
    skills_home: str
    harnesses_home: str
    mcporter_home: str
    summarize_home: str
    managed_state_home: str
    install_timeout_ms: int
    harnesses: tuple[Harness, ...]
    platform: HostPlatform
    root_env: dict[str, str]

    @classmethod
    def from_system(cls) -> SyncEnv:
        """Create a SyncEnv by resolving the home directory from the environment."""
        home = os.environ.get("HOME", "").strip()
        if not home:
            expanded = str(Path("~").expanduser()).strip()
            if expanded and expanded != "~":
                home = expanded
        if not home:
            message = "missing HOME"
            raise RuntimeError(message)
        return cls.from_home(home, INSTALL_TIMEOUT_MS)

    @classmethod
    def from_home(
        cls,
        home: str,
        install_timeout_ms: int = INSTALL_TIMEOUT_MS,
        *,
        platform: HostPlatform | None = None,
    ) -> SyncEnv:
        """Create a SyncEnv for a specified user home directory."""
        home_path = Path(home)
        agents_home = str(home_path / ".config" / "agents")
        harnesses_home = str(home_path / ".config" / "agents" / "harnesses")
        resolved_platform = (
            platform if platform is not None else platform_from_process()
        )
        env_path = str(home_path / ".config" / "agents" / ".env")
        return cls(
            home=home,
            ssot_home=agents_home,
            runtime_home=str(home_path / ".local" / "share" / "agents"),
            skills_home=str(home_path / ".config" / "agents" / "skills"),
            harnesses_home=harnesses_home,
            mcporter_home=str(home_path / ".mcporter"),
            summarize_home=str(home_path / ".summarize"),
            managed_state_home=str(home_path / MANAGED_STATE_SUBDIR),
            install_timeout_ms=install_timeout_ms,
            harnesses=discover_harnesses(home, harnesses_home, resolved_platform),
            platform=resolved_platform,
            root_env=load_root_env(env_path),
        )

    def harness(self, harness_id: HarnessId) -> Harness | None:
        """Look up a discovered harness by its identifier."""
        return next((h for h in self.harnesses if h.id == harness_id), None)


class RootEnvReadError(Exception):
    """Raised when reading the root .env file fails with a non-ENOENT error."""

    path: str
    cause: BaseException | None

    def __init__(self, path: str, cause: BaseException | None = None) -> None:
        """Initialize RootEnvReadError with path and optional cause."""
        self.path = path
        self.cause = cause
        message = f"failed to read root environment file {path}"
        super().__init__(message)


def read_root_env_content(env_path: str) -> str | None:
    """Read the content of the root environment file.

    Returns None if the file does not exist (ENOENT).
    Raises RootEnvReadError if reading fails for any other reason (e.g. EISDIR).
    """
    try:
        return Path(env_path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as err:
        raise RootEnvReadError(env_path, err) from err


def decode_root_env(content: str | None) -> dict[str, str]:
    """Decode root .env content into a key-value dictionary.

    - Variable expansion is disabled (interpolate=False).
    - Empty string values are excluded.
    - Purely file-based; values are not merged with or overridden by os.environ.
    """
    if content is None:
        return {}
    raw = dotenv.dotenv_values(stream=io.StringIO(content), interpolate=False)
    return {k: v for k, v in raw.items() if v is not None and v != ""}


def load_root_env(env_path: str) -> dict[str, str]:
    """Load and parse the root .env file at `env_path`.

    Returns an empty dict if the file does not exist.
    Raises RootEnvReadError if reading fails.
    """
    content = read_root_env_content(env_path)
    return decode_root_env(content)


def _resolve_launcher_env(
    env: LauncherEnv | None,
    home: str,
) -> dict[str, str] | None:
    if callable(env):
        return env(home)
    return env


def _build_launcher(spec: HarnessLauncherSpec, home: str) -> HarnessLauncher:
    launcher_env = _resolve_launcher_env(spec.env, home)
    smoke_check = spec.smoke_check or "--version"
    default_args = spec.default_args or ()

    if isinstance(spec, StaticReleaseLauncherSpec):
        return StaticReleaseLauncher(
            bin=spec.bin,
            release=StaticRelease(
                manifest_url=spec.release.manifest_url,
                install_segments=spec.release.install_segments,
                executable_segments=spec.release.executable_segments,
                targets=spec.release.targets,
                man_segments=spec.release.man_segments,
                man_dest_segments=spec.release.man_dest_segments,
            ),
            smoke_check=smoke_check,
            default_args=default_args,
            env=launcher_env,
        )
    return NpmLauncher(
        package=spec.package,
        bin=spec.bin,
        dist_tag=spec.dist_tag or "latest",
        smoke_check=smoke_check,
        default_args=default_args,
        env=launcher_env,
    )


def build_harness(spec: HarnessSpec) -> Harness:
    """Build a resolved Harness instance from a specification."""
    assert_path_component(spec.source_name, "harness id")
    return Harness(
        id=spec.id,
        source_name=spec.source_name,
        home=spec.home,
        launcher=_build_launcher(spec.launcher, spec.home),
        instruction_file=spec.instruction_file or DEFAULT_INSTRUCTION_FILE,
        runtime_subdir=spec.runtime_subdir,
        compat_managed_entries=spec.compat_managed_entries or (),
        preserve_json_keys=spec.preserve_json_keys or {},
        hooks=normalize_hooks(spec.hooks or ()),
    )


def _adapter_target_home(adapter: HarnessAdapter, user_home: str) -> str:
    for segment in adapter.home_segments:
        assert_path_component(segment, f"{adapter.id} home segment")
    return str(Path(user_home).joinpath(*adapter.home_segments))


def _adapter_to_harness(
    adapter: HarnessAdapter,
    user_home: str,
    source_name: str | None = None,
) -> Harness:
    target_home = _adapter_target_home(adapter, user_home)
    spec = HarnessSpec(
        id=adapter.id,
        source_name=source_name if source_name is not None else adapter.id,
        home=target_home,
        launcher=adapter.launcher,
        instruction_file=adapter.instruction_file,
        runtime_subdir=adapter.runtime_subdir,
        compat_managed_entries=adapter.compat_managed_entries,
        preserve_json_keys=adapter.preserve_json_keys,
        hooks=adapter.hooks,
    )
    return build_harness(spec)


def discover_harnesses(
    home: str,
    harnesses_home: str,
    platform: HostPlatform | None = None,
) -> tuple[Harness, ...]:
    """Discover active harnesses based on installed directories and target platform."""
    resolved_platform = platform if platform is not None else platform_from_process()
    harnesses_path = Path(harnesses_home)
    return tuple(
        _adapter_to_harness(adapter, home)
        for adapter in HARNESS_ADAPTERS
        if resolved_platform in adapter.platforms
        and is_directory(str(harnesses_path / adapter.id))
    )


def supported_harness(
    home: str,
    source_name: str,
    platform: HostPlatform,
) -> Harness | None:
    """Find a supported harness adapter by name and platform."""
    for adapter in HARNESS_ADAPTERS:
        if adapter.id == source_name and platform in adapter.platforms:
            return _adapter_to_harness(adapter, home, source_name=source_name)
    return None


def is_directory(candidate: str) -> bool:
    """Check if a filesystem path exists and is a directory."""
    try:
        return Path(candidate).is_dir()
    except OSError:
        return False


def platform_from_process() -> HostPlatform:
    """Determine the host platform from the current Python runtime."""
    system = sys.platform
    if system in ("darwin", "linux"):
        return system
    message = f"unsupported platform: {system}"
    raise RuntimeError(message)


def assert_path_component(value: str, label: str) -> None:
    """Validate that a path segment is safe and matches PATH_COMPONENT_PATTERN."""
    if not PATH_COMPONENT_PATTERN.fullmatch(value) or value in (".", ".."):
        message = f"invalid {label}: {value}"
        raise ValueError(message)


def harness_root(harness: Harness) -> str:
    """Return the absolute root directory of a harness."""
    home_path = Path(harness.home)
    return (
        str(home_path / harness.runtime_subdir)
        if harness.runtime_subdir
        else harness.home
    )


def harness_source_root(harness: Harness, harnesses_home: str) -> str:
    """Return the SSOT source directory of a harness."""
    base_path = Path(harnesses_home) / harness.source_name
    return (
        str(base_path / harness.runtime_subdir)
        if harness.runtime_subdir
        else str(base_path)
    )


def harness_instruction_target(harness: Harness) -> str:
    """Return the destination path for the harness instruction file."""
    return str(Path(harness_root(harness)) / harness.instruction_file)


def harness_instruction_file_name(harness: Harness) -> str:
    """Return the base instruction file name for a harness."""
    return harness.instruction_file


def harness_managed_state_path(harness: Harness, managed_state_home: str) -> str:
    """Return the managed state JSON path for a harness."""
    return str(Path(managed_state_home) / f"{harness.source_name}.json")


def normalize_hooks(
    hooks: Sequence[HarnessHookSpec] = (),
) -> tuple[HarnessHook, ...]:
    """Normalize harness hook specifications with default file paths."""
    result: list[HarnessHook] = []
    for hook in hooks:
        if isinstance(hook, PackageBootstrapHook):
            result.append(
                PackageBootstrapHook(
                    manifest_file=hook.manifest_file or "packages.json",
                    settings_file=hook.settings_file or "settings.json",
                    cache_subdir=hook.cache_subdir or DEFAULT_PACKAGE_CACHE_SUBDIR,
                )
            )
        else:
            result.append(hook)
    return tuple(result)


__all__ = [
    "DEFAULT_INSTRUCTION_FILE",
    "DEFAULT_PACKAGE_CACHE_SUBDIR",
    "HARNESS_ADAPTERS",
    "INSTALL_TIMEOUT_MS",
    "MANAGED_STATE_SUBDIR",
    "PATH_COMPONENT_PATTERN",
    "SKILLS_DST_DIR",
    "SKILLS_SOURCE_SUBDIR",
    "SOURCE_AGENT_FILE",
    "ExtensionDepsHook",
    "Harness",
    "HarnessAdapter",
    "HarnessHookSpec",
    "HarnessId",
    "HarnessLauncherSpec",
    "HarnessSpec",
    "HostPlatform",
    "NpmLauncher",
    "PackageBootstrapHook",
    "RootEnvReadError",
    "StaticRelease",
    "StaticReleaseLauncher",
    "SyncEnv",
    "assert_path_component",
    "build_harness",
    "discover_harnesses",
    "harness_instruction_target",
    "harness_managed_state_path",
    "harness_root",
    "harness_source_root",
    "is_directory",
    "load_root_env",
    "platform_from_process",
    "supported_harness",
]
