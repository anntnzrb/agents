# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for managed external tool downloading, validation, and preparation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

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
