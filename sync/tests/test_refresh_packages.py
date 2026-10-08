# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Real CLI launches and maintenance against a local npm registry."""

from __future__ import annotations

import asyncio
import gzip
import hashlib
import io
import json
import tarfile
import threading
from dataclasses import dataclass, field, replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, override
from urllib.parse import unquote

import pytest

from sync.core.harness import StaticReleaseLauncher, SyncEnv, supported_harness
from sync.core.launcher import (
    NpmPackageSpec,
    PreparePackageOptions,
    npm_cache_layout,
    refresh_npm_package,
)
from sync.core.tool_launchers import TOOL_LAUNCHERS
from sync.core.wrappers import render_launch_wrapper
from sync.maintenance.refresh_packages import refresh_packages
from sync.runtime.lock import SyncLock, release_sync_lock, try_acquire_sync_lock
from tests.test_integration import run_sync_process, seed_cached_npm_package

if TYPE_CHECKING:
    from collections.abc import Iterator


@dataclass
class Registry:
    """Local registry state and captured HTTP requests."""

    url: str = ""
    version: str = "2.0.0"
    failed: set[str] = field(default_factory=set)
    requests: list[str] = field(default_factory=list)
    release_archive: bytes = b""
    release_checksum: str = ""

    @property
    def env(self) -> dict[str, str]:
        """Point real npm at this server with retries disabled."""
        return {
            "npm_config_registry": self.url,
            "npm_config_fetch_retries": "0",
            "npm_config_fetch_timeout": "1000",
        }


def _bin_name(package: str) -> str:
    return next(
        (tool.bin for tool in TOOL_LAUNCHERS if tool.package == package),
        package.rsplit("/", 1)[-1],
    )


def _tarball(package: str, version: str) -> bytes:
    manifest = json.dumps(
        {
            "name": package,
            "version": version,
            "bin": {_bin_name(package): "cli"},
        }
    ).encode()
    executable = f"#!/bin/sh\necho {package}@{version}\n".encode()
    result = io.BytesIO()
    with tarfile.open(fileobj=result, mode="w") as archive:
        for name, data, mode in (
            ("package/package.json", manifest, 0o644),
            ("package/cli", executable, 0o755),
        ):
            entry = tarfile.TarInfo(name)
            entry.size = len(data)
            entry.mode = mode
            archive.addfile(entry, io.BytesIO(data))
    return gzip.compress(result.getvalue(), mtime=0)


@pytest.fixture
def registry() -> Iterator[Registry]:
    """Serve npm metadata and real installable package archives over loopback."""
    state = Registry()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = unquote(self.path).removeprefix("/")
            state.requests.append(path)
            if path == "release.json":
                self._send(
                    json.dumps(
                        {
                            "version": state.version,
                            "platforms": {
                                "test-platform": {
                                    "url": f"{state.url}release.tar.gz",
                                    "sha256": state.release_checksum,
                                }
                            },
                        }
                    ).encode()
                )
                return
            if path == "release.tar.gz":
                self._send(state.release_archive)
                return
            package = path.removeprefix("tar/")
            version = state.version
            if path.startswith("tar/"):
                package, version = package.rsplit("/", 1)
            if package in state.failed:
                self.send_error(503, "registry unavailable")
                return
            bundle = _tarball(package, version)
            if path.startswith("tar/"):
                data = bundle
            else:
                data = json.dumps(
                    {
                        "name": package,
                        "dist-tags": {"latest": state.version, "stable": state.version},
                        "versions": {
                            selected: {
                                "name": package,
                                "version": selected,
                                "bin": {_bin_name(package): "cli"},
                                "dist": {
                                    "tarball": f"{state.url}tar/{package}/{selected}",
                                    "shasum": hashlib.sha1(  # noqa: S324 - npm archive protocol
                                        _tarball(package, selected)
                                    ).hexdigest(),
                                },
                            }
                            for selected in {"1.0.0", "2.0.0", state.version}
                        },
                    }
                ).encode()
            self._send(data)

        def _send(self, data: bytes) -> None:
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            _ = self.wfile.write(data)

        @override
        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    state.url = f"http://127.0.0.1:{server.server_port}/"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.parametrize("busy", [False, True])
@pytest.mark.parametrize(
    ("target", "package"), [("codex", "@openai/codex"), ("mcporter", "mcporter")]
)
def test_cached_cli_launch_skips_sync_registry_and_busy_lock(
    home: Path, registry: Registry, target: str, package: str, *, busy: bool
) -> None:
    """A cached launch makes no HTTP requests or SSOT writes, even during install."""
    ssot = home / "src" / "agents"
    (ssot / "harnesses" / target).mkdir(parents=True)
    _ = (ssot / "agents.toml").write_text("invalid = [", encoding="utf-8")
    seed_cached_npm_package(
        home,
        {"tool": target, "package": package, "bin": target},
        "0.1.0",
        f"#!/bin/sh\necho {target}-cached\n",
    )
    layout = npm_cache_layout(str(home), NpmPackageSpec(target, package, target))
    lock = try_acquire_sync_lock(layout.tool_cache, layout.lock_file) if busy else None
    assert not busy or lock is not None
    try:
        result = run_sync_process(
            home,
            ["launch", target, "--", "--version"],
            env=registry.env,
            timeout_seconds=3,
        )
    finally:
        if lock is not None:
            release_sync_lock(lock)
    assert result.exit_code == 0, result.stderr
    assert result.stdout.strip() == f"{target}-cached"
    assert registry.requests == []
    assert result.stderr == ""
    assert not (home / ".local/share/agents/sync-managed/sync.lock").exists()


def test_cached_static_cli_launch_skips_sync_and_busy_lock(home: Path) -> None:
    """A cached static release does not fetch a manifest or wait for an installer."""
    (home / "src/agents/harnesses/devin").mkdir(parents=True)
    harness = supported_harness(str(home), "devin", "linux")
    assert harness is not None
    assert isinstance(harness.launcher, StaticReleaseLauncher)
    root = home.joinpath(*harness.launcher.release.install_segments)
    versions = root / "_versions"
    executable = (versions / "1.0.0").joinpath(
        *harness.launcher.release.executable_segments
    )
    executable.parent.mkdir(parents=True)
    _ = executable.write_text("#!/bin/sh\necho static-cached\n", encoding="utf-8")
    executable.chmod(0o755)
    (versions / "current").symlink_to("1.0.0")
    lock = try_acquire_sync_lock(root, root / "lock")
    assert lock is not None
    try:
        result = run_sync_process(
            home, ["launch", "devin", "--", "--version"], timeout_seconds=3
        )
    finally:
        release_sync_lock(lock)
    assert result.exit_code == 0, result.stderr
    assert result.stdout.strip() == "static-cached"
    assert result.stderr == ""


def _seed_tools(home: Path) -> None:
    for tool in TOOL_LAUNCHERS:
        seed_cached_npm_package(
            home,
            {"tool": tool.id, "package": tool.package, "bin": tool.bin},
            "0.1.0",
            "#!/bin/sh\necho cached\n",
        )


def test_refresh_cli_installs_rotates_prunes_and_continues_after_failure(
    home: Path, registry: Registry
) -> None:
    """Maintenance updates through real npm; a failed package retains its cache."""
    _seed_tools(home)
    registry.failed.add("mcporter")
    paseo = next(t for t in TOOL_LAUNCHERS if t.id == "paseo")
    layout = npm_cache_layout(
        str(home), NpmPackageSpec(paseo.id, paseo.package, paseo.bin)
    )
    obsolete = Path(layout.versions_dir) / "0.0.1"
    obsolete.mkdir()
    result = run_sync_process(home, ["job", "refresh-packages"], env=registry.env)
    assert result.exit_code == 0, result.stderr
    assert "mcporter" in result.stderr
    for tool in TOOL_LAUNCHERS:
        cache = npm_cache_layout(
            str(home), NpmPackageSpec(tool.id, tool.package, tool.bin)
        )
        assert Path(cache.current_link).readlink().name == (
            "0.1.0" if tool.id == "mcporter" else "2.0.0"
        )
        if tool.id != "mcporter":
            assert Path(cache.previous_link).readlink().name == "0.1.0"
    assert not obsolete.exists()
    assert "tar/@getpaseo/cli/2.0.0" in registry.requests
    assert (
        run_sync_process(
            home, ["launch", "paseo", "--", "--version"], env=registry.env
        ).stdout.strip()
        == "@getpaseo/cli@2.0.0"
    )


def test_refresh_cli_returns_failure_when_every_package_failed(
    home: Path, registry: Registry
) -> None:
    """Registry failures are visible even though valid cached versions survive."""
    _seed_tools(home)
    registry.failed.update(tool.package for tool in TOOL_LAUNCHERS)
    result = run_sync_process(home, ["job", "refresh-packages"], env=registry.env)
    assert result.exit_code == 1, result.stderr
    for tool in TOOL_LAUNCHERS:
        layout = npm_cache_layout(
            str(home), NpmPackageSpec(tool.id, tool.package, tool.bin)
        )
        assert Path(layout.current_link).readlink().name == "0.1.0"


def test_refresh_cli_skips_busy_packages_without_registry_calls(
    home: Path, registry: Registry
) -> None:
    """An entirely busy round is a successful no-op, without lock waits or HTTP."""
    _seed_tools(home)
    locks: list[SyncLock] = []
    for tool in TOOL_LAUNCHERS:
        layout = npm_cache_layout(
            str(home), NpmPackageSpec(tool.id, tool.package, tool.bin)
        )
        lock = try_acquire_sync_lock(layout.tool_cache, layout.lock_file)
        assert lock is not None
        locks.append(lock)
    try:
        result = run_sync_process(
            home, ["job", "refresh-packages"], env=registry.env, timeout_seconds=3
        )
    finally:
        for lock in locks:
            release_sync_lock(lock)
    assert result.exit_code == 0, result.stderr
    assert "busy" in result.stderr
    assert registry.requests == []


def test_first_cli_launch_installs_and_fails_without_registry(
    home: Path, registry: Registry
) -> None:
    """Cold launch installs synchronously and fails if no package can be obtained."""
    result = run_sync_process(
        home, ["launch", "mcporter", "--", "--version"], env=registry.env
    )
    assert result.exit_code == 0, result.stderr
    assert result.stdout.strip() == "mcporter@2.0.0"
    assert "tar/mcporter/2.0.0" in registry.requests
    registry.failed.add("@steipete/summarize")
    result = run_sync_process(home, ["launch", "summarize"], env=registry.env)
    assert result.exit_code == 1
    assert "could not resolve" in result.stderr


def test_refresh_respects_version_pin(
    home: Path, registry: Registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An exact-version dist_tag cannot drift to a newer registry latest."""
    registry.version = "3.0.0"
    spec = NpmPackageSpec("mcporter", "mcporter", "mcporter", dist_tag="2.0.0")
    for key, value in registry.env.items():
        monkeypatch.setenv(key, value)
    assert asyncio.run(refresh_npm_package(spec, PreparePackageOptions(home=str(home))))
    layout = npm_cache_layout(str(home), spec)
    assert Path(layout.current_link).readlink().name == "2.0.0"
    assert "tar/mcporter/2.0.0" in registry.requests
    assert "tar/mcporter/3.0.0" not in registry.requests


def test_refresh_cli_discovers_installed_harness_without_ssot(
    home: Path, registry: Registry
) -> None:
    """A managed harness wrapper remains refreshable while its SSOT is absent."""
    wrapper = home / ".local/bin/codex"
    wrapper.parent.mkdir(parents=True)
    _ = wrapper.write_text(
        render_launch_wrapper(str(home / ".local/share/agents"), "codex"),
        encoding="utf-8",
    )
    result = run_sync_process(home, ["job", "refresh-packages"], env=registry.env)
    assert result.exit_code == 0, result.stderr
    assert "tar/@openai/codex/2.0.0" in registry.requests


def test_refresh_job_updates_static_release_and_preserves_cache_on_failure(
    home: Path, registry: Registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Static updates rotate versions; checksum failure preserves current."""
    for key, value in registry.env.items():
        monkeypatch.setenv(key, value)
    harness = supported_harness(str(home), "devin", "linux")
    assert harness is not None
    assert isinstance(harness.launcher, StaticReleaseLauncher)
    targets = dict.fromkeys(harness.launcher.release.targets, "test-platform")
    release = replace(
        harness.launcher.release,
        manifest_url=f"{registry.url}release.json",
        targets=targets,
    )
    harness = replace(harness, launcher=replace(harness.launcher, release=release))
    env = replace(SyncEnv.from_home(str(home)), harnesses=(harness,))
    archive_bytes = io.BytesIO()
    with tarfile.open(fileobj=archive_bytes, mode="w") as archive:
        for name, content in (
            ("bin/devin", b"#!/bin/sh\necho new\n"),
            ("share/man/man1/devin.1", b".TH devin 1\n"),
        ):
            entry = tarfile.TarInfo(name)
            entry.size = len(content)
            entry.mode = 0o755
            archive.addfile(entry, io.BytesIO(content))
    registry.release_archive = gzip.compress(archive_bytes.getvalue(), mtime=0)
    registry.release_checksum = hashlib.sha256(registry.release_archive).hexdigest()
    versions = home.joinpath(*release.install_segments, "_versions")
    old = (versions / "1.0.0").joinpath(*release.executable_segments)
    old.parent.mkdir(parents=True)
    _ = old.write_text("#!/bin/sh\necho old\n", encoding="utf-8")
    old.chmod(0o755)
    (versions / "current").symlink_to("1.0.0")
    (versions / "0.0.1").mkdir()
    assert refresh_packages(env) == 0
    assert (versions / "current").readlink().name == "2.0.0"
    assert (versions / "previous").readlink().name == "1.0.0"
    assert not (versions / "0.0.1").exists()
    assert "release.tar.gz" in registry.requests
    assert release.man_dest_segments is not None
    assert home.joinpath(*release.man_dest_segments, "devin.1").is_symlink()

    registry.failed.update(tool.package for tool in TOOL_LAUNCHERS)
    registry.version = "3.0.0"
    registry.release_checksum = "0" * 64
    assert refresh_packages(env) == 1
    assert (versions / "current").readlink().name == "2.0.0"
    assert (versions / "previous").readlink().name == "1.0.0"

    install_root = versions.parent
    lock = try_acquire_sync_lock(install_root, install_root / "lock")
    assert lock is not None
    registry.requests.clear()
    try:
        assert refresh_packages(env) == 0
    finally:
        release_sync_lock(lock)
    assert "release.json" not in registry.requests


def test_cached_harness_launch_survives_source_directory_removal(home: Path) -> None:
    """A cached installed wrapper remains usable until manual sync removes it."""
    (home / "src/agents").mkdir(parents=True)
    seed_cached_npm_package(
        home,
        {"tool": "codex", "package": "@openai/codex", "bin": "codex"},
        "0.1.0",
        "#!/bin/sh\necho cached\n",
    )
    result = run_sync_process(
        home, ["launch", "codex", "--", "--version"], timeout_seconds=3
    )
    assert result.exit_code == 0, result.stderr
    assert result.stdout.strip() == "cached"
    assert result.stderr == ""
