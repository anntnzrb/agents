# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""npm package caching, version resolution, and launcher subprocess execution."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import TypeAdapter, ValidationError

from sync.runtime.errors import err, warn
from sync.runtime.lock import SyncLock, release_sync_lock, try_acquire_sync_lock
from sync.runtime.process import ProcessResult, RunProcessOptions, run_process

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from sync.core.harness import Harness, SyncEnv

__all__ = [
    "DEFAULT_LAUNCH_TIMEOUT_MS",
    "LauncherProcessResult",
    "LauncherRuntime",
    "NpmCacheLayout",
    "NpmPackageSpec",
    "PreparePackageOptions",
    "PreparedNpmPackage",
    "launch_harness",
    "launch_npm_package",
    "npm_cache_layout",
    "prepare_npm_package",
]

DEFAULT_LAUNCH_TIMEOUT_MS: int = 120_000
COMPONENT_PATTERN: re.Pattern[str] = re.compile(r"^[A-Za-z0-9._-]+$")
PACKAGE_PATTERN: re.Pattern[str] = re.compile(
    r"^(?:@[A-Za-z0-9._~-]+/)?[A-Za-z0-9._~-]+$"
)
SEMVER_PATTERN: re.Pattern[str] = re.compile(r"^\d+\.\d+\.\d+(-[\w.]+)?(\+[\w.]+)?$")
RETRY_SLEEP_SECONDS: float = 0.025
PACKAGE_KEY_LENGTH: int = 16
MILLISECONDS_PER_SECOND: float = 1000.0
EXEC_PERM_MASK: int = 0o111
EXIT_TIMED_OUT: int = 124
MAX_DETAIL_CHARS: int = 2000


@dataclass(frozen=True, slots=True)
class NpmPackageSpec:
    """Specification of an npm package executable."""

    tool: str
    package: str
    bin: str
    dist_tag: str | None = None
    smoke_check: str | None = None
    env: dict[str, str] | None = None


@dataclass(frozen=True, slots=True)
class NpmCacheLayout:
    """Directory and symlink layout for an npm-installed tool."""

    tool_cache: str
    versions_dir: str
    current_link: str
    previous_link: str
    lock_file: str


@dataclass(frozen=True, slots=True)
class PreparedNpmPackage:
    """Result of preparing and resolving an npm package executable."""

    layout: NpmCacheLayout
    resolved_version: str
    current_bin: str


@dataclass(frozen=True, slots=True)
class LauncherProcessResult:
    """Captured result of a launcher subprocess execution."""

    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool


@dataclass(frozen=True, slots=True)
class LauncherRuntime:
    """Optional pluggable callbacks for launcher resolution and execution."""

    resolve_version: Callable[[str, str, int], Awaitable[str]] | None = None
    run: (
        Callable[[Sequence[str], RunProcessOptions], Awaitable[ProcessResult]] | None
    ) = None


@dataclass(frozen=True, slots=True)
class PreparePackageOptions:
    """Options for preparing and caching an npm package."""

    home: str
    cache_home: str | None = None
    timeout_ms: int | None = None
    runtime: LauncherRuntime | None = None


def npm_cache_layout(
    home: str,
    spec: NpmPackageSpec,
    cache_home: str | None = None,
) -> NpmCacheLayout:
    """Compute the cache directories, symlinks, and lockfile for an npm tool."""
    require_component(spec.tool, "tool")
    resolved_cache = (
        cache_home or os.environ.get("XDG_CACHE_HOME") or str(Path(home) / ".cache")
    )
    tool_cache = str(Path(resolved_cache) / "npm-tools" / spec.tool)
    digest = hashlib.sha256(spec.package.encode("utf-8")).hexdigest()
    package_key = digest[:PACKAGE_KEY_LENGTH]
    package_cache = str(Path(tool_cache) / "packages" / package_key)
    return NpmCacheLayout(
        tool_cache=tool_cache,
        versions_dir=str(Path(package_cache) / "versions"),
        current_link=str(Path(package_cache) / "current"),
        previous_link=str(Path(package_cache) / "previous"),
        lock_file=str(Path(tool_cache) / "lock"),
    )


async def _resolve_package_version(
    layout: NpmCacheLayout,
    spec: NpmPackageSpec,
    options: PreparePackageOptions,
    timeout_ms: int,
    cached: tuple[str, str] | None,
) -> str | PreparedNpmPackage:
    runtime = options.runtime
    resolver = (
        runtime.resolve_version
        if (runtime is not None and runtime.resolve_version is not None)
        else resolve_version
    )
    dist_tag = spec.dist_tag if spec.dist_tag is not None else "latest"
    try:
        raw_version = await resolver(spec.package, dist_tag, timeout_ms)
        return validate_resolved_version(raw_version)
    except Exception as error:
        if cached is None:
            raise
        warn_using_cached_package(spec, cached[0], error)
        return PreparedNpmPackage(
            layout=layout,
            resolved_version=cached[0],
            current_bin=cached[1],
        )


async def _install_staged_package(
    runner: Callable[[Sequence[str], RunProcessOptions], Awaitable[ProcessResult]],
    spec: NpmPackageSpec,
    resolved_version: str,
    stage_dir: str,
    timeout_ms: int,
) -> None:
    await asyncio.to_thread(_create_dir, stage_dir)
    install_cmd = [
        "npm",
        "install",
        "--prefix",
        stage_dir,
        "--no-save",
        "--no-package-lock",
        "--no-audit",
        "--no-fund",
        "--loglevel=error",
        f"{spec.package}@{resolved_version}",
    ]
    install = await runner(
        install_cmd,
        RunProcessOptions(timeout_ms=timeout_ms, stdio="pipe"),
    )
    if install.timed_out or install.output_limited or install.exit_code != 0:
        detail = _detail_from_result(install)
        message = f"npm install failed: {detail}"
        raise RuntimeError(message)

    installed_bin = package_bin_path(stage_dir, spec.bin)
    if not is_executable(installed_bin):
        message = f"installed package has no executable bin: {spec.bin}"
        raise RuntimeError(message)
    if not installed_package_matches(stage_dir, spec, resolved_version):
        message = (
            f"installed package identity mismatch: {spec.package}@{resolved_version}"
        )
        raise RuntimeError(message)

    smoke_check = spec.smoke_check if spec.smoke_check is not None else "--version"
    if smoke_check != "-":
        smoke = await runner(
            [installed_bin, smoke_check],
            RunProcessOptions(
                cwd=stage_dir,
                timeout_ms=timeout_ms,
                stdio="pipe",
            ),
        )
        if smoke.timed_out or smoke.output_limited or smoke.exit_code != 0:
            detail = _detail_from_result(smoke)
            message = f"installed package smoke check failed: {detail}"
            raise RuntimeError(message)


async def _ensure_version_installed(
    layout: NpmCacheLayout,
    spec: NpmPackageSpec,
    resolved_version: str,
    options: PreparePackageOptions,
    timeout_ms: int,
) -> None:
    version_dir = str(Path(layout.versions_dir) / resolved_version)
    staged_bin = package_bin_path(version_dir, spec.bin)

    if is_executable(staged_bin):
        if not installed_package_matches(version_dir, spec, resolved_version):
            message = f"cached package identity mismatch: {resolved_version}"
            raise RuntimeError(message)
        return

    if await asyncio.to_thread(_path_exists, version_dir):
        message = f"cached package is incomplete: {resolved_version}"
        raise RuntimeError(message)

    runtime = options.runtime
    runner = (
        runtime.run
        if (runtime is not None and runtime.run is not None)
        else run_process
    )
    stage_name = f".stage-{os.getpid()}-{secrets.token_hex(4)}"
    stage_dir = str(Path(layout.versions_dir) / stage_name)
    try:
        await _install_staged_package(
            runner, spec, resolved_version, stage_dir, timeout_ms
        )
        await asyncio.to_thread(_replace_dir, stage_dir, version_dir)
    finally:
        await asyncio.to_thread(_cleanup_dir, stage_dir)


def _create_dir(path: str) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)


def _cleanup_dir(path: str) -> None:
    if Path(path).exists():
        shutil.rmtree(path, ignore_errors=True)


def _replace_dir(src: str, dest: str) -> None:
    Path(src).replace(dest)


def _path_exists(path: str) -> bool:
    return Path(path).exists()


def _validate_current_bin(bin_path: str, bin_name: str) -> None:
    if not is_executable(bin_path):
        message = f"current package has no executable bin: {bin_name}"
        raise RuntimeError(message)


async def _prepare_locked_package(
    layout: NpmCacheLayout,
    spec: NpmPackageSpec,
    options: PreparePackageOptions,
    timeout_ms: int,
) -> PreparedNpmPackage:
    cached = current_cached_package(layout, spec)
    try:
        resolved = await _resolve_package_version(
            layout, spec, options, timeout_ms, cached
        )
        if isinstance(resolved, PreparedNpmPackage):
            return resolved
        resolved_version = resolved
        await _ensure_version_installed(
            layout, spec, resolved_version, options, timeout_ms
        )
        update_current_and_previous(layout, resolved_version)
        prune_versions(layout)

        current_bin = package_bin_path(layout.current_link, spec.bin)
        _validate_current_bin(current_bin, spec.bin)

        return PreparedNpmPackage(
            layout=layout,
            resolved_version=resolved_version,
            current_bin=current_bin,
        )
    except Exception as error:
        fallback = current_cached_package(layout, spec)
        if fallback is None:
            raise
        warn_using_cached_package(spec, fallback[0], error)
        return PreparedNpmPackage(
            layout=layout,
            resolved_version=fallback[0],
            current_bin=fallback[1],
        )


async def prepare_npm_package(
    spec: NpmPackageSpec,
    options: PreparePackageOptions,
) -> PreparedNpmPackage:
    """Prepare and cache a versioned npm package, returning the executable path."""
    validate_spec(spec)
    timeout_ms = (
        options.timeout_ms
        if options.timeout_ms is not None
        else DEFAULT_LAUNCH_TIMEOUT_MS
    )
    layout = npm_cache_layout(options.home, spec, options.cache_home)
    await asyncio.to_thread(_create_dir, layout.versions_dir)

    lock = await acquire_cache_lock(layout, timeout_ms)
    try:
        return await _prepare_locked_package(layout, spec, options, timeout_ms)
    finally:
        release_sync_lock(lock)


async def launch_npm_package(
    sync_env: SyncEnv,
    spec: NpmPackageSpec,
    args: Sequence[str],
    runtime: LauncherRuntime | None = None,
) -> int:
    """Prepare and execute an npm tool package with forwarded arguments."""
    prepared = await prepare_npm_package(
        spec,
        PreparePackageOptions(
            home=sync_env.home,
            timeout_ms=sync_env.install_timeout_ms,
            runtime=runtime,
        ),
    )
    runner = (
        runtime.run
        if (runtime is not None and runtime.run is not None)
        else run_process
    )
    cmd = [prepared.current_bin, *args]
    result = await runner(
        cmd,
        RunProcessOptions(
            stdio="inherit",
            env=spec.env,
        ),
    )
    if result.timed_out or result.output_limited:
        err(f"{spec.tool} launch timed out")
        return EXIT_TIMED_OUT
    return result.exit_code


async def launch_harness(
    sync_env: SyncEnv,
    harness: Harness,
    args: Sequence[str],
    runtime: LauncherRuntime | None = None,
) -> int:
    """Launch a harness executable, resolving environment variables and cache."""
    # Preserves TS env-merge precedence from launcher.ts:230-240:
    # 1. System environment (os.environ) wins over root_env (.env file).
    #    Root env variables that already exist in os.environ are filtered out.
    # 2. Adapter-specific launcher env (harness.launcher.env) overrides root_env.
    root_filtered = {k: v for k, v in sync_env.root_env.items() if k not in os.environ}
    merged: dict[str, str] = (
        {**root_filtered, **harness.launcher.env}
        if harness.launcher.env is not None
        else root_filtered
    )
    env = merged if len(merged) > 0 else None

    spec = NpmPackageSpec(
        tool=harness.source_name,
        package=harness.launcher.package,
        bin=harness.launcher.bin,
        dist_tag=harness.launcher.dist_tag,
        smoke_check=harness.launcher.smoke_check,
        env=env,
    )
    return await launch_npm_package(sync_env, spec, args, runtime)


async def resolve_version(
    package_name: str,
    dist_tag: str,
    timeout_ms: int,
) -> str:
    """Query npm registry for the version string matching a given dist-tag."""
    result = await run_process(
        ["npm", "view", f"{package_name}@{dist_tag}", "version"],
        RunProcessOptions(
            timeout_ms=timeout_ms,
            stdio="pipe",
        ),
    )
    if result.timed_out or result.output_limited or result.exit_code != 0:
        message = f"could not resolve {package_name}@{dist_tag}"
        raise RuntimeError(message)
    return result.stdout.replace("\r", "").replace("\n", "").strip()


async def acquire_cache_lock(
    layout: NpmCacheLayout,
    timeout_ms: int,
) -> SyncLock:
    """Acquire the exclusive lock for the npm tool cache directory."""
    started_at = time.monotonic()
    timeout_seconds = timeout_ms / MILLISECONDS_PER_SECOND
    while True:
        lock = try_acquire_sync_lock(layout.tool_cache, layout.lock_file)
        if lock is not None:
            return lock
        if time.monotonic() - started_at >= timeout_seconds:
            message = f"timed out waiting for npm cache lock: {layout.lock_file}"
            raise TimeoutError(message)
        await asyncio.sleep(RETRY_SLEEP_SECONDS)


def update_current_and_previous(layout: NpmCacheLayout, version: str) -> None:
    """Rotate symlinks: current to version, previous to old current."""
    version_dir = str(Path(layout.versions_dir) / version)
    expected_target = os.path.relpath(
        version_dir, str(Path(layout.current_link).parent)
    )
    current_target = read_link_target(layout.current_link)
    if current_target == expected_target:
        return
    if current_target is not None:
        replace_link(layout.previous_link, current_target)
    replace_link(layout.current_link, expected_target)


def replace_link(link_path: str, target: str) -> None:
    """Atomically replace or create a symlink pointing to target."""
    temp_path = Path(f"{link_path}.{os.getpid()}.tmp")
    if temp_path.is_symlink() or temp_path.is_file():
        temp_path.unlink()
    elif temp_path.is_dir():
        shutil.rmtree(temp_path, ignore_errors=True)
    link_p = Path(link_path)
    try:
        temp_path.symlink_to(target)
        try:
            lstat = link_p.lstat()
            if not stat.S_ISLNK(lstat.st_mode):
                message = f"unmanaged conflict at {link_path}"
                raise RuntimeError(message)
        except FileNotFoundError:
            pass
        temp_path.replace(link_p)
    except Exception:
        with contextlib.suppress(OSError):
            if temp_path.is_symlink() or temp_path.exists():
                temp_path.unlink()
        raise


def prune_versions(layout: NpmCacheLayout) -> None:
    """Remove versions not referenced by either current or previous links."""
    keep: set[str] = set()
    for link_path in (layout.current_link, layout.previous_link):
        target = read_link_target(link_path)
        if target:
            keep.add(Path(target).name)
    versions_path = Path(layout.versions_dir)
    if not versions_path.exists():
        return
    with contextlib.suppress(OSError):
        for entry_path in versions_path.iterdir():
            name = entry_path.name
            if name.startswith((".stage-", ".stage.")):
                continue
            if name in keep:
                continue
            if entry_path.is_dir() and not entry_path.is_symlink():
                shutil.rmtree(entry_path, ignore_errors=True)
            else:
                with contextlib.suppress(OSError):
                    entry_path.unlink()


def read_link_target(link_path: str) -> str | None:
    """Read symlink target path, raising if the path exists but is not a symlink."""
    path = Path(link_path)
    try:
        lstat = path.lstat()
    except FileNotFoundError:
        return None
    except OSError:
        return None

    if not stat.S_ISLNK(lstat.st_mode):
        if stat.S_ISREG(lstat.st_mode) or stat.S_ISDIR(lstat.st_mode):
            message = f"cache entry is not a symlink: {link_path}"
            raise RuntimeError(message)
        return None
    return str(path.readlink())


def package_bin_path(root: str, bin_name: str) -> str:
    """Return the expected binary executable path within node_modules/.bin."""
    return str(Path(root) / "node_modules" / ".bin" / bin_name)


def validate_spec(spec: NpmPackageSpec) -> None:
    """Validate that spec components adhere to safe identifier patterns."""
    require_component(spec.tool, "tool")
    require_component(spec.bin, "bin")
    dist_tag = spec.dist_tag if spec.dist_tag is not None else "latest"
    require_component(dist_tag, "dist-tag")
    if not PACKAGE_PATTERN.match(spec.package):
        message = f"invalid package: {spec.package}"
        raise ValueError(message)
    if (
        spec.smoke_check is not None
        and not spec.smoke_check.strip()
        and spec.smoke_check != "-"
    ):
        message = "missing smoke check"
        raise ValueError(message)


def validate_resolved_version(version: str) -> str:
    """Validate that version matches semantic versioning syntax."""
    if not SEMVER_PATTERN.match(version):
        message = f"invalid resolved version: {version}"
        raise ValueError(message)
    return version


def current_cached_package(
    layout: NpmCacheLayout,
    spec: NpmPackageSpec,
) -> tuple[str, str] | None:
    """Return the (version, bin_path) tuple for current cached package if healthy."""
    try:
        target = read_link_target(layout.current_link)
    except (OSError, RuntimeError, ValueError, TypeError):
        return None
    if not target:
        return None
    current_bin = package_bin_path(layout.current_link, spec.bin)
    if not is_executable(current_bin):
        return None
    version = Path(target).name
    if not installed_package_matches(layout.current_link, spec, version):
        return None
    return version, current_bin


def warn_using_cached_package(
    spec: NpmPackageSpec,
    version: str,
    error: object,
) -> None:
    """Log a warning that latest package is unavailable and cache is being used."""
    dist_tag = spec.dist_tag if spec.dist_tag is not None else "latest"
    detail = _detail_from_error(error)
    warn(
        f"latest {spec.package}@{dist_tag} unavailable ({detail}); "
        f"using cached {spec.tool}@{version}"
    )


def _detail_from_error(error: object) -> str:
    if isinstance(error, BaseException):
        msg = str(error)
        return msg or error.__class__.__name__
    return str(error)


def installed_package_matches(
    root: str,
    spec: NpmPackageSpec,
    version: str,
) -> bool:
    """Check if the installed package.json matches the expected name and version."""
    try:
        manifest_path = (
            Path(root)
            / "node_modules"
            / Path(*spec.package.split("/"))
            / "package.json"
        )
        if not manifest_path.exists():
            return False
        with manifest_path.open(encoding="utf-8") as f:
            data: object = json.load(f)
        raw_dict = TypeAdapter(dict[str, object]).validate_python(data)
        return bool(
            raw_dict.get("name") == spec.package and raw_dict.get("version") == version
        )
    except (OSError, json.JSONDecodeError, ValidationError, TypeError, ValueError):
        return False


def require_component(value: str, label: str) -> None:
    """Ensure a name component contains only safe characters and is not '.' or '..'."""
    if not value or not COMPONENT_PATTERN.match(value) or value in (".", ".."):
        message = f"invalid {label}: {value}"
        raise ValueError(message)


def is_executable(target_path: str) -> bool:
    """Check if the target path is an executable regular file."""
    try:
        st = Path(target_path).stat()
        return stat.S_ISREG(st.st_mode) and bool(st.st_mode & EXEC_PERM_MASK)
    except OSError:
        return False


def _detail_from_result(result: ProcessResult) -> str:
    detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
    if len(detail) > MAX_DETAIL_CHARS:
        return f"{detail[:MAX_DETAIL_CHARS]}…[truncated]"
    return detail
