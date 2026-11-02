"""Run the repository's pre-commit gate against the real staged state.

The per-commit temporary-worktree commits stay hook-free because hooks there
would judge partial states. This gate runs once, before planning, on the exact
staged snapshot that the commits must reproduce.
"""

from pathlib import Path

from autommit.errors import AutommitError
from autommit.git import run_git, try_git


def _refusal(gate: str, output: str) -> AutommitError:
    detail = output.strip() or "no output"
    summary = f"Pre-commit gate failed ({gate}); no commits were created."
    return AutommitError(
        "hook_failed", f"{summary} Fix the staged changes and rerun.\n{detail}", 4
    )


def run_pre_commit_gate(repo: Path) -> None:
    """Refuse when git diff --cached --check or an executable pre-commit hook fails."""
    root = Path(run_git(repo, "rev-parse", "--show-toplevel").strip())
    check = try_git(root, "diff", "--cached", "--check", "--no-color")
    if check.returncode != 0:
        raise _refusal("git diff --cached --check", check.stdout + check.stderr)
    completed = try_git(root, "hook", "run", "--ignore-missing", "pre-commit")
    if completed.returncode != 0:
        raise _refusal(
            f"pre-commit hook exited {completed.returncode}",
            completed.stdout + completed.stderr,
        )
