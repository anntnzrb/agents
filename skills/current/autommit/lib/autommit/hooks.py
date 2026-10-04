"""Run the repository's pre-commit gate against the real staged state.

The per-commit temporary-worktree commits stay hook-free because hooks there
would judge partial states. This gate runs once, before planning, on the exact
staged snapshot that the commits must reproduce.
"""

import os
import subprocess
from pathlib import Path

from autommit.errors import AutommitError
from autommit.git import run_git, try_git


def _refusal(gate: str, output: str) -> AutommitError:
    detail = output.strip() or "no output"
    summary = f"Pre-commit gate failed ({gate}); no commits were created."
    return AutommitError(
        "hook_failed", f"{summary} Fix the staged changes and rerun.\n{detail}", 4
    )


def _hook_path(root: Path) -> Path:
    """Resolve the pre-commit hook path the way Git does, honoring core.hooksPath."""
    raw = Path(run_git(root, "rev-parse", "--git-path", "hooks/pre-commit").strip())
    return raw if raw.is_absolute() else root / raw


def run_pre_commit_gate(repo: Path) -> None:
    """Refuse when git diff --cached --check or an executable pre-commit hook fails."""
    root = Path(run_git(repo, "rev-parse", "--show-toplevel").strip())
    check = try_git(root, "diff", "--cached", "--check", "--no-color")
    if check.returncode != 0:
        raise _refusal("git diff --cached --check", check.stdout + check.stderr)
    hook = _hook_path(root)
    if not hook.is_file() or not os.access(hook, os.X_OK):
        return
    try:
        completed = subprocess.run(
            [str(hook)],
            cwd=root,
            check=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as error:
        raise _refusal(f"pre-commit hook {hook}", str(error)) from error
    if completed.returncode != 0:
        raise _refusal(
            f"pre-commit hook {hook} exited {completed.returncode}",
            completed.stdout + completed.stderr,
        )
