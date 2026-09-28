"""Integration tests for mk-changelog CLI."""

import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TypeIs

from scripts.cli import main


def _is_dict(obj: object) -> TypeIs[dict[str, object]]:
    return isinstance(obj, dict)


def _is_list(obj: object) -> TypeIs[list[object]]:
    return isinstance(obj, list)


@dataclass(frozen=True, slots=True)
class CapturedOutput:
    """Captured stdout and stderr streams."""

    out: str
    err: str


class CaptureFixture(Protocol):
    """Protocol for pytest capsys fixture."""

    def readouterr(self) -> CapturedOutput:
        """Read captured stdout and stderr."""
        ...


def test_cli_format(capsys: CaptureFixture):
    payload = json.dumps(
        {
            "entries": {
                "Added": ["New command line option"],
                "Fixed": ["Bug in network retry"],
            }
        }
    )
    code = main(["format", "--json", payload, "--header"])
    assert code == 0
    captured = capsys.readouterr()
    assert "## [Unreleased]" in captured.out
    assert "### Added" in captured.out
    assert "- New command line option" in captured.out
    assert "### Fixed" in captured.out
    assert "- Bug in network retry" in captured.out


def test_cli_patch_dry_run(tmp_path: Path, capsys: CaptureFixture):
    cl = tmp_path / "CHANGELOG.md"
    _ = cl.write_text("# Changelog\n\n## [1.0.0]\n- Old\n", encoding="utf-8")

    payload = json.dumps({"entries": {"Fixed": ["Resolved issue #42"]}})
    code = main(
        [
            "patch",
            "--target",
            str(cl),
            "--json",
            payload,
            "--dry-run",
        ]
    )
    assert code == 0
    captured = capsys.readouterr()
    loads_fn: Callable[..., object] = json.loads
    data = loads_fn(captured.out)
    assert _is_dict(data)
    assert data["ok"] is True
    assert data["changed"] is True
    assert "preview" in data
    preview = data["preview"]
    assert isinstance(preview, str)
    assert "## [Unreleased]" in preview
    assert "- Resolved issue #42" in preview


def test_cli_prepare_git(tmp_path: Path, capsys: CaptureFixture):
    # Setup test git repo
    _ = subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    _ = subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    _ = subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    f_init = tmp_path / "README.md"
    _ = f_init.write_text("# Project", encoding="utf-8")
    _ = subprocess.run(
        ["git", "add", "README.md"], cwd=tmp_path, check=True, capture_output=True
    )
    _ = subprocess.run(
        ["git", "commit", "-m", "chore: init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    f = tmp_path / "app.py"
    _ = f.write_text("print('hello')", encoding="utf-8")
    _ = subprocess.run(
        ["git", "add", "app.py"], cwd=tmp_path, check=True, capture_output=True
    )
    _ = subprocess.run(
        ["git", "commit", "-m", "feat: initial app (#100)"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    code = main(["prepare", "--range", "HEAD~1..HEAD", "--repo", str(tmp_path)])
    assert code == 0
    captured = capsys.readouterr()
    loads_fn: Callable[..., object] = json.loads
    data = loads_fn(captured.out)
    assert _is_dict(data)
    assert data["source_type"] == "range"
    commits = data.get("commits")
    assert _is_list(commits)
    assert len(commits) == 1
    commit0 = commits[0]
    assert _is_dict(commit0)
    assert commit0["pr_number"] == 100
    assert commit0["category"] == "Added"


def test_cli_status(capsys: CaptureFixture):
    code = main(["status"])
    assert code == 0
    captured = capsys.readouterr()
    loads_fn: Callable[..., object] = json.loads
    data = loads_fn(captured.out)
    assert _is_dict(data)
    assert data["ok"] is True
    tools = data.get("tools")
    assert _is_dict(tools)
    assert tools["git"] is True
