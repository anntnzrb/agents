# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Harness definitions, environment discovery, and root configuration loader."""

from __future__ import annotations

import io
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import dotenv

from sync.core.harness_adapters import (
    HARNESS_ADAPTERS,
    ExtensionDepsHook,
    HarnessAdapter,
    HarnessHookSpec,
    HarnessId,
    HarnessLauncherSpec,
    HostPlatform,
    PackageBootstrapHook,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

SOURCE_AGENT_FILE: str = "HARNESS.md"
DEFAULT_INSTRUCTION_FILE: str = "AGENTS.md"
INSTALL_TIMEOUT_SECONDS: int = 120
INSTALL_TIMEOUT_MS: int = 120_000
MANAGED_STATE_SUBDIR: str = ".local/share/agents/sync-managed"
DEFAULT_PACKAGE_CACHE_SUBDIR: str = ".local/share/agents/pi-packages"
SKILLS_DST_DIR: str = "skills"
SKILLS_SOURCE_SUBDIR: str = "current"
PATH_COMPONENT_PATTERN: re.Pattern[str] = re.compile(r"^[A-Za-z0-9._-]+$")

type HarnessHook = PackageBootstrapHook | ExtensionDepsHook


@dataclass(frozen=True, slots=True)
class HarnessLauncher:
    """Resolved harness launcher configuration."""

    package: str
    bin: str
    dist_tag: str = "latest"
    smoke_check: str = "--version"
    default_args: tuple[str, ...] = ()
    env: dict[str, str] | None = None


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
        runtime_home = str(home_path / ".local" / "share" / "agents")
        harnesses_home = str(home_path / ".config" / "agents" / "harnesses")
        resolved_platform = (
            platform if platform is not None else platform_from_process()
        )
        env_path = str(home_path / ".config" / "agents" / ".env")
        root_env = load_root_env(env_path)
        harnesses = discover_harnesses(home, harnesses_home, resolved_platform)
        return cls(
            home=home,
            ssot_home=agents_home,
            runtime_home=runtime_home,
            skills_home=str(home_path / ".config" / "agents" / "skills"),
            harnesses_home=harnesses_home,
            mcporter_home=str(home_path / ".mcporter"),
            summarize_home=str(home_path / ".summarize"),
            managed_state_home=str(home_path / MANAGED_STATE_SUBDIR),
            install_timeout_ms=install_timeout_ms,
            harnesses=harnesses,
            platform=resolved_platform,
            root_env=root_env,
        )

    def harness(self, harness_id: HarnessId) -> Harness | None:
        """Look up a discovered harness by its identifier."""
        for candidate in self.harnesses:
            if candidate.id == harness_id:
                return candidate
        return None


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


def parse_dotenv_fallback(content: str) -> dict[str, str]:
    """Parse .env content without external dependencies as a fallback."""
    result: dict[str, str] = {}
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        key, _, val = stripped.partition("=")
        key = key.strip()
        val = val.strip()
        if not key:
            continue
        if (val.startswith('"') and val.endswith('"')) or (
            val.startswith("'") and val.endswith("'")
        ):
            val = val[1:-1]
        else:
            comment_idx = val.find(" #")
            if comment_idx != -1:
                val = val[:comment_idx].rstrip()
        if val:
            result[key] = val
    return result


def decode_root_env(content: str | None) -> dict[str, str]:
    """Decode root .env content into a key-value dictionary.

    Precedence and semantics match Effect ConfigProvider.fromDotEnvContents
    in sync/src/core/harness.ts lines 162-212:
    - Variable expansion is disabled (expandVariables: false).
    - Empty string values are excluded (preserveEmptyStrings: false).
    - Purely file-based; values are not merged with or overridden by os.environ.
    """
    if content is None:
        return {}
    try:
        raw = dotenv.dotenv_values(stream=io.StringIO(content), interpolate=False)
        return {k: v for k, v in raw.items() if v is not None and v != ""}
    except (OSError, ValueError, TypeError):
        return parse_dotenv_fallback(content)


def load_root_env(env_path: str) -> dict[str, str]:
    """Load and parse the root .env file at `env_path`.

    Returns an empty dict if the file does not exist.
    Raises RootEnvReadError if reading fails.
    """
    content = read_root_env_content(env_path)
    return decode_root_env(content)


def build_harness(spec: HarnessSpec) -> Harness:
    """Build a resolved Harness instance from a specification."""
    assert_path_component(spec.source_name, "harness id")
    launcher_env: dict[str, str] | None = None
    if callable(spec.launcher.env):
        launcher_env = spec.launcher.env(spec.home)
    elif spec.launcher.env is not None:
        launcher_env = spec.launcher.env

    launcher = HarnessLauncher(
        package=spec.launcher.package,
        bin=spec.launcher.bin,
        dist_tag=(
            spec.launcher.dist_tag if spec.launcher.dist_tag is not None else "latest"
        ),
        smoke_check=(
            spec.launcher.smoke_check
            if spec.launcher.smoke_check is not None
            else "--version"
        ),
        default_args=(
            spec.launcher.default_args if spec.launcher.default_args is not None else ()
        ),
        env=launcher_env,
    )
    return Harness(
        id=spec.id,
        source_name=spec.source_name,
        home=spec.home,
        launcher=launcher,
        instruction_file=(
            spec.instruction_file
            if spec.instruction_file is not None
            else DEFAULT_INSTRUCTION_FILE
        ),
        runtime_subdir=spec.runtime_subdir,
        compat_managed_entries=(
            spec.compat_managed_entries
            if spec.compat_managed_entries is not None
            else ()
        ),
        hooks=normalize_hooks(spec.hooks if spec.hooks is not None else ()),
    )


def discover_harnesses(
    home: str,
    harnesses_home: str,
    platform: HostPlatform | None = None,
) -> tuple[Harness, ...]:
    """Discover active harnesses based on installed directories and target platform."""
    resolved_platform = platform if platform is not None else platform_from_process()
    results: list[Harness] = []
    harnesses_path = Path(harnesses_home)
    home_path = Path(home)
    for adapter in HARNESS_ADAPTERS:
        adapter_dir = str(harnesses_path / adapter.id)
        if resolved_platform in adapter.platforms and is_directory(adapter_dir):
            for segment in adapter.home_segments:
                assert_path_component(segment, f"{adapter.id} home segment")
            target_home = str(home_path.joinpath(*adapter.home_segments))
            spec = HarnessSpec(
                id=adapter.id,
                source_name=adapter.id,
                home=target_home,
                launcher=adapter.launcher,
                instruction_file=adapter.instruction_file,
                runtime_subdir=adapter.runtime_subdir,
                compat_managed_entries=adapter.compat_managed_entries,
                hooks=adapter.hooks,
            )
            results.append(build_harness(spec))
    return tuple(results)


def supported_harness(
    home: str,
    source_name: str,
    platform: HostPlatform,
) -> Harness | None:
    """Find a supported harness adapter by name and platform."""
    home_path = Path(home)
    for adapter in HARNESS_ADAPTERS:
        if adapter.id == source_name and platform in adapter.platforms:
            for segment in adapter.home_segments:
                assert_path_component(segment, f"{adapter.id} home segment")
            target_home = str(home_path.joinpath(*adapter.home_segments))
            spec = HarnessSpec(
                id=adapter.id,
                source_name=adapter.id,
                home=target_home,
                launcher=adapter.launcher,
                instruction_file=adapter.instruction_file,
                runtime_subdir=adapter.runtime_subdir,
                compat_managed_entries=adapter.compat_managed_entries,
                hooks=adapter.hooks,
            )
            return build_harness(spec)
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
    if not PATH_COMPONENT_PATTERN.match(value) or value in (".", ".."):
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
    hooks: Sequence[HarnessHookSpec],
) -> tuple[HarnessHook, ...]:
    """Normalize harness hook specifications with default file paths."""
    normalized: list[HarnessHook] = []
    for hook in hooks:
        match hook:
            case PackageBootstrapHook():
                manifest = (
                    hook.manifest_file
                    if hook.manifest_file is not None
                    else "packages.json"
                )
                settings = (
                    hook.settings_file
                    if hook.settings_file is not None
                    else "settings.json"
                )
                cache = (
                    hook.cache_subdir
                    if hook.cache_subdir is not None
                    else DEFAULT_PACKAGE_CACHE_SUBDIR
                )
                normalized.append(
                    PackageBootstrapHook(
                        manifest_file=manifest,
                        settings_file=settings,
                        cache_subdir=cache,
                    )
                )
            case ExtensionDepsHook():
                normalized.append(
                    ExtensionDepsHook(
                        root_dir=hook.root_dir,
                    )
                )
    return tuple(normalized)


__all__ = [
    "DEFAULT_INSTRUCTION_FILE",
    "DEFAULT_PACKAGE_CACHE_SUBDIR",
    "HARNESS_ADAPTERS",
    "INSTALL_TIMEOUT_MS",
    "INSTALL_TIMEOUT_SECONDS",
    "MANAGED_STATE_SUBDIR",
    "PATH_COMPONENT_PATTERN",
    "SKILLS_DST_DIR",
    "SKILLS_SOURCE_SUBDIR",
    "SOURCE_AGENT_FILE",
    "ExtensionDepsHook",
    "Harness",
    "HarnessAdapter",
    "HarnessHook",
    "HarnessHookSpec",
    "HarnessId",
    "HarnessLauncher",
    "HarnessLauncherSpec",
    "HarnessSpec",
    "HostPlatform",
    "PackageBootstrapHook",
    "RootEnvReadError",
    "SyncEnv",
    "assert_path_component",
    "build_harness",
    "decode_root_env",
    "discover_harnesses",
    "harness_instruction_file_name",
    "harness_instruction_target",
    "harness_managed_state_path",
    "harness_root",
    "harness_source_root",
    "is_directory",
    "load_root_env",
    "platform_from_process",
    "read_root_env_content",
    "supported_harness",
]
