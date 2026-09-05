# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for harness definitions and SyncEnv environment loading."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sync.cli import EXIT_USAGE, main
from sync.core.harness import (
    RootEnvReadError,
    SyncEnv,
    assert_path_component,
    load_root_env,
)

if TYPE_CHECKING:
    from pathlib import Path

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
    (agents_home / ".env").write_text("\n".join(env_lines), encoding="utf-8")

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
        SyncEnv.from_home(str(tmp_path), TEST_TIMEOUT_MS, platform="linux")

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
        load_root_env(str(bad_env_path))

    assert exc_info.value.path == str(bad_env_path)
    assert "failed to read root environment file" in str(exc_info.value)


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
