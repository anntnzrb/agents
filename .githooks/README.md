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

Quality gates:
- `pre-commit`: runs `git diff --cached --check`, followed by `ruff check .`, `ruff format --check .`, and `basedpyright`.
- `pre-push`: runs the same Python gates (`ruff check .`, `ruff format --check .`, `basedpyright`) plus the full test suite (`pytest -n auto`).
