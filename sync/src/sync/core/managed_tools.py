# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Managed external binary downloads, releases, and tool preparation."""

from __future__ import annotations

import concurrent.futures
import hashlib
import inspect
import json
import os
import platform
import re
import shutil
import stat
import tarfile
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, cast

if TYPE_CHECKING:
    from sync.core.harness import SyncEnv

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from sync.core.cliproxy_deployment import (
    CLI_PROXY_SOURCE_DIR,
    CliProxyDeployment,
    cliproxy_models_url,
)
from sync.runtime.errors import panic_message, warn
from sync.runtime.jsonc import strip_jsonc

TOOL_NAME = "cliproxyapi"
RELEASE_FILE = "release.json"
COMPONENT_PATTERN = r"^[A-Za-z0-9._-]+$"
ASSET_NAME_PATTERN = r"^[A-Za-z0-9._-]+(?:[A-Za-z0-9._-]|\{version\})*$"
REPOSITORY_PATTERN = r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$"
SHA256_PATTERN = r"^[a-f0-9]{64}$"
LATEST_VERSION = "latest"
VERSION_PLACEHOLDER = "{version}"
DEFAULT_CHECKSUMS_FILE = "checksums.txt"
GITHUB_BASE = "https://github.com"
REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})
HEX_DIGITS = frozenset("0123456789abcdef")
CHECKSUM_FIELD_COUNT = 2
SHA256_HEX_LENGTH = 64

DEFAULT_HEALTH_TIMEOUT_MS = 500
DEFAULT_INSTALL_TIMEOUT_MS = 120_000
EXECUTABLE_MODE = 0o755
RECEIPT_INDENT = 2
HTTP_OK = 200
MS_PER_SECOND = 1000.0
_TIMEOUT_POSITIONAL_ARITY = 2


class ReleaseAsset(BaseModel):
    """Release asset metadata for a platform.

    ``name`` may embed the ``{version}`` placeholder for latest-tracking
    manifests. ``sha256`` pins the archive; when omitted, the checksum is read
    from the release's checksums asset at install time.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    name: str = Field(pattern=ASSET_NAME_PATTERN)
    sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)


class ReleaseManifest(BaseModel):
    """Release manifest describing a downloadable external tool.

    ``version`` may be ``"latest"`` to track the newest GitHub release; the
    concrete version is resolved at install time and recorded in the receipt.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    repository: str = Field(pattern=REPOSITORY_PATTERN)
    version: str = Field(pattern=COMPONENT_PATTERN)
    binary: str = Field(pattern=COMPONENT_PATTERN)
    assets: dict[str, ReleaseAsset]
    checksums: str = Field(default=DEFAULT_CHECKSUMS_FILE, pattern=COMPONENT_PATTERN)


@dataclass(frozen=True)
class PreparedManagedTool:
    """Metadata for an installed and verified managed tool."""

    name: str
    command: str
    executable: str
    version: str
    config_path: str


type DownloadFn = Callable[[str, str, int], None]
type ExtractFn = Callable[[str, str, str, int], None]
type ResolveVersionFn = Callable[[str, int], str]
type FetchChecksumsFn = Callable[[str, int], dict[str, str]]
type FetchImpl = Callable[..., object]


@dataclass(frozen=True)
class ManagedToolRuntime:
    """Optional overrides for managed tool installation runtime."""

    arch: str | None = None
    cache_home: str | None = None
    download: DownloadFn | None = None
    extract: ExtractFn | None = None
    resolve_version: ResolveVersionFn | None = None
    fetch_checksums: FetchChecksumsFn | None = None


@dataclass(frozen=True)
class ManagedToolInstallContext:
    """Resolved inputs shared by managed tool install helpers."""

    manifest: ReleaseManifest
    platform_key: str
    executable_name: str
    cache_home: str
    config_path: str
    timeout_ms: int
    runtime: ManagedToolRuntime | None


@dataclass(frozen=True)
class ManagedToolRelease:
    """A specific release archive staged for installation."""

    version: str
    asset_name: str
    sha256: str
    install_dir: Path
    receipt: str


def supported_arch(arch: str) -> str:
    """Normalize and validate target machine architecture.

    Returns 'arm64' or 'x64', or raises RuntimeError for unsupported architectures.
    """
    normalized = arch.strip().lower()
    if normalized in ("arm64", "aarch64"):
        return "arm64"
    if normalized in ("x64", "x86_64", "amd64"):
        return "x64"
    message = f"unsupported architecture: {arch}"
    raise RuntimeError(message)


def _current_arch() -> str:
    """Detect current system architecture."""
    return supported_arch(platform.machine())


def read_manifest(manifest_path: str | Path) -> ReleaseManifest:
    """Read and validate a tool release manifest from disk."""
    path = Path(manifest_path)
    try:
        raw_text = path.read_text(encoding="utf-8")
        clean_text = strip_jsonc(raw_text)
        parsed: object = json.loads(clean_text)  # pyright: ignore[reportAny]
    except (OSError, ValueError, TypeError) as exc:
        message = f"parse {path} ({panic_message(exc)})"
        raise RuntimeError(message) from exc

    try:
        return ReleaseManifest.model_validate(parsed)
    except ValidationError as exc:
        message = f"invalid release manifest: {path}"
        raise RuntimeError(message) from exc


def download_release(url: str, destination: str | Path, timeout_ms: int) -> None:
    """Download a remote release archive to a local file destination."""
    dest_path = Path(destination)
    timeout_sec = timeout_ms / MS_PER_SECOND
    try:
        response = httpx.get(url, timeout=timeout_sec, follow_redirects=True)
    except (httpx.HTTPError, OSError, ValueError, TypeError) as exc:
        message = f"download failed ({panic_message(exc)})"
        raise RuntimeError(message) from exc

    if response.status_code != HTTP_OK:
        message = f"download failed with HTTP {response.status_code}"
        raise RuntimeError(message)

    try:
        _ = dest_path.write_bytes(response.content)
    except OSError as exc:
        message = f"download failed ({panic_message(exc)})"
        raise RuntimeError(message) from exc


def _do_extract_tar(
    archive_path: Path,
    dest_path: Path,
    entry_name: str | None,
) -> None:
    with tarfile.open(archive_path, mode="r:*") as tar:
        if entry_name is None:
            tar.extractall(path=dest_path, filter="data")
        else:
            member = tar.getmember(entry_name)
            tar.extract(member, path=dest_path, filter="data")


def _extract_with_timeout(
    archive_path: Path,
    dest_path: Path,
    entry_name: str | None,
    timeout_ms: int,
) -> None:
    timeout_sec = max(0.0, timeout_ms / MS_PER_SECOND)
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(
            _do_extract_tar,
            archive_path,
            dest_path,
            entry_name,
        )
        future.result(timeout=timeout_sec)
    except (TimeoutError, concurrent.futures.TimeoutError) as exc:
        message = "archive extraction timed out"
        raise TimeoutError(message) from exc
    except KeyError as exc:
        message = f"archive extraction failed: missing entry {entry_name}"
        raise RuntimeError(message) from exc
    except (OSError, tarfile.TarError) as exc:
        message = f"archive extraction failed: {panic_message(exc)}"
        raise RuntimeError(message) from exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def extract_release(
    archive: str | Path,
    destination: str | Path,
    entry_name: str,
    timeout_ms: int,
) -> None:
    """Extract a single entry from a tarball archive to destination directory."""
    _extract_with_timeout(Path(archive), Path(destination), entry_name, timeout_ms)


def extract_archive(
    archive: str | Path,
    destination: str | Path,
    timeout_ms: int,
) -> None:
    """Extract every entry from a tarball archive into a destination directory."""
    _extract_with_timeout(Path(archive), Path(destination), None, timeout_ms)


def verify_checksum(archive: str | Path, expected: str) -> None:
    """Verify SHA-256 checksum of an archive file against expected lowerhex."""
    archive_path = Path(archive)
    content = archive_path.read_bytes()
    actual = hashlib.sha256(content).hexdigest().lower()
    if actual != expected.lower():
        message = f"checksum mismatch for {archive_path.name}"
        raise RuntimeError(message)


def installed_tool_matches(
    executable: Path,
    receipt_path: Path,
    receipt: str,
) -> bool:
    """Check if tool executable exists, is executable, and receipt matches."""
    if not _is_executable_file(executable):
        return False
    try:
        return receipt_path.read_text(encoding="utf-8") == receipt
    except (OSError, UnicodeDecodeError):
        return False


def _is_executable_file(path: Path) -> bool:
    """Return True when path is a regular file with an executable bit."""
    try:
        stat_info = path.stat()
    except OSError:
        return False
    return stat.S_ISREG(stat_info.st_mode) and (stat_info.st_mode & 0o111) != 0


def parse_checksums(text: str) -> dict[str, str]:
    """Parse a ``checksums.txt`` payload into a filename to sha256 mapping."""
    entries: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) != CHECKSUM_FIELD_COUNT:
            continue
        digest, name = parts
        normalized = digest.lower()
        if len(normalized) != SHA256_HEX_LENGTH or any(
            char not in HEX_DIGITS for char in normalized
        ):
            continue
        entries[name] = normalized
    return entries


def fetch_checksums(url: str, timeout_ms: int) -> dict[str, str]:
    """Download and parse a release checksums file."""
    timeout_sec = timeout_ms / MS_PER_SECOND
    try:
        response = httpx.get(url, timeout=timeout_sec, follow_redirects=True)
    except (httpx.HTTPError, OSError, ValueError, TypeError) as exc:
        message = f"checksums download failed ({panic_message(exc)})"
        raise RuntimeError(message) from exc

    if response.status_code != HTTP_OK:
        message = f"checksums download failed with HTTP {response.status_code}"
        raise RuntimeError(message)

    return parse_checksums(response.text)


def resolve_latest_version(repository: str, timeout_ms: int) -> str:
    """Resolve the newest release tag for a GitHub repository.

    Uses the ``/releases/latest`` redirect instead of the GitHub API so the
    lookup is not rate-limited on shared or frequently synced hosts.
    """
    url = f"{GITHUB_BASE}/{repository}/releases/latest"
    timeout_sec = timeout_ms / MS_PER_SECOND
    try:
        response = httpx.get(url, timeout=timeout_sec, follow_redirects=False)
    except (httpx.HTTPError, OSError, ValueError, TypeError) as exc:
        message = f"release resolution failed ({panic_message(exc)})"
        raise RuntimeError(message) from exc

    if response.status_code not in REDIRECT_STATUS_CODES:
        message = f"release resolution failed with HTTP {response.status_code}"
        raise RuntimeError(message)

    locations = response.headers.get_list("location")
    tag = locations[0].rstrip("/").rsplit("/", maxsplit=1)[-1] if locations else ""
    tag = tag.removeprefix("v")
    if not tag or re.fullmatch(COMPONENT_PATTERN, tag) is None:
        message = f"release resolution returned unusable tag {tag!r}"
        raise RuntimeError(message)
    return tag


def _render_asset_name(template: str, version: str) -> str:
    """Render the ``{version}`` placeholder in a release asset name."""
    name = template.replace(VERSION_PLACEHOLDER, version)
    if VERSION_PLACEHOLDER in name or re.fullmatch(COMPONENT_PATTERN, name) is None:
        message = f"invalid release asset name: {name!r}"
        raise RuntimeError(message)
    return name


def _render_receipt(payload: dict[str, str]) -> str:
    return f"{json.dumps(payload, indent=RECEIPT_INDENT)}\n"


def installed_receipt_matches(
    executable: Path,
    receipt_path: Path,
    expected: dict[str, str],
) -> bool:
    """Check an installed tool against receipt fields that exclude the checksum."""
    if not _is_executable_file(executable):
        return False
    try:
        parsed = cast("object", json.loads(receipt_path.read_text(encoding="utf-8")))
    except (OSError, UnicodeDecodeError, ValueError):
        return False
    if not isinstance(parsed, dict):
        return False
    payload = cast("dict[str, object]", parsed)
    return all(payload.get(key) == value for key, value in expected.items())


def _version_sort_key(version: str) -> tuple[int, ...]:
    """Order versions by their numeric components; non-numeric parts are ignored."""
    return tuple(int(match.group()) for match in re.finditer(r"\d+", version))


def _newest_cached_install(
    cache_home: str,
    platform_key: str,
    repository: str,
) -> tuple[str, Path, dict[str, object]] | None:
    """Return the newest cached install for a repository and platform, if any."""
    versions_root = Path(cache_home) / "github-tools" / TOOL_NAME / "versions"
    if not versions_root.is_dir():
        return None
    best: tuple[tuple[int, ...], str, Path, dict[str, object]] | None = None
    for version_dir in versions_root.iterdir():
        receipt_path = version_dir / platform_key / "receipt.json"
        try:
            parsed = cast(
                "object", json.loads(receipt_path.read_text(encoding="utf-8"))
            )
        except (OSError, UnicodeDecodeError, ValueError):
            continue
        if not isinstance(parsed, dict):
            continue
        payload = cast("dict[str, object]", parsed)
        if payload.get("repository") != repository:
            continue
        version = payload.get("version")
        if not isinstance(version, str) or not version:
            continue
        key = _version_sort_key(version)
        if best is None or key > best[0]:
            best = (key, version, version_dir, payload)
    if best is None:
        return None
    _, version, version_dir, payload = best
    return version, version_dir, payload


def _resolve_cache_home(
    sync_env: SyncEnv,
    runtime: ManagedToolRuntime | None,
) -> str:
    """Resolve cache directory root from runtime override, env, or default."""
    if runtime is not None and runtime.cache_home is not None:
        return runtime.cache_home
    env_cache = os.environ.get("XDG_CACHE_HOME")
    if env_cache:
        return env_cache
    home = getattr(sync_env, "home", str(Path.home()))
    return str(Path(home) / ".cache")


def _ensure_staged_executable(stage_path: Path, executable_name: str) -> None:
    staged_executable = stage_path / executable_name
    if not staged_executable.is_file():
        message = f"CLIProxyAPI archive is missing {executable_name}"
        raise RuntimeError(message)
    staged_executable.chmod(EXECUTABLE_MODE)


def _resolve_declared_version(
    manifest: ReleaseManifest,
    runtime: ManagedToolRuntime | None,
    timeout_ms: int,
) -> str:
    """Return the manifest version, resolving ``latest`` against GitHub."""
    if manifest.version != LATEST_VERSION:
        return manifest.version
    resolve = (
        runtime.resolve_version
        if runtime and runtime.resolve_version
        else resolve_latest_version
    )
    return resolve(manifest.repository, timeout_ms)


def _cached_tool(
    context: ManagedToolInstallContext,
    error: Exception,
) -> PreparedManagedTool | None:
    """Reuse the newest cached install when the latest lookup fails."""
    cached = _newest_cached_install(
        context.cache_home,
        context.platform_key,
        context.manifest.repository,
    )
    if cached is None:
        return None
    cached_version, cached_dir, _payload = cached
    executable = cached_dir / context.platform_key / context.executable_name
    if not _is_executable_file(executable):
        return None
    detail = panic_message(error)
    warn(f"CLIProxyAPI latest lookup failed; using cached {cached_version} ({detail})")
    return PreparedManagedTool(
        name=TOOL_NAME,
        command=context.executable_name,
        executable=str(executable),
        version=cached_version,
        config_path=context.config_path,
    )


def _resolve_checksum(
    context: ManagedToolInstallContext,
    asset_name: str,
    resolved_version: str,
) -> str:
    """Resolve an asset checksum from the release checksums file."""
    checksums_url = (
        f"{GITHUB_BASE}/{context.manifest.repository}/releases/download/"
        f"v{resolved_version}/{context.manifest.checksums}"
    )
    fetch_fn = (
        context.runtime.fetch_checksums
        if context.runtime and context.runtime.fetch_checksums
        else fetch_checksums
    )
    try:
        entries = fetch_fn(checksums_url, context.timeout_ms)
    except Exception as exc:
        message = f"install CLIProxyAPI {resolved_version} ({panic_message(exc)})"
        raise RuntimeError(message) from exc
    sha256 = entries.get(asset_name)
    if sha256 is None:
        message = (
            f"install CLIProxyAPI {resolved_version} (checksums missing {asset_name})"
        )
        raise RuntimeError(message)
    return sha256


def _cached_install_matches(
    executable: Path,
    receipt_path: Path,
    identity: dict[str, str],
    sha256: str | None,
) -> bool:
    """Check an installed tool, comparing the checksum only when pinned."""
    if sha256 is not None:
        return installed_tool_matches(
            executable,
            receipt_path,
            _render_receipt({**identity, "sha256": sha256}),
        )
    return installed_receipt_matches(executable, receipt_path, identity)


def _install_verified_archive(
    context: ManagedToolInstallContext,
    release: ManagedToolRelease,
) -> None:
    """Download, verify, extract, and stage a release archive."""
    install_dir = release.install_dir
    if install_dir.exists():
        shutil.rmtree(install_dir, ignore_errors=True)
    install_dir.parent.mkdir(parents=True, exist_ok=True)
    stage_dir = tempfile.mkdtemp(prefix=".stage.", dir=str(install_dir.parent))
    stage_path = Path(stage_dir)
    try:
        archive_path = stage_path / release.asset_name
        url = (
            f"{GITHUB_BASE}/{context.manifest.repository}/releases/download/"
            f"v{release.version}/{release.asset_name}"
        )
        download_fn = (
            context.runtime.download
            if context.runtime and context.runtime.download
            else download_release
        )
        download_fn(url, str(archive_path), context.timeout_ms)
        verify_checksum(archive_path, release.sha256)
        extract_fn = (
            context.runtime.extract
            if context.runtime and context.runtime.extract
            else extract_release
        )
        extract_fn(
            str(archive_path),
            str(stage_path),
            context.executable_name,
            context.timeout_ms,
        )
        archive_path.unlink(missing_ok=True)
        _ensure_staged_executable(stage_path, context.executable_name)
        _ = (stage_path / "receipt.json").write_text(release.receipt, encoding="utf-8")
        _ = stage_path.replace(install_dir)
    except Exception as exc:
        shutil.rmtree(stage_dir, ignore_errors=True)
        message = f"install CLIProxyAPI {release.version} ({panic_message(exc)})"
        raise RuntimeError(message) from exc


def prepare_cli_proxy(
    sync_env: SyncEnv,
    manifest_path: str | Path,
    runtime: ManagedToolRuntime | None = None,
) -> PreparedManagedTool:
    """Download, verify, extract, and stage the CLIProxyAPI tool binary.

    Manifests with ``version: "latest"`` resolve the newest GitHub release at
    install time; a cached install is reused when the lookup fails so offline
    syncs keep working with the last verified binary.
    """
    manifest = read_manifest(manifest_path)
    arch_candidate = runtime.arch if runtime and runtime.arch else None
    arch = supported_arch(arch_candidate) if arch_candidate else _current_arch()
    platform_name = getattr(sync_env, "platform", sys_platform())
    platform_key = f"{platform_name}-{arch}"
    asset = manifest.assets.get(platform_key)
    if asset is None:
        message = f"CLIProxyAPI has no release asset for {platform_key}"
        raise RuntimeError(message)

    executable_name = manifest.binary
    cache_home = _resolve_cache_home(sync_env, runtime)
    home = getattr(sync_env, "home", str(Path.home()))
    config_path = str(Path(home) / ".cli-proxy-api" / "config.yaml")
    timeout_ms = getattr(
        sync_env,
        "install_timeout_ms",
        getattr(sync_env, "installTimeoutMs", DEFAULT_INSTALL_TIMEOUT_MS),
    )

    context = ManagedToolInstallContext(
        manifest=manifest,
        platform_key=platform_key,
        executable_name=executable_name,
        cache_home=cache_home,
        config_path=config_path,
        timeout_ms=timeout_ms,
        runtime=runtime,
    )

    try:
        resolved_version = _resolve_declared_version(manifest, runtime, timeout_ms)
    except Exception as exc:
        cached = _cached_tool(context, exc)
        if cached is None:
            raise
        return cached

    asset_name = _render_asset_name(asset.name, resolved_version)
    install_dir = (
        Path(cache_home)
        / "github-tools"
        / TOOL_NAME
        / "versions"
        / resolved_version
        / platform_key
    )
    executable = install_dir / executable_name
    receipt_path = install_dir / "receipt.json"
    identity = {
        "repository": manifest.repository,
        "version": resolved_version,
        "asset": asset_name,
    }

    if not _cached_install_matches(executable, receipt_path, identity, asset.sha256):
        sha256 = (
            asset.sha256
            if asset.sha256 is not None
            else _resolve_checksum(context, asset_name, resolved_version)
        )
        receipt = _render_receipt({**identity, "sha256": sha256})
        release = ManagedToolRelease(
            version=resolved_version,
            asset_name=asset_name,
            sha256=sha256,
            install_dir=install_dir,
            receipt=receipt,
        )
        _install_verified_archive(context, release)

    return PreparedManagedTool(
        name=TOOL_NAME,
        command=executable_name,
        executable=str(executable),
        version=resolved_version,
        config_path=config_path,
    )


def sys_platform() -> str:
    """Return system platform identifier matching host platform."""
    if platform.system().lower() == "darwin":
        return "darwin"
    return "linux"


def prepare_managed_tools(
    sync_env: SyncEnv,
    runtime: ManagedToolRuntime | None = None,
) -> list[PreparedManagedTool]:
    """Prepare all managed tools defined in SSOT environment."""
    ssot_home = getattr(
        sync_env,
        "ssot_home",
        getattr(sync_env, "ssotHome", str(Path.home())),
    )
    manifest_path = Path(ssot_home) / CLI_PROXY_SOURCE_DIR / RELEASE_FILE
    if not manifest_path.exists():
        return []
    return [prepare_cli_proxy(sync_env, manifest_path, runtime)]


def _invoke_fetch(
    fetch_impl: FetchImpl,
    url: str,
    timeout_sec: float,
    timeout_ms: int,
) -> object:
    """Invoke fetch implementation with timeout according to its signature."""
    try:
        sig = inspect.signature(fetch_impl)
        params = list(sig.parameters.values())
        param_names = {p.name for p in params}
        has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params)
        if "timeout_ms" in param_names:
            return fetch_impl(url, timeout_ms=timeout_ms)
        if "timeout" in param_names or has_var_kw:
            return fetch_impl(url, timeout=timeout_sec)
        if len(params) >= _TIMEOUT_POSITIONAL_ARITY and params[1].kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ):
            return fetch_impl(url, timeout_sec)
        return fetch_impl(url)
    except (ValueError, TypeError):
        try:
            return fetch_impl(url, timeout=timeout_sec)
        except TypeError:
            return fetch_impl(url)


def is_cli_proxy_running(
    deployment: CliProxyDeployment,
    timeout_ms: int = DEFAULT_HEALTH_TIMEOUT_MS,
    fetch_impl: FetchImpl | None = None,
) -> bool:
    """Check if the CLIProxyAPI daemon is reachable via its health endpoint."""
    try:
        url = cliproxy_models_url(deployment)
        timeout_sec = timeout_ms / MS_PER_SECOND
        if fetch_impl is not None:
            _ = _invoke_fetch(fetch_impl, url, timeout_sec, timeout_ms)
        else:
            _ = httpx.get(url, timeout=timeout_sec)
    except Exception:
        return False
    else:
        return True
