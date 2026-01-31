# AGENTS.md

This holds automation scripts used to manage and sync these AI Agent configs. Keep changes here, not in synced tool homes, because sync will overwrite tool-home copies.

## Full gate

- `uvx ruff format bin/sync.py`
- `uvx ruff check --select ALL --ignore D203,D212 bin/sync.py`
