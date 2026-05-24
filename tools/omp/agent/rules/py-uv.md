---
description: Use the Python skill and uv workflow for all Python work
condition:
  - "\\b(?:pythonw?(?:[23])?(?:\\.\\d+)*(?:\\.exe)?|py(?:\\.exe)?|pypy(?:3)?(?:\\.exe)?|pip(?:[23])?(?:\\.\\d+)*(?:\\.exe)?|pipx(?:\\.exe)?|pip-compile|pip-sync|pipdeptree|conda|hatch|mamba|micromamba|pdm|pipenv|poetry|rye|virtualenv|pyenv|twine|flit|pytest|py\\.test|tox|nox|coverage|mypy|pyright|ruff|black|isort|flake8|pylint|ipython|jupyter|jupyter-lab|jupyter-notebook|notebook)\\b"
  - "\\bpython(?:w?(?:[23])?(?:\\.\\d+)*)?\\b[^\\n;|&]*\\s-m\\s*(?:pip|venv|virtualenv|ensurepip|py_compile|compileall|build|twine)\\b"
  - "\\bpython(?:w?(?:[23])?(?:\\.\\d+)*)?\\b[^\\n;|&]*\\bsetup\\.py\\b"
scope:
  - text
  - tool
interruptMode: never
---

Python work must use the Python skill and uv workflow.

When Python is involved:
- Load `/skill:python` before implementing, debugging, testing, or changing Python code.
- Prefer uv-native workflows:
  - `uv run ...`
  - `uv run --with <pkg> ...`
  - `uv add <pkg>`
  - `uv sync`
  - `uv pip compile/sync ...` only for requirements-style compatibility.
  - `uv tool run <tool>` or `uvx <tool>` for Python CLI tools.
- Do not use raw `python`, `pip`, `pipx`, `poetry`, `conda`, `virtualenv`, `pyenv`, `twine`, or direct Python tool CLIs unless the user explicitly overrides this policy.
- If a command was blocked by bashInterceptor, revise it to the uv equivalent instead of retrying variants of the blocked command.
