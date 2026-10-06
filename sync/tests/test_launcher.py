# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for npm package resolution, caching, and launcher subprocess dispatch."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import TYPE_CHECKING, Final

import pytest

from sync.core.harness import StaticRelease, StaticReleaseLauncher, SyncEnv
from sync.core.launcher import (
    LauncherRuntime,
    NpmPackageSpec,
    PreparePackageOptions,
    ReleaseRuntime,
    launch_harness,
    launch_npm_package,
    npm_cache_layout,
    prepare_npm_package,
    prepare_static_release,
    running_executables,
)
from sync.core.release_manifest import StaticReleaseAsset, StaticReleaseManifest
from sync.core.tool_launchers import tool_launcher
from sync.runtime.process import (
    MAX_DETAIL_CHARS,
    ProcessResult,
    RunProcessOptions,
    run_process,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

EXPECTED_INSTALLS: Final[int] = 2
DEFAULT_PREPARE_TIMEOUT_MS: Final[int] = 1000
MODE_EXECUTABLE: Final[int] = 0o755
RELEASE_VERSION: Final[str] = "9.9.9"
RELEASE_TARGET: Final[str] = "x86_64-unknown-linux"


def _make_release_bundle(bundle: Path, stage: Path) -> str:
    """Create a fake release tar.gz and return its SHA-256 hex digest."""
    binary = stage / "bin" / "devin"
    binary.parent.mkdir(parents=True, exist_ok=True)
    _ = binary.write_text("#!/bin/sh\necho devin\n", encoding="utf-8")
    binary.chmod(MODE_EXECUTABLE)
    docs = stage / "share" / "devin" / "docs" / "index.mdx"
    docs.parent.mkdir(parents=True, exist_ok=True)
    _ = docs.write_text("docs\n", encoding="utf-8")
    man = stage / "share" / "man" / "man1" / "devin.1"
    man.parent.mkdir(parents=True, exist_ok=True)
    _ = man.write_text(".TH devin 1\n", encoding="utf-8")
    with tarfile.open(bundle, "w:gz") as archive:
        archive.add(binary, arcname="bin/devin")
        archive.add(docs, arcname="share/devin/docs/index.mdx")
        archive.add(man, arcname="share/man/man1/devin.1")
    return hashlib.sha256(bundle.read_bytes()).hexdigest()


def _release_spec() -> StaticRelease:
    """Return the static release source used by the launch tests."""
    return StaticRelease(
        manifest_url="https://example.test/manifest.json",
        install_segments=(".local", "share", "devin", "cli"),
        executable_segments=("bin", "devin"),
        targets={"linux-x64": RELEASE_TARGET},
        man_segments=("share", "man", "man1"),
        man_dest_segments=(".local", "share", "man", "man1"),
    )


def _release_manifest(sha256: str) -> StaticReleaseManifest:
    """Return a manifest pointing at a single Linux x64 platform asset."""
    return StaticReleaseManifest(
        version=RELEASE_VERSION,
        platforms={
            RELEASE_TARGET: StaticReleaseAsset(
                url="https://example.test/bundle.tar.gz",
                sha256=sha256,
            )
        },
    )


def _success(stdout: str = "") -> ProcessResult:
    """Return a successful ProcessResult."""
    return ProcessResult(
        exit_code=0,
        stdout=stdout,
        stderr="",
        timed_out=False,
    )


def _write_package_manifest(
    root: str | Path,
    package_name: str,
    version: str,
) -> None:
    """Write package.json manifest in node_modules directory."""
    pkg_dir = Path(root, "node_modules", *package_name.split("/"))
    pkg_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"name": package_name, "version": version}
    _ = (pkg_dir / "package.json").write_text(
        f"{json.dumps(manifest)}\n", encoding="utf-8"
    )


def _setup_stage_binary(
    stage: str | Path,
    bin_name: str,
    package_name: str,
    version: str,
) -> None:
    """Set up simulated binary and package manifest in npm stage."""
    exe = Path(stage, "node_modules", ".bin", bin_name)
    exe.parent.mkdir(parents=True, exist_ok=True)
    _ = exe.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    exe.chmod(MODE_EXECUTABLE)
    _write_package_manifest(stage, package_name, version)


def test_npm_launcher_resolves_latest_and_caches_current_previous_without_network(
    tmp_path: Path,
) -> None:
    """Test npm package resolution caches current and previous versions."""
    home = str(tmp_path)
    calls: list[list[str]] = []

    async def mock_resolve(_pkg: str, _tag: str, _timeout: int) -> str:
        return "1.2.3"

    async def mock_run(
        cmd: Sequence[str],
        _options: RunProcessOptions,
    ) -> ProcessResult:
        command = list(cmd)
        calls.append(command)
        if command and command[0] == "npm":
            stage = command[3]
            await asyncio.to_thread(
                _setup_stage_binary, stage, "demo", "demo-package", "1.2.3"
            )
        return _success()

    runtime = LauncherRuntime(resolve_version=mock_resolve, run=mock_run)
    spec = NpmPackageSpec(tool="demo", package="demo-package", bin="demo")
    options = PreparePackageOptions(
        home=home,
        cache_home=str(tmp_path / "cache"),
        runtime=runtime,
        timeout_ms=DEFAULT_PREPARE_TIMEOUT_MS,
    )

    prepared = asyncio.run(prepare_npm_package(spec, options))
    assert prepared.resolved_version == "1.2.3"
    assert Path(prepared.current_bin).exists()
    target = str(Path(prepared.layout.current_link).readlink())
    assert target.endswith(str(Path("versions") / "1.2.3"))
    assert any("demo-package@1.2.3" in token for c in calls for token in c)

    second = asyncio.run(prepare_npm_package(spec, options))
    assert second.current_bin == prepared.current_bin
    npm_calls = [c for c in calls if c and c[0] == "npm"]
    assert len(npm_calls) == 1


def test_npm_launcher_rotates_previous_and_falls_back_to_last_known_good(
    tmp_path: Path,
) -> None:
    """Test rotating previous link and falling back to last known good."""
    home = str(tmp_path)
    version = "1.0.0"
    fail_install = False
    fail_smoke = False

    async def mock_resolve(_pkg: str, _tag: str, _timeout: int) -> str:
        if version == "offline":
            message = "network unavailable"
            raise RuntimeError(message)
        return version

    async def mock_run(
        cmd: Sequence[str],
        _options: RunProcessOptions,
    ) -> ProcessResult:
        command = list(cmd)
        if command and command[0] == "npm":
            if fail_install:
                return ProcessResult(
                    exit_code=1,
                    stdout="",
                    stderr="registry unavailable",
                    timed_out=False,
                )
            stage = command[3]
            await asyncio.to_thread(
                _setup_stage_binary, stage, "demo", "demo-package", version
            )
        if (
            fail_smoke
            and command
            and command[0].endswith("demo")
            and len(command) > 1
            and command[1] == "--version"
        ):
            return ProcessResult(
                exit_code=1,
                stdout="",
                stderr="smoke failed",
                timed_out=False,
            )
        return _success()

    runtime = LauncherRuntime(resolve_version=mock_resolve, run=mock_run)
    options = PreparePackageOptions(
        home=home,
        cache_home=str(tmp_path / "cache"),
        runtime=runtime,
        timeout_ms=DEFAULT_PREPARE_TIMEOUT_MS,
    )
    spec = NpmPackageSpec(tool="demo", package="demo-package", bin="demo")

    first = asyncio.run(prepare_npm_package(spec, options))
    version = "2.0.0"
    second = asyncio.run(prepare_npm_package(spec, options))
    layout = npm_cache_layout(home, spec, str(tmp_path / "cache"))

    current_target = str(Path(layout.current_link).readlink())
    previous_target = str(Path(layout.previous_link).readlink())
    assert current_target.endswith(str(Path("versions") / "2.0.0"))
    assert previous_target.endswith(str(Path("versions") / "1.0.0"))
    assert Path(first.current_bin).exists()
    assert Path(second.current_bin).exists()

    version = "offline"
    offline = asyncio.run(prepare_npm_package(spec, options))
    assert offline.resolved_version == "2.0.0"
    assert offline.current_bin == second.current_bin
    assert str(Path(layout.current_link).readlink()).endswith(
        str(Path("versions") / "2.0.0")
    )

    version = "3.0.0"
    fail_install = True
    failed_install = asyncio.run(prepare_npm_package(spec, options))
    assert failed_install.resolved_version == "2.0.0"
    assert failed_install.current_bin == second.current_bin

    version = "4.0.0"
    fail_install = False
    fail_smoke = True
    failed_smoke = asyncio.run(prepare_npm_package(spec, options))
    assert failed_smoke.resolved_version == "2.0.0"
    assert failed_smoke.current_bin == second.current_bin


def test_npm_launcher_first_ever_resolution_failure_still_errors(
    tmp_path: Path,
) -> None:
    """Test that first resolution failure raises an error without fallback."""
    home = str(tmp_path)

    async def mock_resolve(_pkg: str, _tag: str, _timeout: int) -> str:
        message = "network unavailable"
        raise RuntimeError(message)

    runtime = LauncherRuntime(resolve_version=mock_resolve)
    spec = NpmPackageSpec(tool="demo", package="demo-package", bin="demo")
    options = PreparePackageOptions(
        home=home,
        cache_home=str(tmp_path / "cache"),
        runtime=runtime,
        timeout_ms=DEFAULT_PREPARE_TIMEOUT_MS,
    )

    with pytest.raises(RuntimeError, match="network unavailable"):
        _ = asyncio.run(prepare_npm_package(spec, options))


def test_npm_launcher_truncates_oversized_install_failure_detail(
    tmp_path: Path,
) -> None:
    """Verify oversized npm install failure output is truncated in the error."""
    home = str(tmp_path)

    async def mock_resolve(_pkg: str, _tag: str, _timeout: int) -> str:
        return "1.0.0"

    async def mock_run(
        _cmd: Sequence[str],
        _options: RunProcessOptions,
    ) -> ProcessResult:
        return ProcessResult(
            exit_code=1,
            stdout="",
            stderr="x" * (MAX_DETAIL_CHARS + 1),
            timed_out=False,
        )

    runtime = LauncherRuntime(resolve_version=mock_resolve, run=mock_run)
    options = PreparePackageOptions(
        home=home,
        cache_home=str(tmp_path / "cache"),
        runtime=runtime,
        timeout_ms=DEFAULT_PREPARE_TIMEOUT_MS,
    )
    spec = NpmPackageSpec(tool="demo", package="demo-package", bin="demo")

    with pytest.raises(RuntimeError) as exc_info:
        _ = asyncio.run(prepare_npm_package(spec, options))
    message = str(exc_info.value)
    assert "npm install failed" in message
    assert message.endswith("…[truncated]")
    assert len(message) < MAX_DETAIL_CHARS + 100


def test_npm_launcher_separates_cache_versions_when_a_harness_changes_package(
    tmp_path: Path,
) -> None:
    """Test distinct package names under same tool id use isolated versions."""
    home = str(tmp_path)
    offline = False
    installs = 0

    async def mock_resolve(_pkg: str, _tag: str, _timeout: int) -> str:
        if offline:
            message = "network unavailable"
            raise RuntimeError(message)
        return "1.0.0"

    async def mock_run(
        cmd: Sequence[str],
        _options: RunProcessOptions,
    ) -> ProcessResult:
        nonlocal installs
        command = list(cmd)
        if command and command[0] == "npm":
            installs += 1
            stage = command[3]
            package_spec = command[-1]
            package_name = package_spec[: package_spec.rfind("@")]
            await asyncio.to_thread(
                _setup_stage_binary, stage, "demo", package_name, "1.0.0"
            )
        return _success()

    runtime = LauncherRuntime(resolve_version=mock_resolve, run=mock_run)
    options = PreparePackageOptions(
        home=home,
        cache_home=str(tmp_path / "cache"),
        runtime=runtime,
        timeout_ms=DEFAULT_PREPARE_TIMEOUT_MS,
    )

    first = asyncio.run(
        prepare_npm_package(
            NpmPackageSpec(tool="demo", package="package-a", bin="demo"),
            options,
        )
    )
    second = asyncio.run(
        prepare_npm_package(
            NpmPackageSpec(tool="demo", package="package-b", bin="demo"),
            options,
        )
    )
    offline = True
    restored = asyncio.run(
        prepare_npm_package(
            NpmPackageSpec(tool="demo", package="package-a", bin="demo"),
            options,
        )
    )

    assert installs == EXPECTED_INSTALLS
    assert first.layout.versions_dir != second.layout.versions_dir
    assert "packages" in second.layout.versions_dir
    assert Path(second.current_bin).exists()
    assert restored.current_bin == first.current_bin
    assert restored.resolved_version == "1.0.0"


def test_harness_launch_plans_exec_of_cached_binary_with_arguments(
    tmp_path: Path,
) -> None:
    """Harness launch plans an exec of the prepared binary with forwarded args."""
    home = str(tmp_path)
    (tmp_path / "src" / "agents" / "harnesses" / "codex").mkdir(
        parents=True, exist_ok=True
    )

    async def mock_resolve(_pkg: str, _tag: str, _timeout: int) -> str:
        return "1.0.0"

    async def mock_run(
        cmd: Sequence[str],
        _options: RunProcessOptions,
    ) -> ProcessResult:
        command = list(cmd)
        if command and command[0] == "npm":
            stage = command[3]
            await asyncio.to_thread(
                _setup_stage_binary, stage, "codex", "@openai/codex", "1.0.0"
            )
        return _success()

    runtime = LauncherRuntime(resolve_version=mock_resolve, run=mock_run)
    sync_env = SyncEnv.from_home(home, DEFAULT_PREPARE_TIMEOUT_MS, platform="linux")
    harness = next(c for c in sync_env.harnesses if c.source_name == "codex")

    plan = asyncio.run(launch_harness(sync_env, harness, ["--help", "hello"], runtime))

    assert plan.executable.endswith("current/node_modules/.bin/codex")
    assert plan.args == ("--help", "hello")
    assert plan.env["PATH"] == os.environ["PATH"]


def test_harness_launch_merges_root_env_parent_env_and_adapter_env_with_precedence(
    tmp_path: Path,
) -> None:
    """Test env resolution merges root, parent, and adapter environments."""
    home = str(tmp_path)
    root_key_only = "AGENTS_SYNC_TEST_ROOT_ONLY_VAR"
    parent_key_override = "AGENTS_SYNC_TEST_PARENT_OVERRIDE_VAR"
    adapter_collision_key = "AGENTS_SYNC_TEST_ADAPTER_COLLISION_VAR"

    agents_home = tmp_path / "src" / "agents"
    (agents_home / "harnesses" / "codex").mkdir(parents=True, exist_ok=True)
    env_content = "\n".join(
        [
            f"{root_key_only}=root_default_val",
            f"{parent_key_override}=root_ignored_val",
            f"{adapter_collision_key}=root_val_overridden_by_adapter",
        ]
    )
    _ = (agents_home / ".env").write_text(f"{env_content}\n", encoding="utf-8")

    code = f"""
import asyncio
import os
from dataclasses import replace
from pathlib import Path
from sync.core.harness import SyncEnv
from sync.core.launcher import launch_harness, LauncherRuntime
from sync.runtime.process import ProcessResult, RunProcessOptions

async def main():
    async def mock_resolve(pkg, tag, timeout):
        return "1.0.0"

    async def mock_run(cmd, options):
        command = list(cmd)
        if command and command[0] == "npm":
            stage = command[3]
            exe = Path(stage, "node_modules", ".bin", "codex")
            exe.parent.mkdir(parents=True, exist_ok=True)
            exe.write_text("#!/bin/sh\\nexit 0\\n", encoding="utf-8")
            exe.chmod(0o755)
            pkg_dir = Path(stage, "node_modules", "@openai", "codex")
            pkg_dir.mkdir(parents=True, exist_ok=True)
            (pkg_dir / "package.json").write_text(
                '{{"name": "@openai/codex", "version": "1.0.0"}}\\n',
                encoding="utf-8"
            )
        return ProcessResult(exit_code=0, stdout="", stderr="", timed_out=False)

    runtime = LauncherRuntime(resolve_version=mock_resolve, run=mock_run)
    sync_env = SyncEnv.from_home({home!r}, 1000, platform="linux")
    base_harness = next(
        c for c in sync_env.harnesses if c.source_name == "codex"
    )
    launcher_with_env = replace(
        base_harness.launcher,
        env={{{adapter_collision_key!r}: "adapter_wins"}},
    )
    harness = replace(base_harness, launcher=launcher_with_env)

    plan = await launch_harness(sync_env, harness, [], runtime)
    assert plan.env[{root_key_only!r}] == "root_default_val"
    assert plan.env[{parent_key_override!r}] == "parent_value"
    assert plan.env[{adapter_collision_key!r}] == "adapter_wins"

asyncio.run(main())
"""

    sub_env = {
        **os.environ,
        "HOME": home,
        parent_key_override: "parent_value",
    }
    proc = asyncio.run(
        run_process(
            [sys.executable, "-c", code],
            RunProcessOptions(env=sub_env),
        )
    )
    assert proc.exit_code == 0, f"Subprocess failed:\n{proc.stderr}"


def test_static_release_prepares_verifies_and_reuses_cache(tmp_path: Path) -> None:
    """Verify a static release is downloaded, verified, linked, and cached."""
    bundle = tmp_path / "bundle.tar.gz"
    sha256 = _make_release_bundle(bundle, tmp_path / "stage")
    downloads: list[str] = []

    def fetch_manifest(_url: str, _timeout_ms: int) -> StaticReleaseManifest:
        return _release_manifest(sha256)

    def download(_url: str, destination: str, _timeout_ms: int) -> None:
        downloads.append(destination)
        _ = shutil.copyfile(bundle, destination)

    runtime = ReleaseRuntime(
        arch="x86_64",
        platform="linux",
        fetch_manifest=fetch_manifest,
        download=download,
    )

    first = asyncio.run(
        prepare_static_release(
            _release_spec(), str(tmp_path), DEFAULT_PREPARE_TIMEOUT_MS, runtime
        )
    )
    assert first.version == RELEASE_VERSION
    executable = Path(first.executable)
    assert executable.is_file()
    assert executable.parent.name == "bin"
    install_root = tmp_path / ".local" / "share" / "devin" / "cli"
    version_dir = install_root / "_versions" / RELEASE_VERSION
    assert (install_root / "_versions" / "current").is_symlink()
    assert (install_root / "_versions" / "current").resolve() == version_dir.resolve()
    assert (version_dir / "distribution").read_text(encoding="utf-8") == "curl-bash\n"
    assert (version_dir / "share" / "devin" / "docs" / "index.mdx").is_file()
    man_link = tmp_path / ".local" / "share" / "man" / "man1" / "devin.1"
    assert man_link.is_symlink()
    assert (
        man_link.resolve()
        == (version_dir / "share" / "man" / "man1" / "devin.1").resolve()
    )
    assert len(downloads) == 1

    second = asyncio.run(
        prepare_static_release(
            _release_spec(), str(tmp_path), DEFAULT_PREPARE_TIMEOUT_MS, runtime
        )
    )
    assert second.executable == first.executable
    assert len(downloads) == 1


def test_static_release_prunes_stale_owned_man_links(tmp_path: Path) -> None:
    """Verify stale owned man links are removed while unrelated links survive."""
    bundle = tmp_path / "bundle.tar.gz"
    sha256 = _make_release_bundle(bundle, tmp_path / "stage")

    def fetch_manifest(_url: str, _timeout_ms: int) -> StaticReleaseManifest:
        return _release_manifest(sha256)

    def download(_url: str, destination: str, _timeout_ms: int) -> None:
        _ = shutil.copyfile(bundle, destination)

    runtime = ReleaseRuntime(
        arch="x86_64",
        platform="linux",
        fetch_manifest=fetch_manifest,
        download=download,
    )
    _ = asyncio.run(
        prepare_static_release(
            _release_spec(), str(tmp_path), DEFAULT_PREPARE_TIMEOUT_MS, runtime
        )
    )

    man_dir = tmp_path / ".local" / "share" / "man" / "man1"
    install_root = tmp_path / ".local" / "share" / "devin" / "cli"
    stale = man_dir / "devin-stale.1"
    stale.symlink_to(
        install_root / "_versions" / "current" / "share" / "man" / "man1" / stale.name
    )
    unrelated_target = tmp_path / "other.1"
    _ = unrelated_target.write_text(".TH other 1\n", encoding="utf-8")
    unrelated = man_dir / "other.1"
    unrelated.symlink_to(unrelated_target)

    _ = asyncio.run(
        prepare_static_release(
            _release_spec(), str(tmp_path), DEFAULT_PREPARE_TIMEOUT_MS, runtime
        )
    )

    assert not stale.exists()
    assert unrelated.is_symlink()
    assert unrelated.resolve() == unrelated_target.resolve()


def test_static_release_falls_back_to_cached_install(tmp_path: Path) -> None:
    """Verify a failed manifest lookup reuses the current cached install."""
    bundle = tmp_path / "bundle.tar.gz"
    sha256 = _make_release_bundle(bundle, tmp_path / "stage")

    def ok_fetch(_url: str, _timeout_ms: int) -> StaticReleaseManifest:
        return _release_manifest(sha256)

    def download(_url: str, destination: str, _timeout_ms: int) -> None:
        _ = shutil.copyfile(bundle, destination)

    install_runtime = ReleaseRuntime(
        arch="x86_64",
        platform="linux",
        fetch_manifest=ok_fetch,
        download=download,
    )
    first = asyncio.run(
        prepare_static_release(
            _release_spec(), str(tmp_path), DEFAULT_PREPARE_TIMEOUT_MS, install_runtime
        )
    )

    def fail_fetch(_url: str, _timeout_ms: int) -> StaticReleaseManifest:
        message = "network down"
        raise RuntimeError(message)

    offline_runtime = ReleaseRuntime(
        arch="x86_64", platform="linux", fetch_manifest=fail_fetch
    )
    cached = asyncio.run(
        prepare_static_release(
            _release_spec(), str(tmp_path), DEFAULT_PREPARE_TIMEOUT_MS, offline_runtime
        )
    )
    assert cached.version == first.version
    assert cached.executable == first.executable


@pytest.mark.parametrize(
    "target",
    ["../../../../outside/9.9.9", "nested/9.9.9", ".stage-incomplete", "9.9.9\n"],
)
def test_static_release_rejects_unmanaged_fallback(tmp_path: Path, target: str) -> None:
    """Reject executable caches outside a direct, valid version directory."""
    release = _release_spec()
    versions = tmp_path.joinpath(*release.install_segments, "_versions")
    binary = (versions / target).joinpath(*release.executable_segments)
    binary.parent.mkdir(parents=True)
    _ = binary.write_text("#!/bin/sh\n", encoding="utf-8")
    binary.chmod(MODE_EXECUTABLE)
    (versions / "current").symlink_to(target)

    def fail_fetch(_url: str, _timeout_ms: int) -> StaticReleaseManifest:
        message = "network down"
        raise RuntimeError(message)

    with pytest.raises(RuntimeError, match="network down"):
        _ = asyncio.run(
            prepare_static_release(
                release,
                str(tmp_path),
                DEFAULT_PREPARE_TIMEOUT_MS,
                ReleaseRuntime(fetch_manifest=fail_fetch),
            )
        )


@pytest.mark.parametrize("entry", ["current", "9.9.9", "9.9.9/bin/devin"])
@pytest.mark.parametrize("destination", ["outside", "missing", "loop"])
def test_static_release_rejects_escaping_or_broken_links(
    tmp_path: Path, entry: str, destination: str
) -> None:
    """Reject symlink escapes and preserve lookup errors for broken caches."""
    release = _release_spec()
    versions = tmp_path.joinpath(*release.install_segments, "_versions")
    versions.mkdir(parents=True)
    if entry != "current":
        (versions / "current").symlink_to(RELEASE_VERSION)
    link = versions / entry
    link.parent.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside" / RELEASE_VERSION
    binary = outside if entry.endswith("devin") else outside / "bin" / "devin"
    binary.parent.mkdir(parents=True)
    _ = binary.write_text("#!/bin/sh\n", encoding="utf-8")
    binary.chmod(MODE_EXECUTABLE)
    target = outside if destination == "outside" else link
    link.symlink_to(tmp_path / "missing" if destination == "missing" else target)

    def fail_fetch(_url: str, _timeout_ms: int) -> StaticReleaseManifest:
        message = "network down"
        raise RuntimeError(message)

    with pytest.raises(RuntimeError, match="network down"):
        _ = asyncio.run(
            prepare_static_release(
                release,
                str(tmp_path),
                DEFAULT_PREPARE_TIMEOUT_MS,
                ReleaseRuntime(fetch_manifest=fail_fetch),
            )
        )


def test_static_release_rotates_previous_link(tmp_path: Path) -> None:
    """Verify a version change rotates current to previous."""
    first_hash = _make_release_bundle(tmp_path / "first.tar.gz", tmp_path / "stage-one")
    second_hash = _make_release_bundle(
        tmp_path / "second.tar.gz", tmp_path / "stage-two"
    )
    state: dict[str, str] = {
        "version": RELEASE_VERSION,
        "hash": first_hash,
        "bundle": str(tmp_path / "first.tar.gz"),
    }

    def fetch_manifest(_url: str, _timeout_ms: int) -> StaticReleaseManifest:
        return StaticReleaseManifest(
            version=state["version"],
            platforms={
                RELEASE_TARGET: StaticReleaseAsset(
                    url="https://example.test/bundle.tar.gz",
                    sha256=state["hash"],
                )
            },
        )

    def download(_url: str, destination: str, _timeout_ms: int) -> None:
        _ = shutil.copyfile(state["bundle"], destination)

    runtime = ReleaseRuntime(
        arch="x86_64",
        platform="linux",
        fetch_manifest=fetch_manifest,
        download=download,
    )
    _ = asyncio.run(
        prepare_static_release(
            _release_spec(), str(tmp_path), DEFAULT_PREPARE_TIMEOUT_MS, runtime
        )
    )

    state["version"] = "10.0.0"
    state["hash"] = second_hash
    state["bundle"] = str(tmp_path / "second.tar.gz")
    updated = asyncio.run(
        prepare_static_release(
            _release_spec(), str(tmp_path), DEFAULT_PREPARE_TIMEOUT_MS, runtime
        )
    )
    assert updated.version == "10.0.0"
    versions_dir = tmp_path / ".local" / "share" / "devin" / "cli" / "_versions"
    previous = (versions_dir / "previous").resolve()
    current = (versions_dir / "current").resolve()
    assert previous == (versions_dir / RELEASE_VERSION).resolve()
    assert current == (versions_dir / "10.0.0").resolve()


def test_static_release_missing_platform_asset_raises(tmp_path: Path) -> None:
    """Verify a manifest missing the host platform fails with context."""

    def fetch_manifest(_url: str, _timeout_ms: int) -> StaticReleaseManifest:
        return StaticReleaseManifest(version=RELEASE_VERSION, platforms={})

    runtime = ReleaseRuntime(
        arch="x86_64", platform="linux", fetch_manifest=fetch_manifest
    )

    with pytest.raises(RuntimeError, match="missing platform"):
        _ = asyncio.run(
            prepare_static_release(
                _release_spec(), str(tmp_path), DEFAULT_PREPARE_TIMEOUT_MS, runtime
            )
        )


def test_static_release_harness_launch_dispatches_prepared_binary(
    tmp_path: Path,
) -> None:
    """Verify launch_harness prepares and forwards arguments to the release binary."""
    bundle = tmp_path / "bundle.tar.gz"
    sha256 = _make_release_bundle(bundle, tmp_path / "stage")

    def fetch_manifest(_url: str, _timeout_ms: int) -> StaticReleaseManifest:
        return _release_manifest(sha256)

    def download(_url: str, destination: str, _timeout_ms: int) -> None:
        _ = shutil.copyfile(bundle, destination)

    runtime = ReleaseRuntime(
        arch="x86_64",
        platform="linux",
        fetch_manifest=fetch_manifest,
        download=download,
    )

    home = str(tmp_path)
    (tmp_path / "src" / "agents" / "harnesses" / "devin").mkdir(
        parents=True, exist_ok=True
    )
    sync_env = SyncEnv.from_home(home, DEFAULT_PREPARE_TIMEOUT_MS, platform="linux")
    harness = next(c for c in sync_env.harnesses if c.source_name == "devin")
    assert isinstance(harness.launcher, StaticReleaseLauncher)

    plan = asyncio.run(
        launch_harness(sync_env, harness, ["--help"], release_runtime=runtime)
    )
    assert plan.args == ("--help",)
    assert plan.executable.endswith("bin/devin")


def test_tool_launcher_launch_uses_the_registered_npm_spec(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test tool launcher resolution uses registered npm spec and arguments."""
    home = str(tmp_path)
    # Isolate the npm cache from the real XDG cache so a previously cached
    # mcporter does not make the install (and its recorded npm call) a no-op.
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    tool = tool_launcher("mcporter")
    assert tool is not None
    calls: list[list[str]] = []

    async def mock_resolve(_pkg: str, _tag: str, _timeout: int) -> str:
        return "1.0.0"

    async def mock_run(
        cmd: Sequence[str],
        _options: RunProcessOptions,
    ) -> ProcessResult:
        command = list(cmd)
        calls.append(command)
        if command and command[0] == "npm":
            stage = command[3]
            await asyncio.to_thread(
                _setup_stage_binary, stage, "mcporter", "mcporter", "1.0.0"
            )
        return _success()

    runtime = LauncherRuntime(resolve_version=mock_resolve, run=mock_run)
    sync_env = SyncEnv.from_home(home, DEFAULT_PREPARE_TIMEOUT_MS, platform="linux")
    assert tool.package == "mcporter"
    assert tool.bin == "mcporter"

    plan = asyncio.run(
        launch_npm_package(
            sync_env,
            NpmPackageSpec(tool=tool.id, package=tool.package, bin=tool.bin),
            ["list"],
            runtime,
        )
    )
    assert plan.executable.endswith("current/node_modules/.bin/mcporter")
    assert plan.args == ("list",)
    assert any(
        c and c[0] == "npm" and "mcporter@1.0.0" in token for c in calls for token in c
    )

    summarize = tool_launcher("summarize")
    assert summarize is not None
    assert summarize.package == "@steipete/summarize"
    assert summarize.bin == "summarize"
    assert summarize.default_args == (
        "--force-summary",
        "--timestamps",
        "--format",
        "md",
        "--retries",
        "2",
        "--metrics",
        "detailed",
    )
    paseo = tool_launcher("paseo")
    assert paseo is not None
    assert paseo.package == "@getpaseo/cli"
    assert paseo.bin == "paseo"
    assert paseo.default_args == ()
    assert tool_launcher("codex") is None


def test_npm_launcher_rejects_unmanaged_conflict_for_current_and_previous(
    tmp_path: Path,
) -> None:
    """Test unmanaged non-symlink file in cache link path raises RuntimeError."""
    home = str(tmp_path)
    spec = NpmPackageSpec(tool="demo", package="demo-package", bin="demo")
    layout = npm_cache_layout(home, spec, str(tmp_path / "cache"))
    version_dir = Path(layout.versions_dir) / "1.0.0"
    version_dir.mkdir(parents=True, exist_ok=True)
    Path(layout.current_link).symlink_to(Path("versions") / "1.0.0")
    _ = Path(layout.previous_link).write_text("real file", encoding="utf-8")

    async def mock_resolve(_pkg: str, _tag: str, _timeout: int) -> str:
        return "1.2.3"

    async def mock_run(
        cmd: Sequence[str],
        _options: RunProcessOptions,
    ) -> ProcessResult:
        command = list(cmd)
        if command and command[0] == "npm":
            stage = command[3]
            await asyncio.to_thread(
                _setup_stage_binary, stage, "demo", "demo-package", "1.2.3"
            )
        return _success()

    runtime = LauncherRuntime(resolve_version=mock_resolve, run=mock_run)
    options = PreparePackageOptions(
        home=home,
        cache_home=str(tmp_path / "cache"),
        runtime=runtime,
        timeout_ms=DEFAULT_PREPARE_TIMEOUT_MS,
    )

    with pytest.raises(RuntimeError, match="unmanaged conflict"):
        _ = asyncio.run(prepare_npm_package(spec, options))


def _prepare_versions(
    tmp_path: Path,
    versions: Sequence[str],
    running: Callable[[], Awaitable[set[Path] | None]],
) -> Path:
    """Prepare each version in order and return the package versions directory."""
    version = versions[0]

    async def mock_resolve(_pkg: str, _tag: str, _timeout: int) -> str:
        return version

    async def mock_run(
        cmd: Sequence[str],
        _options: RunProcessOptions,
    ) -> ProcessResult:
        command = list(cmd)
        if command and command[0] == "npm":
            await asyncio.to_thread(
                _setup_stage_binary, command[3], "demo", "demo-package", version
            )
        return _success()

    spec = NpmPackageSpec(tool="demo", package="demo-package", bin="demo")
    options = PreparePackageOptions(
        home=str(tmp_path),
        cache_home=str(tmp_path / "cache"),
        runtime=LauncherRuntime(
            resolve_version=mock_resolve,
            run=mock_run,
            running_executables=running,
        ),
        timeout_ms=DEFAULT_PREPARE_TIMEOUT_MS,
    )
    for version in versions:  # noqa: B007 - read by mock_resolve and mock_run
        _ = asyncio.run(prepare_npm_package(spec, options))
    layout = npm_cache_layout(str(tmp_path), spec, str(tmp_path / "cache"))
    return Path(layout.versions_dir)


def _version_names(versions_dir: Path) -> set[str]:
    return {p.name for p in versions_dir.iterdir() if not p.name.startswith(".")}


def test_npm_prune_keeps_a_version_whose_executable_is_still_running(
    tmp_path: Path,
) -> None:
    """A long-lived process keeps its version after two newer versions land."""
    versions_dir = tmp_path / "cache" / "npm-tools" / "demo"
    in_use: set[Path] = set()

    async def running() -> set[Path] | None:
        return in_use

    # 1.0.0 keeps running, like a runner started before two updates land.
    _ = _prepare_versions(tmp_path, ["1.0.0"], running)
    runner_bin = next(versions_dir.rglob("1.0.0/node_modules/.bin/demo")).resolve()
    in_use.add(runner_bin)
    versions = _prepare_versions(tmp_path, ["2.0.0", "3.0.0"], running)
    assert _version_names(versions) == {"1.0.0", "2.0.0", "3.0.0"}

    # Once it stops running, the next prune removes it like any stale version.
    in_use.clear()
    versions = _prepare_versions(tmp_path, ["4.0.0"], running)
    assert _version_names(versions) == {"3.0.0", "4.0.0"}


def test_npm_prune_removes_stages_left_by_dead_installers(tmp_path: Path) -> None:
    """A killed installer's stage is reclaimed; a live installer's stage is kept."""

    async def running() -> set[Path] | None:
        return set()

    versions_dir = _prepare_versions(tmp_path, ["1.0.0"], running)
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    _ = dead.wait()
    orphan = versions_dir / f".stage-{dead.pid}-deadbeef"
    live = versions_dir / f".stage-{os.getpid()}-cafef00d"
    for stage in (orphan, live):
        (stage / "node_modules").mkdir(parents=True)

    versions = _prepare_versions(tmp_path, ["2.0.0"], running)

    assert not orphan.exists()
    assert live.is_dir()
    assert _version_names(versions) == {"1.0.0", "2.0.0"}


def test_npm_install_reclaims_dead_stages_before_staging(tmp_path: Path) -> None:
    """Stages left by killed installers are freed even when every install fails.

    An installer killed mid-install never reaches its cleanup or a successful
    prune; without reclaiming first, each failed attempt adds another stage.
    """
    spec = NpmPackageSpec(tool="demo", package="demo-package", bin="demo")
    layout = npm_cache_layout(str(tmp_path), spec, str(tmp_path / "cache"))
    versions_dir = Path(layout.versions_dir)
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    _ = dead.wait()
    orphan = versions_dir / f".stage-{dead.pid}-deadbeef"
    (orphan / "node_modules").mkdir(parents=True)
    seen: list[bool] = []

    async def mock_resolve(_pkg: str, _tag: str, _timeout: int) -> str:
        return "1.0.0"

    async def failing_install(
        _cmd: Sequence[str], _options: RunProcessOptions
    ) -> ProcessResult:
        seen.append(orphan.exists())
        return ProcessResult(exit_code=1, stdout="", stderr="", timed_out=False)

    options = PreparePackageOptions(
        home=str(tmp_path),
        cache_home=str(tmp_path / "cache"),
        runtime=LauncherRuntime(resolve_version=mock_resolve, run=failing_install),
        timeout_ms=DEFAULT_PREPARE_TIMEOUT_MS,
    )
    with pytest.raises(RuntimeError):
        _ = asyncio.run(prepare_npm_package(spec, options))

    assert seen == [False]
    assert not orphan.exists()


def test_npm_prune_keeps_every_version_when_running_processes_are_unknown(
    tmp_path: Path,
) -> None:
    """If running executables cannot be listed, nothing is deleted."""

    async def unknown() -> set[Path] | None:
        return None

    versions = _prepare_versions(tmp_path, ["1.0.0", "2.0.0", "3.0.0"], unknown)
    assert _version_names(versions) == {"1.0.0", "2.0.0", "3.0.0"}


def test_running_executables_lists_a_running_child_on_the_host_platform() -> None:
    """The real detector sees a child process by the image the kernel reports.

    The expected path comes from the kernel (``/proc/<pid>/exe`` on Linux, the
    child's own lsof ``txt`` mapping on macOS), not from ``sys.executable``:
    framework Python builds on macOS re-exec into ``Python.app``, so the
    interpreter path differs from the image that actually runs.
    """
    script = "import time; time.sleep(30)"
    child = subprocess.Popen([sys.executable, "-c", script])  # noqa: S603 - this interpreter
    try:
        running = asyncio.run(running_executables())
        expected = _child_image(child.pid)
    finally:
        child.kill()
        _ = child.wait()
    assert running is not None
    assert expected in running


def _child_image(pid: int) -> Path:
    """Return the executable image the kernel reports for ``pid``."""
    proc_exe = Path(f"/proc/{pid}/exe")
    if proc_exe.exists():
        return Path(os.path.realpath(proc_exe))
    listing = subprocess.run(  # noqa: S603 - fixed lsof invocation in tests
        ["lsof", "-n", "-w", "-a", "-p", str(pid), "-d", "txt", "-Fn"],  # noqa: S607 - lsof from PATH
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    first = next(line[1:] for line in listing.splitlines() if line.startswith("n/"))
    return Path(os.path.realpath(first))
