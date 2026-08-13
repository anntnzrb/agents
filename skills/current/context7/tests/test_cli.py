"""Contract tests for the Context7 MCPorter launcher."""
# ruff: noqa: CPY001, INP001, S101

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from types import ModuleType


SCRIPT = Path(__file__).parents[1] / "scripts" / "cli.py"


def load_cli() -> ModuleType:
    """Load the standalone launcher as an isolated module."""
    spec = importlib.util.spec_from_file_location("context7_cli_under_test", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> ModuleType:
    """Load the launcher with credential discovery isolated from the host."""
    monkeypatch.delenv("CONTEXT7_API_KEY", raising=False)
    monkeypatch.delenv("CONTEXT7_ENV_FILE", raising=False)
    monkeypatch.delenv("SKILLS_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    return load_cli()


def test_existing_environment_wins(
    cli: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Keep an inherited credential ahead of dotenv values."""
    env_file = tmp_path / ".env"
    env_file.write_text("CONTEXT7_API_KEY=file-key\n", encoding="utf-8")
    monkeypatch.setenv("CONTEXT7_API_KEY", "inherited-key")
    monkeypatch.setenv("CONTEXT7_ENV_FILE", str(env_file))

    cli.load_env()

    assert os.environ["CONTEXT7_API_KEY"] == "inherited-key"


def test_explicit_env_file_supplies_key(
    cli: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Load credentials from the explicitly selected dotenv file."""
    env_file = tmp_path / ".env"
    env_file.write_text("CONTEXT7_API_KEY='file-key'\n", encoding="utf-8")
    monkeypatch.setenv("CONTEXT7_ENV_FILE", str(env_file))

    cli.load_env()

    assert os.environ["CONTEXT7_API_KEY"] == "file-key"


def test_missing_key_fails_before_exec(
    cli: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Reject execution before MCPorter when no credential is available."""
    monkeypatch.setattr(cli, "load_env", lambda: None)
    monkeypatch.setattr(
        cli,
        "run_mcporter",
        lambda _args: pytest.fail("must not execute MCPorter without a key"),
    )

    assert cli.main(["list", "context7", "--brief"]) == cli.USAGE_ERROR_EXIT
    assert "CONTEXT7_API_KEY required" in capsys.readouterr().err


def test_main_forwards_arguments_after_loading_key(
    cli: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Forward every MCPorter argument and preserve its exit status."""
    forwarded: list[list[str]] = []
    monkeypatch.setenv("CONTEXT7_API_KEY", "test-key")
    expected_exit = 17
    monkeypatch.setattr(
        cli,
        "run_mcporter",
        lambda args: forwarded.append(args) or expected_exit,
    )

    assert cli.main(["list", "context7", "--brief"]) == expected_exit
    assert forwarded == [["list", "context7", "--brief"]]
