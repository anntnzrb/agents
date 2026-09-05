# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Managed external binary downloads, releases, and tool preparation."""

from __future__ import annotations

import concurrent.futures
import hashlib
import inspect
import json
import os
import platform
import shutil
import stat
import tarfile
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sync.core.harness import SyncEnv

import httpx
from pydantic import BaseModel, ConfigDict, Field

from sync.core.cliproxy_deployment import (
    CLI_PROXY_SOURCE_DIR,
    CliProxyDeployment,
    cliproxy_models_url,
)
from sync.core.secret_template import strip_jsonc
from sync.runtime.errors import panic_message

TOOL_NAME = "cliproxyapi"
RELEASE_FILE = "release.json"
COMPONENT_PATTERN = r"^[A-Za-z0-9._-]+$"
REPOSITORY_PATTERN = r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$"
SHA256_PATTERN = r"^[a-f0-9]{64}$"

DEFAULT_HEALTH_TIMEOUT_MS = 500
DEFAULT_INSTALL_TIMEOUT_MS = 120_000
EXECUTABLE_MODE = 0o755
RECEIPT_INDENT = 2
HTTP_OK = 200
MS_PER_SECOND = 1000.0
_TIMEOUT_POSITIONAL_ARITY = 2


class ReleaseAsset(BaseModel):
    """Pinned release asset metadata for a platform."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=COMPONENT_PATTERN)
    sha256: str = Field(pattern=SHA256_PATTERN)


class ReleaseManifest(BaseModel):
    """Release manifest describing a downloadable external tool."""

    model_config = ConfigDict(extra="forbid")

    repository: str = Field(pattern=REPOSITORY_PATTERN)
    version: str = Field(pattern=COMPONENT_PATTERN)
    binary: str = Field(pattern=COMPONENT_PATTERN)
    assets: dict[str, ReleaseAsset]


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
type FetchImpl = Callable[..., object]


@dataclass(frozen=True)
class ManagedToolRuntime:
    """Optional overrides for managed tool installation runtime."""

    arch: str | None = None
    cache_home: str | None = None
    download: DownloadFn | None = None
    extract: ExtractFn | None = None


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
        parsed: object = json.loads(clean_text)
    except Exception as exc:
        message = f"parse {path} ({panic_message(exc)})"
        raise RuntimeError(message) from exc

    try:
        return ReleaseManifest.model_validate(parsed)
    except Exception as exc:
        message = f"invalid release manifest: {path}"
        raise RuntimeError(message) from exc


def download_release(url: str, destination: str | Path, timeout_ms: int) -> None:
    """Download a remote release archive to a local file destination."""
    dest_path = Path(destination)
    timeout_sec = timeout_ms / MS_PER_SECOND
    try:
        response = httpx.get(url, timeout=timeout_sec, follow_redirects=True)
    except Exception as exc:
        message = f"download failed ({panic_message(exc)})"
        raise RuntimeError(message) from exc

    if response.status_code != HTTP_OK:
        message = f"download failed with HTTP {response.status_code}"
        raise RuntimeError(message)

    try:
        dest_path.write_bytes(response.content)
    except OSError as exc:
        message = f"download failed ({panic_message(exc)})"
        raise RuntimeError(message) from exc


def _do_extract_tar(
    archive_path: Path,
    dest_path: Path,
    entry_name: str,
) -> None:
    with tarfile.open(archive_path, mode="r:*") as tar:
        member = tar.getmember(entry_name)
        tar.extract(member, path=dest_path, filter="data")


def extract_release(
    archive: str | Path,
    destination: str | Path,
    entry_name: str,
    timeout_ms: int,
) -> None:
    """Extract a single entry from a tarball archive to destination directory."""
    archive_path = Path(archive)
    dest_path = Path(destination)
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
        executor.shutdown(wait=False, cancel_futures=True)
        message = "archive extraction timed out"
        raise TimeoutError(message) from exc
    except KeyError as exc:
        executor.shutdown(wait=False, cancel_futures=True)
        message = f"archive extraction failed: missing entry {entry_name}"
        raise RuntimeError(message) from exc
    except Exception as exc:
        executor.shutdown(wait=False, cancel_futures=True)
        message = f"archive extraction failed: {panic_message(exc)}"
        raise RuntimeError(message) from exc
    else:
        executor.shutdown(wait=False)


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
    try:
        stat_info = executable.stat()
        is_regular = stat.S_ISREG(stat_info.st_mode)
        has_exec_bit = (stat_info.st_mode & 0o111) != 0
        if not is_regular or not has_exec_bit:
            return False
        return receipt_path.read_text(encoding="utf-8") == receipt
    except (OSError, UnicodeDecodeError):
        return False


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


def prepare_cli_proxy(
    sync_env: SyncEnv,
    manifest_path: str | Path,
    runtime: ManagedToolRuntime | None = None,
) -> PreparedManagedTool:
    """Download, verify, extract, and stage the CLIProxyAPI tool binary."""
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
    install_dir = (
        Path(cache_home)
        / "github-tools"
        / TOOL_NAME
        / "versions"
        / manifest.version
        / platform_key
    )
    executable = install_dir / executable_name
    receipt_path = install_dir / "receipt.json"
    receipt_payload = {
        "repository": manifest.repository,
        "version": manifest.version,
        "asset": asset.name,
        "sha256": asset.sha256,
    }
    receipt = f"{json.dumps(receipt_payload, indent=RECEIPT_INDENT)}\n"

    if not installed_tool_matches(executable, receipt_path, receipt):
        if install_dir.exists():
            shutil.rmtree(install_dir, ignore_errors=True)
        install_dir.parent.mkdir(parents=True, exist_ok=True)
        stage_dir = tempfile.mkdtemp(prefix=".stage.", dir=str(install_dir.parent))
        stage_path = Path(stage_dir)
        try:
            archive_path = stage_path / asset.name
            url = (
                f"https://github.com/{manifest.repository}/releases/download/"
                f"v{manifest.version}/{asset.name}"
            )
            download_fn = (
                runtime.download if runtime and runtime.download else download_release
            )
            timeout_ms = getattr(
                sync_env,
                "install_timeout_ms",
                getattr(sync_env, "installTimeoutMs", DEFAULT_INSTALL_TIMEOUT_MS),
            )
            download_fn(url, str(archive_path), timeout_ms)
            verify_checksum(archive_path, asset.sha256)
            extract_fn = (
                runtime.extract if runtime and runtime.extract else extract_release
            )
            extract_fn(str(archive_path), str(stage_path), executable_name, timeout_ms)
            archive_path.unlink(missing_ok=True)
            _ensure_staged_executable(stage_path, executable_name)
            (stage_path / "receipt.json").write_text(receipt, encoding="utf-8")
            stage_path.replace(install_dir)
        except Exception as exc:
            shutil.rmtree(stage_dir, ignore_errors=True)
            message = f"install CLIProxyAPI {manifest.version} ({panic_message(exc)})"
            raise RuntimeError(message) from exc

    home = getattr(sync_env, "home", str(Path.home()))
    config_path = str(Path(home) / ".cli-proxy-api" / "config.yaml")
    return PreparedManagedTool(
        name=TOOL_NAME,
        command=manifest.binary,
        executable=str(executable),
        version=manifest.version,
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
            _invoke_fetch(fetch_impl, url, timeout_sec, timeout_ms)
        else:
            httpx.get(url, timeout=timeout_sec)
    except Exception:
        return False
    else:
        return True
