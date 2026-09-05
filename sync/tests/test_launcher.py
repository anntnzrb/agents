# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for npm package resolution, caching, and launcher subprocess dispatch."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Final

import pytest

from sync.core.harness import SyncEnv
from sync.core.launcher import (
    LauncherRuntime,
    NpmPackageSpec,
    PreparePackageOptions,
    launch_harness,
    launch_npm_package,
    npm_cache_layout,
    prepare_npm_package,
)
from sync.core.tool_launchers import tool_launcher
from sync.runtime.process import ProcessResult, RunProcessOptions, run_process

if TYPE_CHECKING:
    from collections.abc import Sequence

EXPECTED_INSTALLS: Final[int] = 2
EXPECTED_LAUNCH_EXIT_CODE: Final[int] = 7
EXPECTED_TOOL_EXIT_CODE: Final[int] = 3
DEFAULT_PREPARE_TIMEOUT_MS: Final[int] = 1000
MODE_EXECUTABLE: Final[int] = 0o755


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


def test_interactive_harness_launch_is_unbounded_and_keeps_arguments(
    tmp_path: Path,
) -> None:
    """Test interactive harness launch passes arguments with unbounded timeout."""
    home = str(tmp_path)
    (tmp_path / ".config" / "agents" / "harnesses" / "codex").mkdir(
        parents=True, exist_ok=True
    )
    calls: list[tuple[list[str], float | None, str]] = []

    async def mock_resolve(_pkg: str, _tag: str, _timeout: int) -> str:
        return "1.0.0"

    async def mock_run(
        cmd: Sequence[str],
        options: RunProcessOptions,
    ) -> ProcessResult:
        command = list(cmd)
        calls.append((command, options.timeout_ms, options.stdio))
        if command and command[0] == "npm":
            stage = command[3]
            await asyncio.to_thread(
                _setup_stage_binary, stage, "codex", "@openai/codex", "1.0.0"
            )
        if (
            command
            and command[0].endswith("codex")
            and len(command) > 1
            and command[1] == "--help"
        ):
            return ProcessResult(
                exit_code=EXPECTED_LAUNCH_EXIT_CODE,
                stdout="",
                stderr="",
                timed_out=False,
            )
        return _success()

    runtime = LauncherRuntime(resolve_version=mock_resolve, run=mock_run)
    sync_env = SyncEnv.from_home(home, DEFAULT_PREPARE_TIMEOUT_MS, platform="linux")
    harness = next(c for c in sync_env.harnesses if c.source_name == "codex")

    exit_code = asyncio.run(
        launch_harness(sync_env, harness, ["--help", "hello"], runtime)
    )
    assert exit_code == EXPECTED_LAUNCH_EXIT_CODE
    launch_call = calls[-1]
    assert launch_call[0][-2:] == ["--help", "hello"]
    assert launch_call[1] is None
    assert launch_call[2] == "inherit"


def test_harness_launch_merges_root_env_parent_env_and_adapter_env_with_precedence(
    tmp_path: Path,
) -> None:
    """Test env resolution merges root, parent, and adapter environments."""
    home = str(tmp_path)
    root_key_only = "AGENTS_SYNC_TEST_ROOT_ONLY_VAR"
    parent_key_override = "AGENTS_SYNC_TEST_PARENT_OVERRIDE_VAR"
    adapter_collision_key = "AGENTS_SYNC_TEST_ADAPTER_COLLISION_VAR"

    agents_home = tmp_path / ".config" / "agents"
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

captured_env = None

async def main():
    global captured_env

    async def mock_resolve(pkg, tag, timeout):
        return "1.0.0"

    async def mock_run(cmd, options):
        global captured_env
        captured_env = options.env
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

    await launch_harness(sync_env, harness, [], runtime)
    assert captured_env is not None
    assert captured_env[{root_key_only!r}] == "root_default_val"
    assert {parent_key_override!r} not in captured_env
    assert captured_env[{adapter_collision_key!r}] == "adapter_wins"

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


def test_tool_launcher_launch_uses_the_registered_npm_spec(
    tmp_path: Path,
) -> None:
    """Test tool launcher resolution uses registered npm spec and arguments."""
    home = str(tmp_path)
    tool = tool_launcher("mcporter")
    assert tool is not None
    calls: list[tuple[list[str], float | None, str]] = []

    async def mock_resolve(_pkg: str, _tag: str, _timeout: int) -> str:
        return "1.0.0"

    async def mock_run(
        cmd: Sequence[str],
        options: RunProcessOptions,
    ) -> ProcessResult:
        command = list(cmd)
        calls.append((command, options.timeout_ms, options.stdio))
        if command and command[0] == "npm":
            stage = command[3]
            await asyncio.to_thread(
                _setup_stage_binary, stage, "mcporter", "mcporter", "1.0.0"
            )
        if (
            command
            and command[0].endswith("mcporter")
            and len(command) > 1
            and command[1] == "list"
        ):
            return ProcessResult(
                exit_code=EXPECTED_TOOL_EXIT_CODE,
                stdout="",
                stderr="",
                timed_out=False,
            )
        return _success()

    runtime = LauncherRuntime(resolve_version=mock_resolve, run=mock_run)
    sync_env = SyncEnv.from_home(home, DEFAULT_PREPARE_TIMEOUT_MS, platform="linux")
    assert tool.package == "mcporter"
    assert tool.bin == "mcporter"

    exit_code = asyncio.run(
        launch_npm_package(
            sync_env,
            NpmPackageSpec(tool=tool.id, package=tool.package, bin=tool.bin),
            ["list"],
            runtime,
        )
    )
    assert exit_code == EXPECTED_TOOL_EXIT_CODE
    launch_call = calls[-1]
    assert launch_call[0][-1:] == ["list"]
    assert launch_call[1] is None
    assert launch_call[2] == "inherit"
    assert any(
        c[0] and c[0][0] == "npm" and "mcporter@1.0.0" in token
        for c in calls
        for token in c[0]
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
