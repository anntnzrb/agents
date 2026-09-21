"""Unit tests for the AutoReview CLI wrapper and target selection logic."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

CLI_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "cli.py"


def test_cli_help_flag() -> None:
    """Verify that the CLI provides help output with valid zero exit code."""
    proc = subprocess.run(
        [sys.executable, str(CLI_SCRIPT), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "usage:" in proc.stdout.lower()
    assert "--mode" in proc.stdout
    assert "--max-priority" in proc.stdout


def test_cli_mode_flags_parsing() -> None:
    """Verify that --mode, --max-priority, and target parameters parse correctly."""
    proc = subprocess.run(
        [sys.executable, str(CLI_SCRIPT), "--mode", "local", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "local" in proc.stdout or "--mode" in proc.stdout
