# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for harness definitions and SyncEnv environment loading."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from sync.cli import EXIT_USAGE, main
from sync.core.harness import (
    DEFAULT_PACKAGE_CACHE_SUBDIR,
    NpmLauncher,
    PackageBootstrapHook,
    RootEnvReadError,
    StaticReleaseLauncher,
    SyncEnv,
    assert_path_component,
    harness_from_adapter,
    load_root_env,
    platform_from_process,
    supported_harness,
)
from sync.core.harness_adapters import (
    HARNESS_ADAPTERS,
    NpmLauncherSpec,
)

if TYPE_CHECKING:
    from pathlib import Path

    from sync.core.harness import HostPlatform

TEST_TIMEOUT_MS: int = 1000


def test_root_env_returns_empty_when_env_file_is_missing(tmp_path: Path) -> None:
    """Test that an absent .env file yields an empty dictionary without error."""
    home = str(tmp_path)
    sync_env = SyncEnv.from_home(home, TEST_TIMEOUT_MS, platform="linux")
    assert sync_env.root_env == {}


def test_root_env_parses_dotenv_contents_with_expected_precedence_and_literals(
    tmp_path: Path,
) -> None:
    """Test .env parsing preserves literals, skips empty keys, and ignores comments."""
    agents_home = tmp_path / ".config" / "agents"
    agents_home.mkdir(parents=True, exist_ok=True)
    env_lines = [
        "# Shared test env",
        'QUOTED_VAL="secret_value # not a comment"',
        "SINGLE_QUOTED='single'",
        "EMPTY_KEY=",
        'EMPTY_QUOTED=""',
        "VARIABLE_REF=${UNEXPANDED_VAR}",
        "DOLLAR_PREFIX=$LITERAL_VAR",
        "NESTED_PREFIX_A=foo",
        "NESTED_PREFIX_B=bar",
        "COMMAND_CODE_API_KEY=",
        "API_KEY=12345",
    ]
    _ = (agents_home / ".env").write_text("\n".join(env_lines), encoding="utf-8")

    sync_env = SyncEnv.from_home(str(tmp_path), TEST_TIMEOUT_MS, platform="linux")
    assert sync_env.root_env == {
        "QUOTED_VAL": "secret_value # not a comment",
        "SINGLE_QUOTED": "single",
        "VARIABLE_REF": "${UNEXPANDED_VAR}",
        "DOLLAR_PREFIX": "$LITERAL_VAR",
        "NESTED_PREFIX_A": "foo",
        "NESTED_PREFIX_B": "bar",
        "API_KEY": "12345",
    }


def test_root_env_throws_when_reading_env_fails_with_non_enoent_error(
    tmp_path: Path,
) -> None:
    """Test that reading a non-file (directory) .env raises RootEnvReadError."""
    agents_home = tmp_path / ".config" / "agents"
    bad_env_path = agents_home / ".env"
    bad_env_path.mkdir(parents=True, exist_ok=True)

    with pytest.raises(RootEnvReadError) as exc_info:
        _ = SyncEnv.from_home(str(tmp_path), TEST_TIMEOUT_MS, platform="linux")

    assert "failed to read root environment file" in str(exc_info.value)
    assert str(bad_env_path) in str(exc_info.value)


def test_load_root_env_returns_tagged_error_when_reading_fails(
    tmp_path: Path,
) -> None:
    """Test load_root_env directly raises RootEnvReadError with the target path."""
    agents_home = tmp_path / ".config" / "agents"
    bad_env_path = agents_home / ".env"
    bad_env_path.mkdir(parents=True, exist_ok=True)

    with pytest.raises(RootEnvReadError) as exc_info:
        _ = load_root_env(str(bad_env_path))

    assert exc_info.value.path == str(bad_env_path)
    assert "failed to read root environment file" in str(exc_info.value)


def test_supported_harness_resolves_devin_static_release(tmp_path: Path) -> None:
    """Verify the devin adapter resolves a static release launcher and merge file."""
    devin = supported_harness(str(tmp_path), "devin", "linux")
    assert devin is not None
    assert devin.home == str(tmp_path / ".config" / "devin")
    assert devin.preserve_json_keys == {
        "config.json": (
            "devin",
            "shell.setup_complete",
            "shell.startup_messages_remaining",
        )
    }
    assert isinstance(devin.launcher, StaticReleaseLauncher)
    assert devin.launcher.bin == "devin"
    assert devin.launcher.release.manifest_url == (
        "https://static.devin.ai/cli/current/manifest.json"
    )
    assert devin.launcher.release.install_segments == (
        ".local",
        "share",
        "devin",
        "cli",
    )
    assert devin.launcher.release.executable_segments == ("bin", "devin")
    assert devin.launcher.release.targets["linux-x64"] == "x86_64-unknown-linux"
    assert devin.launcher.release.targets["darwin-arm64"] == "aarch64-apple-darwin"
    assert devin.launcher.release.man_segments == ("share", "man", "man1")
    assert devin.launcher.release.man_dest_segments == (
        ".local",
        "share",
        "man",
        "man1",
    )


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_supported_harness_resolves_amp_npm_launcher(
    tmp_path: Path,
    platform: HostPlatform,
) -> None:
    """Verify the amp adapter resolves an npm launcher and its config home."""
    amp = supported_harness(str(tmp_path), "amp", platform)
    assert amp is not None
    assert amp.home == str(tmp_path / ".config" / "amp")
    assert isinstance(amp.launcher, NpmLauncher)
    assert amp.launcher.package == "@ampcode/cli"
    assert amp.launcher.bin == "amp"
    assert amp.launcher.dist_tag == "latest"
    assert amp.launcher.default_args == ("--remote-control-terminal",)
    assert amp.instruction_file == "AGENTS.md"
    assert amp.runtime_subdir is None
    assert amp.preserve_json_keys == {}
    assert amp.hooks == ()


def test_assert_path_component_rejects_trailing_newline() -> None:
    """Test that assert_path_component rejects names with trailing newlines."""
    with pytest.raises(ValueError, match=r"invalid harness id: codex\n"):
        assert_path_component("codex\n", "harness id")


def test_cli_launch_empty_name_returns_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test that sync launch with an empty string name returns usage error."""
    exit_code = main(["launch", ""])
    assert exit_code == EXIT_USAGE
    captured = capsys.readouterr()
    assert "sync: usage: launch NAME -- [ARGS...]" in captured.err


def test_harness_from_adapter_applies_launcher_defaults(tmp_path: Path) -> None:
    """Adapter launcher defaults must resolve into concrete launcher values."""
    adapter = next(a for a in HARNESS_ADAPTERS if a.id == "codex")
    harness = harness_from_adapter(adapter, str(tmp_path))
    launcher = harness.launcher
    assert isinstance(launcher, NpmLauncher)
    assert launcher.dist_tag == "latest"
    assert launcher.smoke_check == "--version"
    assert launcher.default_args == ()
    assert launcher.env is None


def test_harness_from_adapter_resolves_callable_launcher_env(tmp_path: Path) -> None:
    """A callable launcher env resolves against the generated harness home."""
    adapter = replace(
        next(a for a in HARNESS_ADAPTERS if a.id == "codex"),
        launcher=NpmLauncherSpec(
            package="@openai/codex",
            bin="codex",
            env=lambda home: {"CODEX_SYNC_HOME": home},
        ),
    )
    harness = harness_from_adapter(adapter, str(tmp_path))
    assert harness.launcher.env == {"CODEX_SYNC_HOME": str(tmp_path / ".codex")}


def test_harness_from_adapter_normalizes_hook_defaults(tmp_path: Path) -> None:
    """Package bootstrap hooks must receive their default files and cache."""
    adapter = replace(
        next(a for a in HARNESS_ADAPTERS if a.id == "pi"),
        hooks=(PackageBootstrapHook(),),
    )
    harness = harness_from_adapter(adapter, str(tmp_path))
    hook = harness.hooks[0]
    assert isinstance(hook, PackageBootstrapHook)
    assert hook.manifest_file == "packages.json"
    assert hook.settings_file == "settings.json"
    assert hook.cache_subdir == DEFAULT_PACKAGE_CACHE_SUBDIR


def test_harness_from_adapter_propagates_declarative_adapter_fields(
    tmp_path: Path,
) -> None:
    """Per-harness cliproxy and python-env declarations reach resolved harnesses."""
    harnesses = {
        adapter.id: harness_from_adapter(adapter, str(tmp_path))
        for adapter in HARNESS_ADAPTERS
    }
    codex = harnesses["codex"]
    assert codex.cliproxy_templates == ("config.toml",)
    assert codex.cliproxy_preserve_top_levels == {
        "config.toml": ("hooks.state", "projects")
    }
    assert codex.python_env_segments is None
    assert harnesses["omp"].python_env_segments == (".omp", "python-env")
    assert harnesses["omp"].cliproxy_templates == ("models.yml",)
    assert harnesses["devin"].cliproxy_templates == ()
    assert harnesses["devin"].cliproxy_preserve_top_levels == {}


def test_harness_from_adapter_defaults_are_independent_per_harness(
    tmp_path: Path,
) -> None:
    """Unset adapter fields must not leak state between resolved harnesses."""
    codex = harness_from_adapter(
        next(a for a in HARNESS_ADAPTERS if a.id == "codex"), str(tmp_path)
    )
    devin = harness_from_adapter(
        next(a for a in HARNESS_ADAPTERS if a.id == "devin"), str(tmp_path)
    )
    assert codex.instruction_file == "AGENTS.md"
    assert devin.instruction_file == "AGENTS.md"
    assert codex.preserve_json_keys == {}
    assert devin.compat_managed_entries == ()
    assert codex.hooks == ()
    # Empty mappings must be allocated per call, not shared between harnesses.
    assert codex.preserve_json_keys is not devin.preserve_json_keys
    assert codex.cliproxy_preserve_top_levels is not devin.cliproxy_preserve_top_levels


def test_harness_from_adapter_treats_empty_segments_as_absent(tmp_path: Path) -> None:
    """An empty python_env_segments tuple must resolve to None, never to the home."""
    adapter = replace(
        next(a for a in HARNESS_ADAPTERS if a.id == "omp"),
        python_env_segments=(),
    )
    harness = harness_from_adapter(adapter, str(tmp_path))
    assert harness.python_env_segments is None


def test_platform_from_process_rejects_unsupported_platform(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sync supports macOS and Linux only; other hosts must fail loudly."""
    monkeypatch.setattr("sync.core.harness.sys.platform", "win32")
    with pytest.raises(RuntimeError, match="unsupported platform: win32"):
        _ = platform_from_process()
