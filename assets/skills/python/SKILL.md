---
name: python
description: "Develop Python applications using modern patterns, uv, functional-first design, and production-first practices. Use this whenever working with .py files, pyproject.toml, uv commands, pip/pip3, poetry, virtualenv/venv, inline script metadata, or Python tooling like pytest, mypy, ruff, asyncio, itertools, functools, or dataclasses. If the task involves running Python, managing Python dependencies, creating environments, or building Python packages, load this skill and prefer uv-oriented workflows."
---

# Python Development

Functional-first, production-first Python 3.14+ with uv, type safety, immutability, and small composable modules.

## Activation Triggers
- `.py` files, `pyproject.toml`, uv commands, Python packaging
- pip, pip3, poetry, venv, virtualenv, inline script metadata
- Python, typing, asyncio, pytest, mypy, ruff, dataclasses, itertools, functools
- Async I/O, data pipelines, CLI tooling, validation, parsing, test strategy

## Workflow

```text
1. MODEL    -> types, invariants, boundaries
2. COMPOSE  -> pure functions, pipelines, small modules
3. VALIDATE -> parse at edges, return errors early
4. TEST     -> pytest, fixtures, async tests
5. HARDEN   -> ruff + format + mypy + regression tests
```

## Core Principles
- Functional core, imperative shell
- Immutability by default; copy-on-write
- Explicit types and error paths
- Small composable units
- Production defaults: logging, config, timeouts, retries
- Prefer `uv` for running Python, dependency management, environments, scripts, and builds

## When to Use
- New or refactored Python modules
- Async I/O, data pipelines, CLI tooling
- Type-heavy APIs, validation, parsing
- Test strategy or flaky tests
- Any request that mentions Python setup, Python dependencies, virtual environments, or script execution

## When Not to Use
- Non-Python runtimes
- Browser E2E tests (use Playwright)

## uv-first workflow
Use `uv` instead of raw `python`, `pip`, `poetry`, or `python -m venv`.

### Quick reference
```bash
uv run python script.py
uv run pytest
uv run --with requests python script.py
uv add requests pydantic httpx
uv add --dev pytest pytest-asyncio mypy ruff
uv venv
uv run python -m ast path/to/file.py >/dev/null
uv init --script example.py --python 3.12
uv add --script example.py requests rich
uv lock --script example.py
```

### Prefer these replacements
- `python script.py` -> `uv run python script.py`
- `python -m pytest` -> `uv run pytest`
- `pip install x` -> `uv add x`
- `python -m venv .venv` -> `uv venv`
- `python -m py_compile foo.py` -> `uv run python -m ast foo.py >/dev/null`

## Inline script metadata
For standalone scripts, prefer uv inline metadata over ad-hoc setup.

```python
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "requests<3",
#   "rich",
# ]
# ///
```

Then run:

```bash
uv run script.py
```

Helpful commands:

```bash
uv init --script script.py --python 3.12
uv add --script script.py requests rich
uv lock --script script.py
```

For executable scripts:

```python
#!/usr/bin/env -S uv run --script
# /// script
# dependencies = ["httpx"]
# ///
```

## Project quick start

```bash
uv init my-project && cd my-project
uv add requests pydantic httpx
uv add --dev pytest pytest-asyncio mypy ruff

uv run python script.py
uv run pytest
```

## Quality gates

```bash
uv run ruff check src/
uv run ruff format --check src/
uv run mypy src/
uv run pytest
```

## Build backend
Use `uv_build` for pure Python packages.
For extension modules, prefer another backend such as `hatchling`.

```toml
[build-system]
requires = ["uv_build>=0.9.28,<0.10.0"]
build-backend = "uv_build"
```

Prefer the standard `src/` layout unless the repo has a strong reason not to.

## Must / Must Not
- MUST: type hints on public APIs; validate inputs at boundaries; prefer pathlib
- MUST: use `uv` for running Python, adding deps, script metadata, and env setup
- MUST NOT: use raw `pip`, `pip3`, `poetry`, or `python -m venv` when uv is the intended workflow
- MUST NOT: use mutable default args; bare except; mix sync/async in one call chain

## Notes
Core patterns, async examples, and anti-patterns live in `reference.md` and the cookbooks.
Read the relevant cookbook when the task narrows:
- async work -> `cookbook/async.md`
- functional structure -> `cookbook/patterns*.md`
- tests -> `cookbook/testing*.md`
- language features -> `cookbook/modern*.md`

## Research tools

```bash
# gh search code for real-world examples
gh search code "asyncio.TaskGroup(" --language=python
gh search code "class.*Protocol):" --language=python
gh search code "async with httpx.AsyncClient(" --language=python
```

## References
- [reference.md](reference.md) - Data structures, best practices, idioms, error handling
- [patterns.md](cookbook/patterns.md) - Functional patterns
- [async.md](cookbook/async.md) - Async/await deep dive
- [testing.md](cookbook/testing.md) - pytest patterns & fixtures
- [design-patterns.md](cookbook/design-patterns.md) - Builder, DI, Factory, Strategy, Repository
- [modern.md](cookbook/modern.md) - Python 3.8-3.14 key features
