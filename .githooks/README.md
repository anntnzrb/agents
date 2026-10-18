# Git hooks

These hooks enforce sync quality gates and selected repository checks without
an external hook manager.

Requirements:
- Python >=3.12
- `uv`

Enable them once after cloning:

```sh
git config --local core.hooksPath .githooks
```

Optionally synchronize the sync environment before committing:

```sh
cd sync && uv sync --frozen
```

This creates and manages only `sync/.venv/`, using the versions pinned by
`sync/uv.lock`; it does not install packages globally. The hooks bootstrap and
reconcile this local virtual environment automatically on every invocation via
`uv sync --frozen` to keep up with lock changes without rewriting tracked source
files.

Local integration into `main` and normal direct pushes follow the
[repository integration policy](../docs/ci.md#integrate-and-publish-a-change).
These hooks validate changes without moving branches or switching worktrees.

Quality gates (`sync-gates` console script, defined in `sync/src/sync/gates.py`):
- `pre-commit`: runs `git diff --cached --check`, followed by `sync-gates` (ruff check, ruff format check, basedpyright).
- `pre-push`: runs the static gates with `sync-gates`, then the full test suite serially with `pytest -n 0 -o addopts="" -q`. Clearing configured pytest options prevents parallel workers on production hosts. It then runs `ci.py local` from the repository root against `origin/main`; see [Run checks locally](../docs/ci.md#run-checks-locally).
- The `autommit` skill runs `pre-commit` once on the full staged snapshot before planning, then creates each commit in a temporary worktree with hooks disabled. The `pre-push` hook still runs.
