"""Small subprocess boundary for Git."""

import os
import subprocess
from pathlib import Path
from typing import Final

from autommit.errors import GitError, GitMissingError

GIT_ENVIRONMENT: Final[dict[str, str]] = {
    "GIT_TERMINAL_PROMPT": "0",
    "LC_ALL": "C",
    "GIT_PAGER": "cat",
}

GIT_ENVIRONMENT_DROPS: Final[tuple[str, ...]] = (
    "GIT_DIFF_OPTS",
    "GIT_EXTERNAL_DIFF",
)

GIT_SAFE_ARGS: Final[tuple[str, ...]] = (
    "-c",
    "core.quotepath=false",
    "-c",
    "diff.mnemonicprefix=false",
    "-c",
    "diff.noprefix=false",
    "-c",
    "diff.algorithm=myers",
    "-c",
    "diff.renames=true",
    "-c",
    "diff.interHunkContext=0",
)

GIT_DIFF_FLAGS: Final[tuple[str, ...]] = (
    "--no-color",
    "--no-ext-diff",
    "--no-textconv",
)


def try_git(
    cwd: Path, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run Git when the caller needs to interpret a nonzero status."""
    merged_env = {**os.environ, **GIT_ENVIRONMENT, **(env or {})}
    for dropped in GIT_ENVIRONMENT_DROPS:
        _ = merged_env.pop(dropped, None)
    cmd = ["git", *GIT_SAFE_ARGS, *args]
    try:
        completed = subprocess.run(
            cmd,
            cwd=cwd,
            check=False,
            capture_output=True,
            env=merged_env,
        )
        return subprocess.CompletedProcess(
            cmd,
            completed.returncode,
            completed.stdout.decode("utf-8", "surrogateescape"),
            completed.stderr.decode("utf-8", "surrogateescape"),
        )
    except FileNotFoundError as err:
        raise GitMissingError from err


def run_git(cwd: Path, *args: str, env: dict[str, str] | None = None) -> str:
    """Run Git without a shell and return stdout, raising GitError on failure."""
    completed = try_git(cwd, *args, env=env)
    if completed.returncode != 0:
        detail = (
            completed.stderr.strip()
            or completed.stdout.strip()
            or f"exit code {completed.returncode}"
        )
        command = " ".join(["git", *GIT_SAFE_ARGS, *args])
        raise GitError(f"{command} failed: {detail}")
    return completed.stdout
