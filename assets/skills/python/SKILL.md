---
name: python
description: "Develop Python applications using modern patterns, uv, Pyright strict, typed JSON/data shapes, boundary validation, and practical testing. Use this whenever working with .py files, pyproject.toml, uv commands, pip/pip3, poetry, virtualenv/venv, inline script metadata, Python typing or static checking, JSON/API/RPC payloads, pydantic/msgspec boundaries, Hypothesis, pytest, asyncio, dataclasses, itertools, functools, or packaging. If the task involves running Python, managing dependencies, creating environments, or building Python packages, load this skill and prefer uv-oriented workflows."
---

# Python Development

Functional-first, production-first Python 3.14+ with uv, Pyright strict, typed JSON/data shapes, boundary validation, and small composable modules.

## Activation Triggers
- `.py`, `pyproject.toml`, uv commands, Python packaging
- pip, pip3, poetry, venv, virtualenv, inline script metadata
- Python typing, pyright, strict type checking, mypy (existing codebases), ruff, pytest, dataclasses, itertools, functools
- TypedDict, Literal, discriminated unions, JSON/API/RPC payloads, pydantic, msgspec, boundary validation
- Hypothesis, parser/transform/invariant tests
- Async I/O, data pipelines, CLI tooling, parsing, test strategy

## Workflow
```text
1. DETECT    -> package manager, runtime, scripts, type gates
2. MODEL     -> domain types, invariants, JSON shapes, boundaries
3. COMPOSE   -> pure functions, pipelines, small modules
4. VALIDATE  -> parse at edges; TypedDict/Literal/discriminated unions for dict-shaped data; pydantic/msgspec only at ingress
5. TEST      -> pytest; Hypothesis only for parsers, transforms, invariants
6. HARDEN    -> ruff + format + pyright strict; mypy only for inherited repos that already use it
```

## Core Principles
- Functional core, imperative shell
- Immutability by default; copy-on-write
- Explicit types and error paths
- Pyright strict first; set `typeCheckingMode = "strict"` for new projects. Use mypy only for inherited repos that already use it.
- Small composable units
- Production defaults: logging, config, timeouts, retries
- Prefer `uv` for running Python, dependency management, environments, scripts, and builds

## Typed data and boundaries
- Model JSON-shaped data with `TypedDict`, `Literal`, and discriminated unions while it is still dict-shaped.
- Validate untrusted input once at the boundary with `pydantic` or `msgspec`.
- Convert to typed domain objects immediately; keep raw `dict[str, Any]` at the edge.

## When to Use
- New or refactored Python modules
- Async I/O, data pipelines, CLI tooling
- Type-heavy APIs, validation, parsing, JSON-shaped data
- Pyright strict setup/tuning; inherited mypy-based repos
- Test strategy or flaky tests, especially parser/transform/invariant-heavy code
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
uv run pyright
uv run --with requests python script.py
uv add requests httpx
uv add --dev pytest pytest-asyncio pyright ruff
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
uv add requests httpx
uv add --dev pytest pytest-asyncio pyright ruff
uv run python script.py
uv run pytest
uv run pyright
```

## Quality gates
New projects: make `pyright` strict the default static gate; keep `mypy` only for inherited repos.

### Baseline
```bash
uv run ruff check src/
uv run ruff format --check src/
uv run pyright  # strict via pyrightconfig.json or [tool.pyright]
uv run pytest
```

### Boundary-heavy
- Baseline +
- contract tests for JSON/API/CLI ingress
- `TypedDict`/`Literal` for shapes; `pydantic` or `msgspec` at the edge

### Parser/transform-heavy
- Baseline +
- Hypothesis for parsers, normalizers, serializers, invariants
- round-trip / idempotence / lossless conversion tests

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
Core patterns, typed shapes, boundary validation, and testing notes live in `reference.md` and the cookbooks.
Read the relevant cookbook when the task narrows:
- async work -> `cookbook/async.md`
- functional structure -> `cookbook/patterns*.md`
- tests or parser-heavy invariants -> `cookbook/testing*.md`
- strict type gates / boundary validation -> `cookbook/correctness.md`
- language features -> `cookbook/modern*.md`
- typed shapes quick reference -> `reference.md`
## Research tools
```bash
# gh search code for real-world examples
gh search code "pyright strict" --language=python
gh search code "TypedDict" --language=python
gh search code "hypothesis" --language=python
```

## References
- [reference.md](reference.md) - data structures, typed shapes, boundary validation, error handling
- [correctness.md](cookbook/correctness.md) - Pyright strict baseline, boundary validation choices, tiered quality gates
- [patterns.md](cookbook/patterns.md) - functional patterns
- [async.md](cookbook/async.md) - async/await deep dive
- [testing.md](cookbook/testing.md) - pytest patterns, fixtures, and property-based testing when parser/transform tests justify it
- [design-patterns.md](cookbook/design-patterns.md) - Builder, DI, Factory, Strategy, Repository
- [modern.md](cookbook/modern.md) - Python 3.8-3.14 key features