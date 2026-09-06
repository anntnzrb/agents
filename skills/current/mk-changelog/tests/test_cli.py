"""Integration tests for mk-changelog CLI."""

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from scripts.cli import main


@dataclass(slots=True)
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
    cl.write_text("# Changelog\n\n## [1.0.0]\n- Old\n", encoding="utf-8")

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
    data = json.loads(captured.out)
    assert data["ok"] is True
    assert data["changed"] is True
    assert "preview" in data
    assert "## [Unreleased]" in data["preview"]
    assert "- Resolved issue #42" in data["preview"]


def test_cli_prepare_git(tmp_path: Path, capsys: CaptureFixture):
    # Setup test git repo
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    f_init = tmp_path / "README.md"
    f_init.write_text("# Project", encoding="utf-8")
    subprocess.run(
        ["git", "add", "README.md"], cwd=tmp_path, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "chore: init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    f = tmp_path / "app.py"
    f.write_text("print('hello')", encoding="utf-8")
    subprocess.run(
        ["git", "add", "app.py"], cwd=tmp_path, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "feat: initial app (#100)"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    code = main(["prepare", "--range", "HEAD~1..HEAD", "--repo", str(tmp_path)])
    assert code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["source_type"] == "range"
    assert len(data["commits"]) == 1
    assert data["commits"][0]["pr_number"] == 100
    assert data["commits"][0]["category"] == "Added"


def test_cli_status(capsys: CaptureFixture):
    code = main(["status"])
    assert code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["ok"] is True
    assert "tools" in data
    assert data["tools"]["git"] is True
