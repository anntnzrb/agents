# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""npm package caching, version resolution, and launcher subprocess execution."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import platform
import re
import secrets
import shutil
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import TypeAdapter, ValidationError

from sync.core.harness import StaticReleaseLauncher
from sync.core.managed_tools import (
    download_release,
    extract_archive,
    supported_arch,
    sys_platform,
    verify_checksum,
)
from sync.core.release_manifest import fetch_static_release_manifest
from sync.runtime.errors import err, panic_message, warn
from sync.runtime.fs import rm_entry
from sync.runtime.lock import acquire_cache_lock, release_sync_lock
from sync.runtime.process import ProcessResult, RunProcessOptions, run_process

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from sync.core.harness import Harness, StaticRelease, SyncEnv
    from sync.core.release_manifest import FetchManifestFn, StaticReleaseAsset

__all__ = [
    "DEFAULT_LAUNCH_TIMEOUT_MS",
    "LauncherRuntime",
    "NpmCacheLayout",
    "NpmPackageSpec",
    "PreparePackageOptions",
    "PreparedNpmPackage",
    "PreparedStaticRelease",
    "ReleaseRuntime",
    "launch_harness",
    "launch_npm_package",
    "launch_static_release",
    "npm_cache_layout",
    "prepare_npm_package",
    "prepare_static_release",
]

DEFAULT_LAUNCH_TIMEOUT_MS: int = 120_000
COMPONENT_PATTERN: re.Pattern[str] = re.compile(r"^[A-Za-z0-9._-]+$")
PACKAGE_PATTERN: re.Pattern[str] = re.compile(
    r"^(?:@[A-Za-z0-9._~-]+/)?[A-Za-z0-9._~-]+$"
)
SEMVER_PATTERN: re.Pattern[str] = re.compile(r"^\d+\.\d+\.\d+(-[\w.]+)?(\+[\w.]+)?$")
RELEASE_VERSION_PATTERN: re.Pattern[str] = re.compile(r"^\d+(?:\.\d+)*$")
PACKAGE_KEY_LENGTH: int = 16
EXEC_PERM_MASK: int = 0o111
EXIT_TIMED_OUT: int = 124
RELEASE_VERSIONS_SUBDIR: str = "_versions"
RELEASE_CURRENT_LINK: str = "current"
RELEASE_PREVIOUS_LINK: str = "previous"
RELEASE_LOCK_FILE: str = "lock"
RELEASE_DISTRIBUTION: str = "curl-bash"
RELEASE_DISTRIBUTION_FILE: str = "distribution"
RELEASE_STAGE_PREFIX: str = ".stage-"
MAX_DETAIL_CHARS: int = 2000
_PACKAGE_MANIFEST = TypeAdapter(dict[str, object])


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


async def _install_staged_package(
    runner: Callable[[Sequence[str], RunProcessOptions], Awaitable[ProcessResult]],
    spec: NpmPackageSpec,
    resolved_version: str,
    stage_dir: str,
    timeout_ms: int,
) -> None:
    await asyncio.to_thread(Path(stage_dir).mkdir, parents=True, exist_ok=True)
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

    if await asyncio.to_thread(Path(version_dir).exists):
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
        _ = await asyncio.to_thread(Path(stage_dir).replace, version_dir)
    finally:
        await asyncio.to_thread(shutil.rmtree, stage_dir, ignore_errors=True)


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
    runtime = options.runtime
    resolver = (
        runtime.resolve_version
        if runtime is not None and runtime.resolve_version is not None
        else resolve_version
    )
    dist_tag = spec.dist_tag if spec.dist_tag is not None else "latest"
    try:
        resolved_version = validate_resolved_version(
            await resolver(spec.package, dist_tag, timeout_ms)
        )
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
    await asyncio.to_thread(
        Path(layout.versions_dir).mkdir, parents=True, exist_ok=True
    )

    lock = await acquire_cache_lock(layout.tool_cache, layout.lock_file, timeout_ms)
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


@dataclass(frozen=True, slots=True)
class ReleaseRuntime:
    """Optional pluggable callbacks for static release resolution and execution."""

    arch: str | None = None
    platform: str | None = None
    fetch_manifest: FetchManifestFn | None = None
    download: Callable[[str, str, int], None] | None = None
    extract: Callable[[str, str, int], None] | None = None
    run: (
        Callable[[Sequence[str], RunProcessOptions], Awaitable[ProcessResult]] | None
    ) = None


@dataclass(frozen=True, slots=True)
class PreparedStaticRelease:
    """Result of preparing a static release executable."""

    version: str
    executable: str


def _release_platform_key(runtime: ReleaseRuntime | None) -> str:
    platform_name = (
        runtime.platform if runtime is not None and runtime.platform else sys_platform()
    )
    arch_source = (
        runtime.arch if runtime is not None and runtime.arch else platform.machine()
    )
    return f"{platform_name}-{supported_arch(arch_source)}"


def _promote_release_stage(
    stage_dir: Path,
    version_dir: Path,
    archive_path: Path,
) -> None:
    archive_path.unlink(missing_ok=True)
    _ = (stage_dir / RELEASE_DISTRIBUTION_FILE).write_text(
        f"{RELEASE_DISTRIBUTION}\n", encoding="utf-8"
    )
    if version_dir.exists() or version_dir.is_symlink():
        rm_entry(str(version_dir))
    _ = stage_dir.replace(version_dir)


async def _install_static_release(
    version: str,
    asset: StaticReleaseAsset,
    version_dir: Path,
    timeout_ms: int,
    runtime: ReleaseRuntime | None,
) -> None:
    versions_dir = version_dir.parent
    stage_dir = Path(
        await asyncio.to_thread(
            tempfile.mkdtemp, prefix=RELEASE_STAGE_PREFIX, dir=str(versions_dir)
        )
    )
    try:
        archive_path = stage_dir / f"release-{version}.tar.gz"
        download = (
            runtime.download
            if runtime is not None and runtime.download is not None
            else download_release
        )
        await asyncio.to_thread(download, asset.url, str(archive_path), timeout_ms)
        await asyncio.to_thread(verify_checksum, str(archive_path), asset.sha256)
        extract = (
            runtime.extract
            if runtime is not None and runtime.extract is not None
            else extract_archive
        )
        await asyncio.to_thread(extract, str(archive_path), str(stage_dir), timeout_ms)
        await asyncio.to_thread(
            _promote_release_stage, stage_dir, version_dir, archive_path
        )
    finally:
        shutil.rmtree(stage_dir, ignore_errors=True)


def _update_release_links(versions_dir: Path, version_dir: Path) -> None:
    current_link = str(versions_dir / RELEASE_CURRENT_LINK)
    previous_link = str(versions_dir / RELEASE_PREVIOUS_LINK)
    expected_target = os.path.relpath(str(version_dir), str(versions_dir))
    current_target = read_link_target(current_link)
    if current_target == expected_target:
        return
    if current_target is not None:
        replace_link(previous_link, current_target)
    replace_link(current_link, expected_target)


def _prune_release_versions(versions_dir: Path) -> None:
    keep: set[str] = set()
    for link_path in (
        str(versions_dir / RELEASE_CURRENT_LINK),
        str(versions_dir / RELEASE_PREVIOUS_LINK),
    ):
        target = read_link_target(link_path)
        if target:
            keep.add(Path(target).name)
    try:
        entries = list(versions_dir.iterdir())
    except OSError:
        return
    for entry in entries:
        if entry.name in keep or entry.is_symlink():
            continue
        if not entry.is_dir() or not RELEASE_VERSION_PATTERN.match(entry.name):
            continue
        shutil.rmtree(entry, ignore_errors=True)


def _sync_release_man_pages(
    release: StaticRelease,
    home: str,
    version_dir: Path,
    install_root: Path,
) -> None:
    if release.man_segments is None or release.man_dest_segments is None:
        return
    source_dir = version_dir.joinpath(*release.man_segments)
    if not source_dir.is_dir():
        return
    dest_dir = Path(home).joinpath(*release.man_dest_segments)
    names = {entry.name for entry in source_dir.iterdir() if entry.is_file()}
    managed_prefix = str(install_root / RELEASE_VERSIONS_SUBDIR) + os.sep
    dest_dir.mkdir(parents=True, exist_ok=True)
    for entry in list(dest_dir.iterdir()):
        if entry.name in names or not entry.is_symlink():
            continue
        try:
            target = str(entry.readlink())
        except OSError:
            continue
        if target.startswith(managed_prefix):
            entry.unlink(missing_ok=True)

    current_dir = install_root / RELEASE_VERSIONS_SUBDIR / RELEASE_CURRENT_LINK
    for name in sorted(names):
        link_target = str(current_dir.joinpath(*release.man_segments) / name)
        link_path = dest_dir / name
        if link_path.is_symlink() and str(link_path.readlink()) == link_target:
            continue
        try:
            replace_link(str(link_path), link_target)
        except (OSError, RuntimeError) as error:
            warn(f"man page conflict at {link_path}: {panic_message(error)}")


def _current_prepared_release(
    release: StaticRelease,
    home: str,
) -> PreparedStaticRelease | None:
    versions_dir = Path(home).joinpath(
        *release.install_segments, RELEASE_VERSIONS_SUBDIR
    )
    try:
        if not (versions_dir / RELEASE_CURRENT_LINK).is_symlink():
            return None
        version_dir = (versions_dir / RELEASE_CURRENT_LINK).resolve(strict=True)
        executable = version_dir.joinpath(*release.executable_segments).resolve(
            strict=True
        )
        if (
            version_dir.parent == versions_dir.resolve()
            and RELEASE_VERSION_PATTERN.fullmatch(version_dir.name)
            and executable.is_relative_to(version_dir)
            and is_executable(str(executable))
        ):
            return PreparedStaticRelease(version_dir.name, str(executable))
    except (OSError, RuntimeError):
        return None
    return None


async def prepare_static_release(
    release: StaticRelease,
    home: str,
    timeout_ms: int,
    runtime: ReleaseRuntime | None = None,
) -> PreparedStaticRelease:
    """Resolve, verify, cache, and link a static release executable."""
    try:
        return await _prepare_static_release_locked(release, home, timeout_ms, runtime)
    except (OSError, RuntimeError, ValueError, TypeError) as error:
        cached = await asyncio.to_thread(_current_prepared_release, release, home)
        if cached is None:
            raise
        detail = panic_message(error)
        warn(f"static release lookup failed ({detail}); using cached {cached.version}")
        return cached


async def _prepare_static_release_locked(
    release: StaticRelease,
    home: str,
    timeout_ms: int,
    runtime: ReleaseRuntime | None,
) -> PreparedStaticRelease:
    fetch = runtime.fetch_manifest if runtime is not None else None
    manifest = await asyncio.to_thread(
        fetch_static_release_manifest, release.manifest_url, timeout_ms, fetch
    )

    platform_key = _release_platform_key(runtime)
    target = release.targets.get(platform_key)
    if target is None:
        message = f"static release has no target for {platform_key}"
        raise RuntimeError(message)
    asset = manifest.platforms.get(target)
    if asset is None:
        message = f"static release {manifest.version} missing platform {target}"
        raise RuntimeError(message)

    install_root = Path(home).joinpath(*release.install_segments)
    versions_dir = install_root / RELEASE_VERSIONS_SUBDIR
    version_dir = versions_dir / manifest.version
    executable = version_dir.joinpath(*release.executable_segments)
    await asyncio.to_thread(versions_dir.mkdir, parents=True, exist_ok=True)

    lock = await acquire_cache_lock(
        str(install_root), str(install_root / RELEASE_LOCK_FILE), timeout_ms
    )
    try:
        if not is_executable(str(executable)):
            await _install_static_release(
                manifest.version, asset, version_dir, timeout_ms, runtime
            )
        _update_release_links(versions_dir, version_dir)
        _prune_release_versions(versions_dir)
        await asyncio.to_thread(
            _sync_release_man_pages, release, home, version_dir, install_root
        )
        if not is_executable(str(executable)):
            message = (
                f"static release {manifest.version} has no executable {executable}"
            )
            raise RuntimeError(message)
    finally:
        release_sync_lock(lock)

    return PreparedStaticRelease(version=manifest.version, executable=str(executable))


async def launch_static_release(
    sync_env: SyncEnv,
    launcher: StaticReleaseLauncher,
    args: Sequence[str],
    env: dict[str, str] | None,
    runtime: ReleaseRuntime | None = None,
) -> int:
    """Prepare and execute a static release harness with forwarded arguments."""
    prepared = await prepare_static_release(
        launcher.release, sync_env.home, sync_env.install_timeout_ms, runtime
    )
    runner = (
        runtime.run if runtime is not None and runtime.run is not None else run_process
    )
    result = await runner(
        [prepared.executable, *args],
        RunProcessOptions(
            stdio="inherit",
            env=env,
        ),
    )
    if result.timed_out or result.output_limited:
        err(f"{launcher.bin} launch timed out")
        return EXIT_TIMED_OUT
    return result.exit_code


async def launch_harness(
    sync_env: SyncEnv,
    harness: Harness,
    args: Sequence[str],
    runtime: LauncherRuntime | None = None,
    release_runtime: ReleaseRuntime | None = None,
) -> int:
    """Launch a harness executable, resolving environment variables and cache."""
    # Parent environment beats .env defaults; explicit adapter values win over both.
    merged = {k: v for k, v in sync_env.root_env.items() if k not in os.environ}
    launcher = harness.launcher
    if launcher.env is not None:
        merged.update(launcher.env)

    if isinstance(launcher, StaticReleaseLauncher):
        return await launch_static_release(
            sync_env, launcher, args, merged or None, release_runtime
        )

    spec = NpmPackageSpec(
        tool=harness.source_name,
        package=launcher.package,
        bin=launcher.bin,
        dist_tag=launcher.dist_tag,
        smoke_check=launcher.smoke_check,
        env=merged or None,
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
        _ = temp_path.replace(link_p)
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
    message = (
        f"latest {spec.package}@{dist_tag} unavailable ({detail}); "
        f"using cached {spec.tool}@{version}"
    )
    warn(message)


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
        with manifest_path.open(encoding="utf-8") as f:
            data: object = json.load(f)  # pyright: ignore[reportAny]
        raw_dict = _PACKAGE_MANIFEST.validate_python(data)
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
