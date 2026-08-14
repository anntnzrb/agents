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


CONFIG_WITH_HEADER = """\
{
  "mcpServers": {
    "context7": {
      "description": "Context7 documentation MCP",
      "serverUrl": "https://mcp.context7.com/mcp",
      "headers": {
        "Authorization": "Bearer ${CONTEXT7_API_KEY}",
      },
    },
  },
}
"""

CONFIG_WITHOUT_HEADER = """\
{
  "mcpServers": {
    "context7": {
      "description": "Context7 documentation MCP",
      "serverUrl": "https://mcp.context7.com/mcp",
    },
  },
}
"""


def test_keyless_strips_auth_header_before_forwarding(
    cli: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Forward a header-stripped config copy when no credential is available."""
    config = tmp_path / "mcporter.jsonc"
    config.write_text(CONFIG_WITH_HEADER, encoding="utf-8")
    captured: dict[str, str | list[str]] = {}

    def fake_run(args: list[str]) -> int:
        captured["args"] = args
        captured["stripped"] = Path(args[1]).read_text(encoding="utf-8")
        return 0

    monkeypatch.setattr(cli, "run_mcporter", fake_run)

    exit_code = cli.main(["--config", str(config), "list", "context7", "--brief"])

    assert exit_code == 0
    assert captured["args"][0] == "--config"
    rewritten = Path(captured["args"][1])
    assert rewritten != config
    assert not rewritten.exists()
    assert "CONTEXT7_API_KEY" not in captured["stripped"]
    assert '"serverUrl"' in captured["stripped"]
    assert "anonymous access" in capsys.readouterr().err


def test_keyless_config_without_header_forwarded_unchanged(
    cli: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Keep the original config when it already lacks an auth header."""
    config = tmp_path / "mcporter.jsonc"
    config.write_text(CONFIG_WITHOUT_HEADER, encoding="utf-8")
    forwarded: list[list[str]] = []
    monkeypatch.setattr(
        cli,
        "run_mcporter",
        lambda args: forwarded.append(args) or 0,
    )

    exit_code = cli.main(["--config", str(config), "list", "context7", "--brief"])

    assert exit_code == 0
    assert forwarded == [["--config", str(config), "list", "context7", "--brief"]]


def test_key_present_forwards_config_unchanged(
    cli: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Keep the credential-backed config untouched when a key is available."""
    config = tmp_path / "mcporter.jsonc"
    config.write_text(CONFIG_WITH_HEADER, encoding="utf-8")
    forwarded: list[list[str]] = []
    monkeypatch.setenv("CONTEXT7_API_KEY", "test-key")
    monkeypatch.setattr(
        cli,
        "run_mcporter",
        lambda args: forwarded.append(args) or 0,
    )

    exit_code = cli.main(["--config", str(config), "list", "context7", "--brief"])

    assert exit_code == 0
    assert forwarded == [["--config", str(config), "list", "context7", "--brief"]]


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
