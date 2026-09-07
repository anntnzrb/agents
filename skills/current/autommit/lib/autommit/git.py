"""Small subprocess boundary for Git."""

from __future__ import annotations

import os
import subprocess
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from pathlib import Path

from autommit.errors import GitError, GitMissingError

GIT_ENVIRONMENT: Final[dict[str, str]] = {
    "GIT_TERMINAL_PROMPT": "0",
    "LC_ALL": "C",
}

GIT_SAFE_ARGS: Final[tuple[str, ...]] = (
    "-c",
    "core.quotepath=false",
    "-c",
    "diff.mnemonicprefix=false",
    "-c",
    "diff.noprefix=false",
)


def run_git(cwd: Path, *args: str, env: dict[str, str] | None = None) -> str:
    """Run Git without a shell and return stdout, raising GitError on failure."""
    merged_env = {**os.environ, **GIT_ENVIRONMENT, **(env or {})}
    cmd = ["git", *GIT_SAFE_ARGS, *args]
    try:
        completed = subprocess.run(
            cmd,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="surrogateescape",
            env=merged_env,
        )
    except FileNotFoundError as err:
        raise GitMissingError from err
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        if not detail:
            detail = f"exit code {completed.returncode}"
        command = " ".join(cmd)
        raise GitError(f"{command} failed: {detail}")
    return completed.stdout


def try_git(
    cwd: Path, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run Git when the caller needs to interpret a nonzero status."""
    merged_env = {**os.environ, **GIT_ENVIRONMENT, **(env or {})}
    cmd = ["git", *GIT_SAFE_ARGS, *args]
    try:
        return subprocess.run(
            cmd,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="surrogateescape",
            env=merged_env,
        )
    except FileNotFoundError as err:
        raise GitMissingError from err
