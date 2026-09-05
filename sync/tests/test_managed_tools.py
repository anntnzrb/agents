# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for managed external tool downloading, validation, and preparation."""

from __future__ import annotations

import hashlib
import json
import tarfile
import time
from pathlib import Path
from typing import Final

import pytest

from sync.core.cliproxy_deployment import (
    ClientConfig,
    CliProxyDeployment,
    ListenConfig,
    ServerConfig,
)
from sync.core.harness import SyncEnv
from sync.core.managed_tools import (
    ManagedToolRuntime,
    extract_release,
    installed_tool_matches,
    is_cli_proxy_running,
    prepare_managed_tools,
)

ARCHIVE_CONTENT = b"fixture archive"
EXPECTED_CHECKSUM = hashlib.sha256(ARCHIVE_CONTENT).hexdigest()
INVALID_CHECKSUM = "0" * 64
TEST_PORT = 9443
HEALTH_CHECK_TIMEOUT_MS = 500
INSTALL_TIMEOUT_MS = 1000
EXECUTABLE_MODE = 0o755
EXPECTED_FETCH_TIMEOUT_SEC: Final[float] = 1.5
EXPECTED_REINSTALL_DOWNLOADS: Final[int] = 2

DEPLOYMENT = CliProxyDeployment(
    server=ServerConfig(hostname="test-gateway"),
    listen=ListenConfig(host="100.64.0.42", port=TEST_PORT),
    client=ClientConfig(baseUrl="https://gateway.example.test:9443/v1"),
)


def write_manifest(home: Path, checksum: str = EXPECTED_CHECKSUM) -> None:
    """Write a valid tool release manifest under ~/.config/agents/tools/cliproxyapi."""
    manifest_dir = home / ".config" / "agents" / "tools" / "cliproxyapi"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_payload = {
        "repository": "router-for-me/CLIProxyAPI",
        "version": "7.2.132",
        "binary": "cli-proxy-api",
        "assets": {
            "darwin-arm64": {
                "name": "CLIProxyAPI_7.2.132_darwin_aarch64.tar.gz",
                "sha256": checksum,
            },
        },
    }
    manifest_path = manifest_dir / "release.json"
    manifest_path.write_text(f"{json.dumps(manifest_payload)}\n", encoding="utf-8")


def test_managed_tool_downloads_verified_release_once(tmp_path: Path) -> None:
    """Verify tool is downloaded and extracted once, then fast-pathed on reuse."""
    write_manifest(tmp_path)
    sync_env = SyncEnv.from_home(
        str(tmp_path),
        INSTALL_TIMEOUT_MS,
        platform="darwin",
    )
    downloads = 0

    def mock_download(url: str, destination: str, timeout_ms: int) -> None:
        nonlocal downloads
        _ = timeout_ms
        downloads += 1
        assert "/releases/download/v7.2.132/" in url
        Path(destination).write_bytes(ARCHIVE_CONTENT)

    def mock_extract(
        archive: str,
        destination: str,
        entry_name: str,
        timeout_ms: int,
    ) -> None:
        _ = (archive, timeout_ms)
        assert entry_name == "cli-proxy-api"
        executable = Path(destination) / entry_name
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(EXECUTABLE_MODE)

    runtime = ManagedToolRuntime(
        arch="arm64",
        cache_home=str(tmp_path / "cache"),
        download=mock_download,
        extract=mock_extract,
    )

    first_list = prepare_managed_tools(sync_env, runtime)
    assert len(first_list) == 1
    first = first_list[0]
    assert first.version == "7.2.132"
    assert first.command == "cli-proxy-api"
    assert Path(first.executable).exists()
    assert Path(first.executable).read_text(encoding="utf-8") == "#!/bin/sh\nexit 0\n"

    second_list = prepare_managed_tools(sync_env, runtime)
    assert len(second_list) == 1
    second = second_list[0]
    assert second.executable == first.executable
    assert downloads == 1


def test_managed_tool_rejects_checksum_mismatch(tmp_path: Path) -> None:
    """Verify checksum mismatch during installation raises an error."""
    write_manifest(tmp_path, INVALID_CHECKSUM)
    sync_env = SyncEnv.from_home(
        str(tmp_path),
        INSTALL_TIMEOUT_MS,
        platform="darwin",
    )

    def mock_download(_url: str, destination: str, _timeout_ms: int) -> None:
        Path(destination).write_bytes(ARCHIVE_CONTENT)

    runtime = ManagedToolRuntime(
        arch="arm64",
        cache_home=str(tmp_path / "cache"),
        download=mock_download,
    )

    with pytest.raises(RuntimeError, match=r"checksum mismatch"):
        prepare_managed_tools(sync_env, runtime)


def test_managed_tool_rejects_platform_without_pinned_asset(
    tmp_path: Path,
) -> None:
    """Verify error is raised when release manifest lacks asset for platform."""
    write_manifest(tmp_path)
    sync_env = SyncEnv.from_home(
        str(tmp_path),
        INSTALL_TIMEOUT_MS,
        platform="linux",
    )
    runtime = ManagedToolRuntime(
        arch="arm64",
        cache_home=str(tmp_path / "cache"),
    )

    with pytest.raises(RuntimeError, match=r"no release asset for linux-arm64"):
        prepare_managed_tools(sync_env, runtime)


def test_managed_tool_health_check_targets_deployment_client() -> None:
    """Verify is_cli_proxy_running requests models endpoint on deployment."""
    calls: list[str] = []

    def mock_fetch(input_url: str) -> object:
        calls.append(input_url)
        return object()

    healthy = is_cli_proxy_running(
        DEPLOYMENT,
        HEALTH_CHECK_TIMEOUT_MS,
        fetch_impl=mock_fetch,
    )
    assert healthy is True
    assert calls == ["https://gateway.example.test:9443/v1/models"]


def test_managed_tool_rejects_unsupported_arch_and_invalid_manifest(
    tmp_path: Path,
) -> None:
    """Verify unsupported architecture and invalid manifest errors."""
    write_manifest(tmp_path)
    sync_env = SyncEnv.from_home(
        str(tmp_path),
        INSTALL_TIMEOUT_MS,
        platform="darwin",
    )
    runtime = ManagedToolRuntime(
        arch="ia32",
        cache_home=str(tmp_path / "cache"),
    )

    with pytest.raises(RuntimeError, match=r"unsupported architecture"):
        prepare_managed_tools(sync_env, runtime)

    manifest_path = (
        tmp_path / ".config" / "agents" / "tools" / "cliproxyapi" / "release.json"
    )
    manifest_path.write_text("invalid json", encoding="utf-8")
    with pytest.raises(RuntimeError, match=r"parse"):
        prepare_managed_tools(sync_env)


def test_extract_release_enforces_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """extract_release raises TimeoutError when extraction exceeds deadline."""
    archive_path = tmp_path / "test.tar.gz"
    entry_file = tmp_path / "dummy.txt"
    entry_file.write_text("dummy", encoding="utf-8")
    with tarfile.open(archive_path, "w:gz") as tar:
        tar.add(entry_file, arcname="dummy.txt")

    def slow_extract(
        _archive_path: Path,
        _dest_path: Path,
        _entry_name: str,
    ) -> None:
        time.sleep(0.1)

    monkeypatch.setattr("sync.core.managed_tools._do_extract_tar", slow_extract)

    dest = tmp_path / "dest"
    dest.mkdir(parents=True, exist_ok=True)
    with pytest.raises(TimeoutError, match=r"archive extraction timed out"):
        extract_release(archive_path, dest, "dummy.txt", timeout_ms=10)


def test_managed_tool_health_check_passes_timeout_to_fetch_impl() -> None:
    """is_cli_proxy_running passes timeout budget to injected fetch_impl."""
    captured: dict[str, object] = {}

    def mock_fetch(url: str, timeout: float) -> object:
        captured["url"] = url
        captured["timeout"] = timeout
        return object()

    healthy = is_cli_proxy_running(
        DEPLOYMENT,
        timeout_ms=1500,
        fetch_impl=mock_fetch,
    )
    assert healthy is True
    assert captured["url"] == "https://gateway.example.test:9443/v1/models"
    assert captured["timeout"] == EXPECTED_FETCH_TIMEOUT_SEC


def test_managed_tool_health_check_infallible_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """is_cli_proxy_running returns False on any Exception without raising."""

    def exploding_fetch(_url: str) -> object:
        message = "unexpected error in fetch"
        raise TypeError(message)

    assert is_cli_proxy_running(DEPLOYMENT, fetch_impl=exploding_fetch) is False

    def exploding_url(_dep: CliProxyDeployment) -> str:
        message = "cannot build models url"
        raise ValueError(message)

    monkeypatch.setattr("sync.core.managed_tools.cliproxy_models_url", exploding_url)
    assert is_cli_proxy_running(DEPLOYMENT) is False


def test_installed_tool_matches_handles_undecodable_receipt(
    tmp_path: Path,
) -> None:
    """installed_tool_matches returns False when receipt is not valid UTF-8."""
    executable = tmp_path / "bin"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(EXECUTABLE_MODE)
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_bytes(b"\xff\xfe\x00\x00corrupt")

    matches = installed_tool_matches(executable, receipt_path, "expected receipt")
    assert matches is False


def test_managed_tool_recovers_from_corrupted_receipt(tmp_path: Path) -> None:
    """Corrupted non-UTF8 receipt is treated as cache miss and triggers reinstall."""
    write_manifest(tmp_path)
    sync_env = SyncEnv.from_home(
        str(tmp_path),
        INSTALL_TIMEOUT_MS,
        platform="darwin",
    )
    downloads = 0

    def mock_download(_url: str, destination: str, _timeout_ms: int) -> None:
        nonlocal downloads
        downloads += 1
        Path(destination).write_bytes(ARCHIVE_CONTENT)

    def mock_extract(
        _archive: str,
        destination: str,
        entry_name: str,
        _timeout_ms: int,
    ) -> None:
        executable = Path(destination) / entry_name
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(EXECUTABLE_MODE)

    runtime = ManagedToolRuntime(
        arch="arm64",
        cache_home=str(tmp_path / "cache"),
        download=mock_download,
        extract=mock_extract,
    )

    prepare_managed_tools(sync_env, runtime)
    assert downloads == 1

    install_dir = (
        tmp_path
        / "cache"
        / "github-tools"
        / "cliproxyapi"
        / "versions"
        / "7.2.132"
        / "darwin-arm64"
    )
    receipt_path = install_dir / "receipt.json"
    receipt_path.write_bytes(b"\x80\x81corrupt_bytes")

    tools = prepare_managed_tools(sync_env, runtime)
    assert len(tools) == 1
    assert downloads == EXPECTED_REINSTALL_DOWNLOADS
