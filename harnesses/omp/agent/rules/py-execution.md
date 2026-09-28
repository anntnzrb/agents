---
name: py-execution
description: Run Python, dependency, build, and quality tooling through uv instead of direct interpreters or foreign package managers
condition:
  - '(?:[;&"]\s*)(?:sudo\s+|env\s+)?(?:[A-Za-z_][A-Za-z0-9_]*=\S+\s+)*(?:pip[23]?|pipx|pip-compile|pip-sync|pipdeptree)\b'
  - '(?:[;&"]\s*)(?:sudo\s+|env\s+)?(?:[A-Za-z_][A-Za-z0-9_]*=\S+\s+)*(?:python[23]?(?:\.\d+)*|pythonw|pypy3?|py)\b'
  - '(?:[;&"]\s*)(?:sudo\s+|env\s+)?(?:[A-Za-z_][A-Za-z0-9_]*=\S+\s+)*(?:conda|hatch|mamba|micromamba|pdm|pipenv|poetry|rye|virtualenv|pyenv)\b'
  - '(?:[;&"]\s*)(?:sudo\s+|env\s+)?(?:[A-Za-z_][A-Za-z0-9_]*=\S+\s+)*(?:twine|flit)\b'
  - '(?:[;&"]\s*)(?:sudo\s+|env\s+)?(?:[A-Za-z_][A-Za-z0-9_]*=\S+\s+)*(?:pytest|tox|nox|coverage|mypy|basedpyright|pyright|ruff|black|isort|flake8|pylint|ipython|jupyter)\b'
scope:
  - tool:bash
interruptMode: never
---
# Python execution

This environment is uv-first. Invoke interpreters and Python tooling through `uv`, not directly and not through foreign environment managers.

- Run code with `uv run python script.py`, `uv run --script script.py` for PEP 723 standalone scripts, or `uv run --with <package> python -c '...'` for a one-off dependency.
- Quality gates: `uv run basedpyright` (never the `pyright` CLI), `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest`. One-off tools: `uvx <tool>` or `uv tool run <tool>`.
- Dependencies: `uv add`, `uv sync`, `uv lock`. Never use `pip`, `pipx`, `pip-compile`, `pip-sync`, or `pipdeptree`; use `uv pip compile`, `uv pip sync`, `uv pip install`, and `uv pip tree`.
- Build and publish: `uv build` and `uv publish`, not `python -m build`, `twine`, or `flit`.
- Interpreters and environments: `uv python` and `uv venv`, not `pyenv`, `virtualenv`, `conda`, `poetry`, `pdm`, `pipenv`, `hatch`, `rye`, or `mamba`. Replace `python -m pip|venv|build|twine|ensurepip` and `python setup.py ...` with the `uv` equivalents.
- Load `skill://python` before changing dependency, project, or tool configuration.
