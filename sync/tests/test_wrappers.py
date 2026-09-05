# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for shell wrapper script generation, rendering, and reconciliation."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Final

import pytest

from sync.core.harness import (
    HarnessSpec,
    SyncEnv,
    build_harness,
    supported_harness,
)
from sync.core.harness_adapters import HarnessLauncherSpec
from sync.core.managed_tools import PreparedManagedTool
from sync.core.wrappers import (
    WRAPPER_MARKER,
    WRAPPER_STATE_FILE,
    WrapperState,
    is_managed_wrapper,
    managed_tool_wrapper_destination,
    read_wrapper_state,
    reconcile_wrapper_files,
    reconcile_wrappers,
    wrapper_destinations,
    write_managed_wrapper,
)
from sync.runtime.process import RunProcessOptions, run_process

if TYPE_CHECKING:
    from collections.abc import Sequence

MODE_READ_WRITE: Final[int] = 0o644
MODE_EXECUTABLE: Final[int] = 0o755
EXPECTED_MISSING_RUNTIME_EXIT_CODE: Final[int] = 127
PERMISSION_MASK: Final[int] = 0o777
DEFAULT_SYNC_TIMEOUT_MS: Final[int] = 1000


def _add_harness_sources(
    home: str | Path,
    ids: Sequence[str] = ("codex", "deepseek", "opencode", "pi", "omp"),
) -> None:
    for harness_id in ids:
        Path(home, ".config", "agents", "harnesses", harness_id).mkdir(
            parents=True, exist_ok=True
        )


def test_harnesses_are_discovered_from_known_harness_directories(
    tmp_path: Path,
) -> None:
    """Test discovery of harnesses from configured harness directories."""
    home = str(tmp_path)
    _add_harness_sources(home, ["codex", "opencode"])
    (tmp_path / ".config" / "agents" / "harnesses" / "unrelated").mkdir(
        parents=True, exist_ok=True
    )
    (tmp_path / ".config" / "agents" / "harnesses" / "pi").write_text(
        "not a directory", encoding="utf-8"
    )

    sync_env = SyncEnv.from_home(home, DEFAULT_SYNC_TIMEOUT_MS, platform="linux")
    discovered_sources = [h.source_name for h in sync_env.harnesses]
    assert discovered_sources == ["codex", "opencode"]
    assert sync_env.platform == "linux"


def test_harness_ownership_ids_cannot_escape_the_wrapper_directory() -> None:
    """Validate that harness IDs cannot contain directory traversal characters."""
    with pytest.raises(ValueError, match="invalid harness id"):
        build_harness(
            HarnessSpec(
                id="codex",
                source_name="../codex",
                home="/var/agents/codex",
                launcher=HarnessLauncherSpec(
                    package="@openai/codex",
                    bin="codex",
                ),
            )
        )


def test_installed_runtime_resolves_known_harness_without_ssot(
    tmp_path: Path,
) -> None:
    """Test supported harness resolution when SSOT configuration is absent."""
    home = str(tmp_path)
    assert not (tmp_path / ".config" / "agents").exists()
    deepseek = supported_harness(home, "deepseek", "linux")
    assert deepseek is not None
    assert deepseek.home == str(tmp_path / ".dsh")
    assert deepseek.launcher.package == "@deepseek-ai/dsh"
    assert deepseek.launcher.bin == "dsh"

    pi = supported_harness(home, "pi", "linux")
    assert pi is not None
    assert pi.home == str(tmp_path / ".pi")
    assert supported_harness(home, "unknown", "linux") is None


def test_wrapper_destinations_render_unix_launchers(tmp_path: Path) -> None:
    """Test generation of Unix shell wrapper scripts for harnesses and tools."""
    home = str(tmp_path)
    _add_harness_sources(home)
    unix_env = SyncEnv.from_home(home, DEFAULT_SYNC_TIMEOUT_MS, platform="linux")
    unix = wrapper_destinations(unix_env)

    codex = unix[0]
    assert codex.path == str(tmp_path / ".local" / "bin" / "codex")
    assert codex.content.startswith("#!/bin/sh\n")
    assert WRAPPER_MARKER in codex.content
    assert "launch 'codex'" in codex.content
    assert "exit 127" in codex.content
    assert "sync runtime is missing" in codex.content
    expected_cli_path = str(
        tmp_path
        / ".local"
        / "share"
        / "agents"
        / "sync-current"
        / "src"
        / "sync"
        / "cli.py"
    )
    assert expected_cli_path in codex.content
    assert str(tmp_path / ".config" / "agents") not in codex.content

    # Golden comparison for codex launch wrapper
    golden_path = Path(__file__).parent / "golden" / "wrapper-launch.sh"
    if golden_path.exists():
        expected_content = (
            golden_path.read_text(encoding="utf-8")
            .replace("<runtimeHome>", unix_env.runtime_home)
            .replace("<sourceName>", "codex")
        )
        assert codex.content == expected_content

    deepseek_unix = next((e for e in unix if e.path.endswith("/dsh")), None)
    assert deepseek_unix is not None
    assert deepseek_unix.path == str(tmp_path / ".local" / "bin" / "dsh")
    assert "launch 'deepseek'" in deepseek_unix.content

    mcporter_unix = next((e for e in unix if e.path.endswith("/mcporter")), None)
    assert mcporter_unix is not None
    assert mcporter_unix.path == str(tmp_path / ".local" / "bin" / "mcporter")
    assert "launch 'mcporter'" in mcporter_unix.content
    mcporter_json = str(tmp_path / ".mcporter" / "mcporter.json")
    expected_mcporter_cfg = f"'--config' '{mcporter_json}'"
    assert expected_mcporter_cfg in mcporter_unix.content
    assert WRAPPER_MARKER in mcporter_unix.content

    summarize_unix = next((e for e in unix if e.path.endswith("/summarize")), None)
    assert summarize_unix is not None
    assert summarize_unix.path == str(tmp_path / ".local" / "bin" / "summarize")
    assert "launch 'summarize'" in summarize_unix.content
    summarize_args = (
        "'--force-summary' '--timestamps' '--format' 'md' "
        "'--retries' '2' '--metrics' 'detailed'"
    )
    assert summarize_args in summarize_unix.content
    assert WRAPPER_MARKER in summarize_unix.content


def test_generated_wrappers_do_not_embed_root_env_values(
    tmp_path: Path,
) -> None:
    """Test that root environment variables are not leaked into wrapper scripts."""
    home = str(tmp_path)
    _add_harness_sources(home)
    sentinel_key = "SECRET_SENTINEL_ROOT_ENV_KEY"
    sentinel_val = "super_secret_payload_12345"
    agents_home = Path(home, ".config", "agents")
    (agents_home / ".env").write_text(
        f"{sentinel_key}={sentinel_val}\n", encoding="utf-8"
    )
    unix_env = SyncEnv.from_home(home, DEFAULT_SYNC_TIMEOUT_MS, platform="linux")
    assert unix_env.root_env.get(sentinel_key) == sentinel_val

    destinations = wrapper_destinations(unix_env)
    for destination in destinations:
        assert sentinel_key not in destination.content
        assert sentinel_val not in destination.content
        assert "launch" in destination.content


def test_codex_wrapper_defers_sandbox_and_hook_policies_to_config(
    tmp_path: Path,
) -> None:
    """Test codex wrapper defers security policies to runtime configuration."""
    home = str(tmp_path)
    _add_harness_sources(home)
    unix_env = SyncEnv.from_home(home, DEFAULT_SYNC_TIMEOUT_MS, platform="linux")
    destinations = wrapper_destinations(unix_env)
    codex = next((e for e in destinations if e.path.endswith("/codex")), None)
    assert codex is not None
    assert "--dangerously-bypass-approvals-and-sandbox" not in codex.content
    assert "--dangerously-bypass-hook-trust" not in codex.content
    for entry in destinations:
        if entry.path.endswith("/codex"):
            continue
        assert "--dangerously-bypass-approvals-and-sandbox" not in entry.content
        assert "--dangerously-bypass-hook-trust" not in entry.content


def test_managed_tool_wrappers_use_the_cached_binary_and_generated_config(
    tmp_path: Path,
) -> None:
    """Test managed tool wrapper points to cached binary and config path."""
    home = str(tmp_path)
    tool = PreparedManagedTool(
        name="cliproxyapi",
        command="cli-proxy-api",
        executable=str(tmp_path / ".cache" / "cli-proxy-api"),
        version="7.2.132",
        config_path=str(tmp_path / ".cli-proxy-api" / "config.yaml"),
    )
    unix_env = SyncEnv.from_home(home, DEFAULT_SYNC_TIMEOUT_MS, platform="linux")
    unix = managed_tool_wrapper_destination(unix_env, tool)
    assert unix.path == str(tmp_path / ".local" / "bin" / "cli-proxy-api")
    assert tool.executable in unix.content
    assert f"--config '{tool.config_path}'" in unix.content

    # Golden comparison for managed tool wrapper
    golden_path = Path(__file__).parent / "golden" / "wrapper-managed-tool.sh"
    if golden_path.exists():
        expected_content = (
            golden_path.read_text(encoding="utf-8")
            .replace("<executable>", tool.executable)
            .replace("<configPath>", tool.config_path)
        )
        assert unix.content == expected_content


def test_wrapper_reconciliation_is_idempotent_and_removes_owned_stale_entries(
    tmp_path: Path,
) -> None:
    """Test wrapper reconciliation idempotency and cleanup of obsolete wrappers."""
    home = str(tmp_path)
    _add_harness_sources(home)
    sync_env = SyncEnv.from_home(home, DEFAULT_SYNC_TIMEOUT_MS, platform="linux")
    first = reconcile_wrappers(sync_env)
    assert first is True
    destinations = wrapper_destinations(sync_env)
    codex = destinations[0]
    codex_path = Path(codex.path)
    before_stat = codex_path.stat()
    assert codex_path.is_file()
    assert not codex_path.is_symlink()

    assert reconcile_wrappers(sync_env) is True
    after_stat = codex_path.stat()
    assert after_stat.st_ino == before_stat.st_ino
    assert WRAPPER_MARKER in codex_path.read_text(encoding="utf-8")

    without_omp = [e for e in destinations if not e.path.endswith("/omp")]
    result = reconcile_wrapper_files(sync_env, without_omp)
    assert any(e.endswith("/omp") for e in result.removed)
    assert not (tmp_path / ".local" / "bin" / "omp").exists()
    assert (tmp_path / ".local" / "bin" / "codex").exists()
    state_file = Path(sync_env.managed_state_home) / WRAPPER_STATE_FILE
    assert state_file.exists()


def test_wrapper_reconciliation_preserves_unmanaged_conflicts(
    tmp_path: Path,
) -> None:
    """Test wrapper reconciliation does not overwrite unmanaged user scripts."""
    home = str(tmp_path)
    _add_harness_sources(home)
    sync_env = SyncEnv.from_home(home, DEFAULT_SYNC_TIMEOUT_MS, platform="linux")
    destination = wrapper_destinations(sync_env)[0]
    dest_path = Path(destination.path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_text("#!/bin/sh\necho user-owned\n", encoding="utf-8")

    assert reconcile_wrappers(sync_env) is True
    assert dest_path.read_text(encoding="utf-8") == "#!/bin/sh\necho user-owned\n"
    state_file = Path(sync_env.managed_state_home) / WRAPPER_STATE_FILE
    assert destination.path not in state_file.read_text(encoding="utf-8")

    outside = tmp_path / "outside-wrapper"
    outside.write_text(f"# {WRAPPER_MARKER}\n", encoding="utf-8")
    state_file.write_text(
        f"{json.dumps({'version': 1, 'entries': [str(outside)]})}\n",
        encoding="utf-8",
    )
    reconcile_wrapper_files(sync_env, [])
    assert outside.exists()


def test_existing_owned_wrapper_with_mode_0644_and_matching_content_is_updated_to_0755(
    tmp_path: Path,
) -> None:
    """Test non-executable owned wrapper file is updated to executable mode."""
    home = str(tmp_path)
    _add_harness_sources(home)
    sync_env = SyncEnv.from_home(home, DEFAULT_SYNC_TIMEOUT_MS, platform="linux")
    assert reconcile_wrappers(sync_env) is True

    destination = wrapper_destinations(sync_env)[0]
    dest_path = Path(destination.path)
    dest_path.chmod(MODE_READ_WRITE)
    assert dest_path.stat().st_mode & PERMISSION_MASK == MODE_READ_WRITE
    assert reconcile_wrappers(sync_env) is True
    assert dest_path.stat().st_mode & PERMISSION_MASK == MODE_EXECUTABLE


def test_wrapper_execution_in_isolated_home_where_sync_runtime_is_missing_returns_127(
    tmp_path: Path,
) -> None:
    """Test wrapper exits with code 127 when sync runtime CLI is missing."""
    home = str(tmp_path)
    _add_harness_sources(home)
    sync_env = SyncEnv.from_home(home, DEFAULT_SYNC_TIMEOUT_MS, platform="linux")
    assert reconcile_wrappers(sync_env) is True

    destination = wrapper_destinations(sync_env)[0]
    sub_env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": home,
    }
    proc = asyncio.run(
        run_process(
            [destination.path],
            RunProcessOptions(env=sub_env),
        )
    )
    assert proc.exit_code == EXPECTED_MISSING_RUNTIME_EXIT_CODE
    assert "agents: sync runtime is missing" in proc.stderr


def test_is_managed_wrapper_handles_non_utf8_binary_content(
    tmp_path: Path,
) -> None:
    """Test is_managed_wrapper returns False for non-UTF8 binary files."""
    binary_file = tmp_path / "binary_script"
    binary_file.write_bytes(b"\x80\xff\xfe\x00\x01\x80")
    assert is_managed_wrapper(str(binary_file)) is False


def test_write_managed_wrapper_preserves_non_utf8_binary_file_as_conflict(
    tmp_path: Path,
) -> None:
    """Test write_managed_wrapper flags non-UTF8 binary file as conflict."""
    binary_dest = tmp_path / "codex"
    payload = b"\x80\xff\xfe\x00\x01\x80"
    binary_dest.write_bytes(payload)
    status = write_managed_wrapper(str(binary_dest), "#!/bin/sh\n")
    assert status == "conflict"
    assert binary_dest.read_bytes() == payload


def test_wrapper_reconciliation_preserves_non_utf8_conflict_with_warning(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test non-UTF8 wrapper is preserved as conflict and triggers warning."""
    home = str(tmp_path)
    _add_harness_sources(home)
    sync_env = SyncEnv.from_home(home, DEFAULT_SYNC_TIMEOUT_MS, platform="linux")
    destination = wrapper_destinations(sync_env)[0]
    dest_path = Path(destination.path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    payload = b"\x80\xff\xfe\x00\x01\x80"
    dest_path.write_bytes(payload)

    assert reconcile_wrappers(sync_env) is True
    assert dest_path.read_bytes() == payload
    state_file = Path(sync_env.managed_state_home) / WRAPPER_STATE_FILE
    assert destination.path not in state_file.read_text(encoding="utf-8")
    captured = capsys.readouterr()
    assert "preserving unmanaged wrapper conflict" in captured.err


def test_read_wrapper_state_strict_validation(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test read_wrapper_state strictly validates version and entries."""
    state_file = tmp_path / "wrappers.json"

    # 1. Valid state with absolute paths and relative paths filtered out
    state_file.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": ["/bin/codex", "relative/path", "/bin/codex"],
            }
        ),
        encoding="utf-8",
    )
    state = read_wrapper_state(str(state_file))
    assert state == WrapperState(version=1, entries=["/bin/codex"])

    # 2. Version skew (version=2) must be discarded
    state_file.write_text(
        json.dumps({"version": 2, "entries": ["/bin/codex"]}),
        encoding="utf-8",
    )
    state = read_wrapper_state(str(state_file))
    assert state == WrapperState(version=1, entries=[])
    assert "invalid shape" in capsys.readouterr().err

    # 3. Missing version must be discarded
    state_file.write_text(
        json.dumps({"entries": ["/bin/codex"]}),
        encoding="utf-8",
    )
    state = read_wrapper_state(str(state_file))
    assert state == WrapperState(version=1, entries=[])
    assert "invalid shape" in capsys.readouterr().err

    # 4. Non-string entry must be discarded
    state_file.write_text(
        json.dumps({"version": 1, "entries": [123, "/bin/codex"]}),
        encoding="utf-8",
    )
    state = read_wrapper_state(str(state_file))
    assert state == WrapperState(version=1, entries=[])
    assert "invalid shape" in capsys.readouterr().err

    # 5. Non-list entries must be discarded
    state_file.write_text(
        json.dumps({"version": 1, "entries": "not-a-list"}),
        encoding="utf-8",
    )
    state = read_wrapper_state(str(state_file))
    assert state == WrapperState(version=1, entries=[])
    assert "invalid shape" in capsys.readouterr().err

    # 6. Non-UTF8 state file must be discarded
    state_file.write_bytes(b"\x80\xff\xfe\x00")
    state = read_wrapper_state(str(state_file))
    assert state == WrapperState(version=1, entries=[])
    assert "wrapper state parse failed, ignoring" in capsys.readouterr().err
