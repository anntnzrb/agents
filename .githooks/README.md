# Git hooks

These hooks enforce the sync application's local quality gates without an
external hook manager.

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

Quality gates (`sync-gates` console script, defined in `sync/src/sync/gates.py`):
- `pre-commit`: runs `git diff --cached --check`, followed by `sync-gates` (ruff check, ruff format check, basedpyright).
- `pre-push`: runs `sync-gates --tests`, which appends the full test suite (`pytest -n auto`) to the static gates.
