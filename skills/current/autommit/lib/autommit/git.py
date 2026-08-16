# ruff: noqa: CPY001, EM102, S607, TC003, TRY003
"""Small subprocess boundary for Git."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Final

from autommit.errors import GitError, GitMissingError

GIT_ENVIRONMENT: Final[dict[str, str]] = {
    "GIT_TERMINAL_PROMPT": "0",
    "LC_ALL": "C",
}


def run_git(cwd: Path, *args: str) -> str:
    """Run Git without a shell and return stdout."""
    try:
        completed = subprocess.run(  # noqa: S603
            ["git", *args],
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="surrogateescape",
            env={**os.environ, **GIT_ENVIRONMENT},
        )
    except FileNotFoundError as error:
        raise GitMissingError from error
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        if not detail:
            detail = f"exit code {completed.returncode}"
        command = " ".join(("git", *args))
        raise GitError(f"{command} failed: {detail}")
    return completed.stdout


def try_git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run Git when the caller needs to interpret a nonzero status."""
    try:
        return subprocess.run(  # noqa: S603
            ["git", *args],
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="surrogateescape",
            env={**os.environ, **GIT_ENVIRONMENT},
        )
    except FileNotFoundError as error:
        raise GitMissingError from error
