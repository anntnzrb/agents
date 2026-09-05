"""Small subprocess boundary for Git."""

from __future__ import annotations

import os
import subprocess
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from pathlib import Path

from expression import Error, Ok, Result

from autommit.errors import AutommitError, GitError, GitMissingError

GIT_ENVIRONMENT: Final[dict[str, str]] = {
    "GIT_TERMINAL_PROMPT": "0",
    "LC_ALL": "C",
}


def run_git(cwd: Path, *args: str) -> Result[str, AutommitError]:
    """Run Git without a shell and return stdout wrapped in a Result."""
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="surrogateescape",
            env={**os.environ, **GIT_ENVIRONMENT},
        )
    except FileNotFoundError:
        return Error(GitMissingError())
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        if not detail:
            detail = f"exit code {completed.returncode}"
        command = " ".join(("git", *args))
        return Error(GitError(f"{command} failed: {detail}"))
    return Ok(completed.stdout)


def try_git(
    cwd: Path, *args: str
) -> Result[subprocess.CompletedProcess[str], AutommitError]:
    """Run Git when the caller needs to interpret a nonzero status."""
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="surrogateescape",
            env={**os.environ, **GIT_ENVIRONMENT},
        )
    except FileNotFoundError:
        return Error(GitMissingError())
    return Ok(completed)
