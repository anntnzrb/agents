"""Pinned CLI invocation and configuration errors."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

CLI = Path(__file__).resolve().parents[1] / "scripts" / "cli.py"
FAKE_BUN = """import json, os, sys
from pathlib import Path
Path(os.environ["FAKE_BUN_LOG"]).write_text(json.dumps(sys.argv[1:]), encoding="utf-8")
sys.exit(3)
"""


def make_skill(root: Path, pin: object) -> Path:
    """Create an isolated wrapper with a chosen release."""
    skill = root / "skill"
    (skill / "scripts").mkdir(parents=True)
    _ = shutil.copy(CLI, skill / "scripts" / "cli.py")
    _ = (skill / "UPSTREAM.json").write_text(json.dumps(pin), encoding="utf-8")
    return skill / "scripts" / "cli.py"


def make_bun(directory: Path) -> None:
    """Install a fake runner that records its arguments."""
    directory.mkdir()
    script = directory / "fake_bun.py"
    _ = script.write_text(FAKE_BUN, encoding="utf-8")
    if sys.platform == "win32":
        _ = (directory / "bun.cmd").write_text(
            f'@"{sys.executable}" "{script}" %*\r\n', encoding="utf-8"
        )
    else:
        launcher = directory / "bun"
        _ = launcher.write_text(f"#!{sys.executable}\n{FAKE_BUN}", encoding="utf-8")
        launcher.chmod(0o755)


def test_pinned_release_and_child_exit(tmp_path: Path) -> None:
    cli = make_skill(tmp_path, {"release": "v9.8.7"})
    make_bun(tmp_path / "bin")
    log = tmp_path / "argv.json"
    result = subprocess.run(
        [sys.executable, str(cli), "help", "status"],
        env=os.environ
        | {
            "PATH": str(tmp_path / "bin"),
            "FAKE_BUN_LOG": str(log),
            "EXCALIDRAW_SKILL_STATE_DIR": str(tmp_path / "state"),
            "EXPRESS_SERVER_URL": "http://127.0.0.1:1",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 3
    assert json.loads(log.read_text(encoding="utf-8")) == [
        "x",
        "mcp-excalidraw-server@9.8.7",
        "help",
        "status",
    ]


@pytest.mark.parametrize("pin", [{}, {"release": "v"}, {"release": 3}])
def test_invalid_pin_returns_configuration_error(tmp_path: Path, pin: object) -> None:
    cli = make_skill(tmp_path, pin)
    result = subprocess.run(
        [sys.executable, str(cli), "help"], capture_output=True, text=True, check=False
    )
    assert result.returncode == 2
    assert "invalid release" in result.stderr
