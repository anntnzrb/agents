"""Git execution and environment sanitization primitives for AutoReview."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from autoreview.models import (
    SAFE_GIT_CONFIG_ARGS,
    SUBPROCESS_TEXT_ENCODING,
    SUBPROCESS_TEXT_ERRORS,
)


def safe_git_env(repo: Path) -> dict[str, str]:
    """Construct an isolated, deterministic Git environment blocking user/system config."""
    platform_keys = (
        "COMSPEC",
        "DEVELOPER_DIR",
        "PATHEXT",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "TMPDIR",
        "WINDIR",
    )
    caller_home = os.environ.get("HOME")
    env = {key: os.environ[key] for key in platform_keys if key in os.environ}
    env.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_GRAFT_FILE": os.devnull,
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "HOME": caller_home if caller_home is not None else str(Path.home()),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        }
    )
    return env


def resolve_git(repo: Path) -> str:
    """Locate the trusted system git executable."""
    resolved = shutil.which("git")
    if resolved is not None:
        return resolved
    raise SystemExit("executable not found: git")


def git_run(
    repo: Path,
    args: list[str],
    *,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run a sanitized git command returning decoded string output."""
    used_env = env if env is not None else safe_git_env(repo)
    result = subprocess.run(
        [
            resolve_git(repo),
            "--no-optional-locks",
            *SAFE_GIT_CONFIG_ARGS,
            *args,
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding=SUBPROCESS_TEXT_ENCODING,
        errors=SUBPROCESS_TEXT_ERRORS,
        env=used_env,
        check=False,
    )
    if check and result.returncode != 0:
        raise SystemExit(
            f"Git command failed ({result.returncode}): git {' '.join(args)}\n"
            f"{result.stderr or result.stdout}"
        )
    return result


def is_dirty(repo: Path) -> bool:
    """Check if the repository has uncommitted changes or untracked files."""
    proc = git_run(
        repo, ["status", "--porcelain", "--untracked-files=all"], check=False
    )
    return bool(proc.stdout.strip())


def current_branch(repo: Path) -> str | None:
    """Return the name of the current branch or None if detached."""
    proc = git_run(repo, ["branch", "--show-current"], check=False)
    out = proc.stdout.strip()
    return out if out else None


def validate_git_ref(repo: Path, ref: str, label: str = "ref") -> str:
    """Verify that a Git reference exists and return its resolved SHA."""
    proc = git_run(repo, ["rev-parse", "--verify", f"{ref}^{{commit}}"], check=False)
    if proc.returncode != 0:
        raise SystemExit(f"invalid {label} Git reference: {ref}")
    return proc.stdout.strip()
