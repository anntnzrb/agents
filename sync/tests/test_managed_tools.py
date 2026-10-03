# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for managed external tool downloading, validation, and preparation."""

from __future__ import annotations

import hashlib
import json
import re
import tarfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, cast

import httpx
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
    download_release,
    extract_release,
    fetch_checksums,
    installed_tool_matches,
    is_cli_proxy_running,
    prepare_managed_tools,
    prepare_release_tool,
    read_manifest,
)

if TYPE_CHECKING:
    from sync.core.harness_adapters import HostPlatform

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
    _ = manifest_path.write_text(f"{json.dumps(manifest_payload)}\n", encoding="utf-8")


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
        _ = Path(destination).write_bytes(ARCHIVE_CONTENT)

    def mock_extract(
        archive: str,
        destination: str,
        entry_name: str,
        timeout_ms: int,
    ) -> None:
        _ = (archive, timeout_ms)
        assert entry_name == "cli-proxy-api"
        executable = Path(destination) / entry_name
        _ = executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
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
        _ = Path(destination).write_bytes(ARCHIVE_CONTENT)

    runtime = ManagedToolRuntime(
        arch="arm64",
        cache_home=str(tmp_path / "cache"),
        download=mock_download,
    )

    with pytest.raises(RuntimeError, match=r"checksum mismatch"):
        _ = prepare_managed_tools(sync_env, runtime)


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
        _ = prepare_managed_tools(sync_env, runtime)


@pytest.mark.parametrize(
    ("platform_name", "arch", "asset_arch"),
    [
        ("linux", "x64", "amd64"),
        ("linux", "arm64", "arm64"),
        ("darwin", "x64", "amd64"),
        ("darwin", "arm64", "arm64"),
    ],
)
def test_kestractl_installs_independently_on_pinned_platforms(
    tmp_path: Path, platform_name: HostPlatform, arch: str, asset_arch: str
) -> None:
    """Install kestractl without a gateway and reuse its verified archive."""
    sync_env = SyncEnv.from_home(
        str(tmp_path), INSTALL_TIMEOUT_MS, platform=platform_name
    )
    cache = tmp_path / "cache"
    downloads: list[str] = []
    archive = b"kestractl pinned release fixture"
    checksum = hashlib.sha256(archive).hexdigest()
    manifest = Path(__file__).parents[2] / "tools/kestractl/release.json"
    payload = cast(
        "dict[str, object]", json.loads(manifest.read_text(encoding="utf-8"))
    )
    assets = cast("dict[str, dict[str, object]]", payload["assets"])
    assets[f"{platform_name}-{arch}"]["sha256"] = checksum
    manifest = tmp_path / "release.json"
    _ = manifest.write_text(json.dumps(payload), encoding="utf-8")

    def download(url: str, destination: str, _timeout_ms: int) -> None:
        downloads.append(url)
        _ = Path(destination).write_bytes(archive)

    def extract(
        _archive: str, destination: str, entry_name: str, _timeout_ms: int
    ) -> None:
        executable = Path(destination) / entry_name
        _ = executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(EXECUTABLE_MODE)

    runtime = ManagedToolRuntime(
        arch=arch, cache_home=str(cache), download=download, extract=extract
    )

    first = prepare_release_tool(
        sync_env,
        "kestractl",
        manifest,
        runtime,
    )
    second = prepare_release_tool(
        sync_env,
        "kestractl",
        manifest,
        runtime,
    )
    assert first.command == "kestractl"
    assert first.config_path == ""
    assert first.executable == second.executable
    assert len(downloads) == 1
    assert downloads == [
        (
            "https://github.com/kestra-io/kestractl/releases/download/v3.6.0/"
            f"kestractl_3.6.0_{platform_name}_{asset_arch}.tar.gz"
        )
    ]


def test_kestractl_platform_assets_are_fully_pinned() -> None:
    """The release manifest supports all declared macOS/Linux architectures."""
    manifest = read_manifest(Path(__file__).parents[2] / "tools/kestractl/release.json")
    assert set(manifest.assets) == {
        "darwin-x64",
        "darwin-arm64",
        "linux-x64",
        "linux-arm64",
    }
    assert all(asset.sha256 is not None for asset in manifest.assets.values())


@pytest.mark.parametrize("gateway_host", [False, True])
def test_managed_tools_respects_gateway_placement(
    tmp_path: Path, *, gateway_host: bool
) -> None:
    """Kestractl installs everywhere; CLIProxyAPI only on the gateway."""
    write_manifest(tmp_path)
    source = Path(__file__).parents[2] / "tools/kestractl/release.json"
    destination = tmp_path / ".config/agents/tools/kestractl/release.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    _ = destination.write_bytes(source.read_bytes())
    env = SyncEnv.from_home(str(tmp_path), INSTALL_TIMEOUT_MS, platform="darwin")
    archive = ARCHIVE_CONTENT
    checksum = hashlib.sha256(archive).hexdigest()
    payload = cast("dict[str, object]", json.loads(source.read_text(encoding="utf-8")))
    assets = cast("dict[str, dict[str, object]]", payload["assets"])
    assets["darwin-arm64"]["sha256"] = checksum
    _ = destination.write_text(json.dumps(payload), encoding="utf-8")

    def download(_url: str, path: str, _timeout: int) -> None:
        _ = Path(path).write_bytes(archive)

    def extract(
        _archive: str, destination_path: str, entry: str, _timeout: int
    ) -> None:
        executable = Path(destination_path) / entry
        _ = executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(EXECUTABLE_MODE)

    runtime = ManagedToolRuntime(
        arch="arm64",
        cache_home=str(tmp_path / "cache"),
        download=download,
        extract=extract,
    )

    prepared = prepare_managed_tools(env, runtime, gateway_host=gateway_host)

    expected_names = ["kestractl", "cliproxyapi"] if gateway_host else ["kestractl"]
    assert [tool.name for tool in prepared] == expected_names
    assert len({tool.executable for tool in prepared}) == len(prepared)


def test_kestractl_rejects_checksum_failure_and_unsupported_asset(
    tmp_path: Path,
) -> None:
    """Kestractl uses normal pinned verification and platform rejection."""
    env = SyncEnv.from_home(str(tmp_path), INSTALL_TIMEOUT_MS, platform="darwin")
    source = Path(__file__).parents[2] / "tools/kestractl/release.json"
    checksum_manifest = tmp_path / "checksummed.json"
    payload = cast("dict[str, object]", json.loads(source.read_text(encoding="utf-8")))
    assets = cast("dict[str, dict[str, object]]", payload["assets"])
    assets["darwin-arm64"]["sha256"] = INVALID_CHECKSUM
    _ = checksum_manifest.write_text(json.dumps(payload), encoding="utf-8")

    def download(_url: str, path: str, _timeout: int) -> None:
        _ = Path(path).write_bytes(ARCHIVE_CONTENT)

    runtime = ManagedToolRuntime(
        arch="arm64",
        cache_home=str(tmp_path / "cache"),
        download=download,
    )
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        _ = prepare_release_tool(env, "kestractl", checksum_manifest, runtime)

    unsupported_env = SyncEnv.from_home(
        str(tmp_path), INSTALL_TIMEOUT_MS, platform="linux"
    )
    del assets["linux-x64"]
    unsupported_manifest = tmp_path / "unsupported.json"
    _ = unsupported_manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(
        RuntimeError, match="kestractl has no release asset for linux-x64"
    ):
        _ = prepare_release_tool(
            unsupported_env,
            "kestractl",
            unsupported_manifest,
            ManagedToolRuntime(arch="x64", cache_home=str(tmp_path / "cache")),
        )


def test_managed_tool_health_check_targets_deployment_client() -> None:
    """Verify is_cli_proxy_running requests models endpoint on deployment."""
    calls: list[str] = []

    def mock_fetch(input_url: str, _timeout: float) -> object:
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
        _ = prepare_managed_tools(sync_env, runtime)

    manifest_path = (
        tmp_path / ".config" / "agents" / "tools" / "cliproxyapi" / "release.json"
    )
    _ = manifest_path.write_text("invalid json", encoding="utf-8")
    with pytest.raises(RuntimeError, match=r"parse"):
        _ = prepare_managed_tools(sync_env)


def test_extract_release_enforces_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """extract_release raises TimeoutError when extraction exceeds deadline."""
    archive_path = tmp_path / "test.tar.gz"
    entry_file = tmp_path / "dummy.txt"
    _ = entry_file.write_text("dummy", encoding="utf-8")
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

    def exploding_fetch(_url: str, _timeout: float) -> object:
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
    _ = executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(EXECUTABLE_MODE)
    receipt_path = tmp_path / "receipt.json"
    _ = receipt_path.write_bytes(b"\xff\xfe\x00\x00corrupt")

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
        _ = Path(destination).write_bytes(ARCHIVE_CONTENT)

    def mock_extract(
        _archive: str,
        destination: str,
        entry_name: str,
        _timeout_ms: int,
    ) -> None:
        executable = Path(destination) / entry_name
        _ = executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(EXECUTABLE_MODE)

    runtime = ManagedToolRuntime(
        arch="arm64",
        cache_home=str(tmp_path / "cache"),
        download=mock_download,
        extract=mock_extract,
    )

    _ = prepare_managed_tools(sync_env, runtime)
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
    _ = receipt_path.write_bytes(b"\x80\x81corrupt_bytes")

    tools = prepare_managed_tools(sync_env, runtime)
    assert len(tools) == 1
    assert downloads == EXPECTED_REINSTALL_DOWNLOADS


LATEST_VERSION = "7.3.0"
LATEST_ARCHIVE_NAME = "CLIProxyAPI_7.3.0_darwin_aarch64.tar.gz"
LATEST_CHECKSUMS_URL = (
    "https://github.com/router-for-me/CLIProxyAPI/releases/download/"
    f"v{LATEST_VERSION}/checksums.txt"
)


def write_latest_manifest(home: Path) -> None:
    """Write a latest-tracking manifest with version-name templates."""
    manifest_dir = home / ".config" / "agents" / "tools" / "cliproxyapi"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_payload = {
        "repository": "router-for-me/CLIProxyAPI",
        "version": "latest",
        "binary": "cli-proxy-api",
        "assets": {
            "darwin-arm64": {
                "name": "CLIProxyAPI_{version}_darwin_aarch64.tar.gz",
            },
        },
    }
    manifest_path = manifest_dir / "release.json"
    _ = manifest_path.write_text(f"{json.dumps(manifest_payload)}\n", encoding="utf-8")


def test_managed_tool_tracks_latest_release(tmp_path: Path) -> None:
    """Latest manifests resolve the tag and verify the download via checksums."""
    write_latest_manifest(tmp_path)
    sync_env = SyncEnv.from_home(
        str(tmp_path),
        INSTALL_TIMEOUT_MS,
        platform="darwin",
    )
    downloads: list[str] = []
    checksum_fetches: list[str] = []

    def mock_resolve(repository: str, timeout_ms: int) -> str:
        _ = timeout_ms
        assert repository == "router-for-me/CLIProxyAPI"
        return LATEST_VERSION

    def mock_fetch_checksums(url: str, timeout_ms: int) -> dict[str, str]:
        _ = timeout_ms
        checksum_fetches.append(url)
        return {LATEST_ARCHIVE_NAME: EXPECTED_CHECKSUM}

    def mock_download(url: str, destination: str, timeout_ms: int) -> None:
        _ = timeout_ms
        downloads.append(url)
        _ = Path(destination).write_bytes(ARCHIVE_CONTENT)

    def mock_extract(
        _archive: str,
        destination: str,
        entry_name: str,
        _timeout_ms: int,
    ) -> None:
        executable = Path(destination) / entry_name
        _ = executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(EXECUTABLE_MODE)

    runtime = ManagedToolRuntime(
        arch="arm64",
        cache_home=str(tmp_path / "cache"),
        resolve_version=mock_resolve,
        fetch_checksums=mock_fetch_checksums,
        download=mock_download,
        extract=mock_extract,
    )

    first = prepare_managed_tools(sync_env, runtime)[0]
    assert first.version == LATEST_VERSION
    assert f"/releases/download/v{LATEST_VERSION}/{LATEST_ARCHIVE_NAME}" in downloads[0]
    assert LATEST_VERSION in first.executable
    assert checksum_fetches == [LATEST_CHECKSUMS_URL]

    second = prepare_managed_tools(sync_env, runtime)[0]
    assert second.executable == first.executable
    assert len(downloads) == 1
    assert len(checksum_fetches) == 1


def test_managed_tool_latest_falls_back_to_cached_install(tmp_path: Path) -> None:
    """A failed latest lookup reuses the newest verified cached install."""
    write_latest_manifest(tmp_path)
    sync_env = SyncEnv.from_home(
        str(tmp_path),
        INSTALL_TIMEOUT_MS,
        platform="darwin",
    )
    downloads = 0

    def mock_download(_url: str, destination: str, _timeout_ms: int) -> None:
        nonlocal downloads
        downloads += 1
        _ = Path(destination).write_bytes(ARCHIVE_CONTENT)

    def mock_extract(
        _archive: str,
        destination: str,
        entry_name: str,
        _timeout_ms: int,
    ) -> None:
        executable = Path(destination) / entry_name
        _ = executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(EXECUTABLE_MODE)

    def mock_fetch_checksums(_url: str, _timeout_ms: int) -> dict[str, str]:
        return {LATEST_ARCHIVE_NAME: EXPECTED_CHECKSUM}

    online = ManagedToolRuntime(
        arch="arm64",
        cache_home=str(tmp_path / "cache"),
        resolve_version=lambda _repository, _timeout_ms: LATEST_VERSION,
        fetch_checksums=mock_fetch_checksums,
        download=mock_download,
        extract=mock_extract,
    )
    first = prepare_managed_tools(sync_env, online)[0]
    assert first.version == LATEST_VERSION
    assert downloads == 1

    def offline_resolve(_repository: str, _timeout_ms: int) -> str:
        message = "network down"
        raise RuntimeError(message)

    offline = ManagedToolRuntime(
        arch="arm64",
        cache_home=str(tmp_path / "cache"),
        resolve_version=offline_resolve,
    )
    cached = prepare_managed_tools(sync_env, offline)[0]
    assert cached.version == LATEST_VERSION
    assert cached.executable == first.executable
    assert downloads == 1


def test_managed_tool_latest_without_cache_raises(tmp_path: Path) -> None:
    """Latest lookup failure without a cached install surfaces the error."""
    write_latest_manifest(tmp_path)
    sync_env = SyncEnv.from_home(
        str(tmp_path),
        INSTALL_TIMEOUT_MS,
        platform="darwin",
    )

    def offline_resolve(_repository: str, _timeout_ms: int) -> str:
        message = "network down"
        raise RuntimeError(message)

    runtime = ManagedToolRuntime(
        arch="arm64",
        cache_home=str(tmp_path / "cache"),
        resolve_version=offline_resolve,
    )
    with pytest.raises(RuntimeError, match=r"network down"):
        _ = prepare_managed_tools(sync_env, runtime)


def test_managed_tool_latest_requires_checksums_entry(tmp_path: Path) -> None:
    """A checksums file without the target asset aborts the install."""
    write_latest_manifest(tmp_path)
    sync_env = SyncEnv.from_home(
        str(tmp_path),
        INSTALL_TIMEOUT_MS,
        platform="darwin",
    )
    downloads = 0

    def mock_download(_url: str, destination: str, _timeout_ms: int) -> None:
        nonlocal downloads
        downloads += 1
        _ = Path(destination).write_bytes(ARCHIVE_CONTENT)

    runtime = ManagedToolRuntime(
        arch="arm64",
        cache_home=str(tmp_path / "cache"),
        resolve_version=lambda _repository, _timeout_ms: LATEST_VERSION,
        fetch_checksums=lambda _url, _timeout_ms: {},
        download=mock_download,
    )
    with pytest.raises(RuntimeError, match=r"checksums missing"):
        _ = prepare_managed_tools(sync_env, runtime)
    assert downloads == 0


@dataclass(frozen=True, slots=True)
class _FakeHttpResponse:
    """Minimal stand-in for the httpx response surface the fetchers read."""

    status_code: int
    content: bytes = b""

    @property
    def text(self) -> str:
        """Decode the body like httpx does for UTF-8 payloads."""
        return self.content.decode("utf-8")


def _install_http_get(
    monkeypatch: pytest.MonkeyPatch,
    outcome: _FakeHttpResponse | Exception,
    calls: list[tuple[str, float, bool]],
) -> None:
    """Replace httpx.get with a fake that records its call and replays one outcome."""

    def _fake_get(
        url: str, *, timeout: float, follow_redirects: bool
    ) -> _FakeHttpResponse:
        calls.append((url, timeout, follow_redirects))
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr("httpx.get", _fake_get)


def test_download_release_writes_body_and_converts_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 200 response body lands at the destination; timeout is in seconds."""
    calls: list[tuple[str, float, bool]] = []
    _install_http_get(monkeypatch, _FakeHttpResponse(200, ARCHIVE_CONTENT), calls)
    destination = tmp_path / "archive.tar.gz"

    download_release("https://example.test/a.tar.gz", destination, 1500)

    assert destination.read_bytes() == ARCHIVE_CONTENT
    assert calls == [
        ("https://example.test/a.tar.gz", EXPECTED_FETCH_TIMEOUT_SEC, True)
    ]


@pytest.mark.parametrize(
    ("outcome", "message"),
    [
        (_FakeHttpResponse(404), "download failed with HTTP 404"),
        (httpx.ConnectError("refused"), "download failed (refused)"),
    ],
)
def test_download_release_reports_http_and_transport_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    outcome: _FakeHttpResponse | Exception,
    message: str,
) -> None:
    """Non-200 statuses and transport errors raise with a labelled message."""
    _install_http_get(monkeypatch, outcome, [])
    destination = tmp_path / "archive.tar.gz"

    with pytest.raises(RuntimeError, match=re.escape(message)):
        download_release("https://example.test/a.tar.gz", destination, 1500)
    assert not destination.exists()


def test_fetch_checksums_parses_body_and_converts_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 200 checksums body parses into a name-to-digest mapping."""
    calls: list[tuple[str, float, bool]] = []
    body = f"{EXPECTED_CHECKSUM}  cli.tar.gz\nnot a checksum line\n".encode()
    _install_http_get(monkeypatch, _FakeHttpResponse(200, body), calls)

    entries = fetch_checksums("https://example.test/checksums.txt", 1500)

    assert entries == {"cli.tar.gz": EXPECTED_CHECKSUM}
    assert calls == [
        ("https://example.test/checksums.txt", EXPECTED_FETCH_TIMEOUT_SEC, True)
    ]


@pytest.mark.parametrize(
    ("outcome", "message"),
    [
        (_FakeHttpResponse(500), "checksums download failed with HTTP 500"),
        (httpx.ReadTimeout("slow"), "checksums download failed (slow)"),
    ],
)
def test_fetch_checksums_reports_http_and_transport_failures(
    monkeypatch: pytest.MonkeyPatch,
    outcome: _FakeHttpResponse | Exception,
    message: str,
) -> None:
    """Non-200 statuses and transport errors raise with a labelled message."""
    _install_http_get(monkeypatch, outcome, [])

    with pytest.raises(RuntimeError, match=re.escape(message)):
        _ = fetch_checksums("https://example.test/checksums.txt", 1500)
