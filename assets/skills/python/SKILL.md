---
name: python
description: "Develop and debug Python: uv, typing, validation, APIs, async, tests, packaging, and .py projects."
license: GPL-3.0-or-later
metadata:
  author: anntnzrb
allowed-tools: ""
---

# Python Development

Python: uv-first, Pyright strict, typed JSON/data shapes, boundary validation, practical tests, small composable modules.

## Activation Triggers

- `.py`, `pyproject.toml`, uv commands, Python packaging, inline script metadata
- pip/pip3/poetry/venv/virtualenv replacement or migration
- Python typing, Pyright strict, inherited mypy, Ruff, pytest, Hypothesis
- TypedDict, Literal, discriminated unions, JSON/API/RPC payloads, pydantic, msgspec, boundary validation
- Async I/O, data pipelines, CLI tooling, parsing, test strategy

## Workflow

```text
1. DETECT    -> package manager, runtime target, scripts, type/test gates
2. ROUTE     -> read the required follow-up docs for async, typing, tests, syntax, patterns, packaging
3. MODEL     -> typed payloads, invariants, boundaries, public API types
4. COMPOSE   -> functional core, imperative shell, small modules
5. VALIDATE  -> parse untrusted input once at the edge; convert inward
6. VERIFY    -> Pyright/Ruff/pytest gates appropriate to the repo
```

## Core Principles

- Respect the declared Python target first: `requires-python`, CI matrix, Docker image, Ruff `target-version`, Pyright config.
- Prefer explicit types and error paths; Pyright strict is the default for new projects.
- Keep raw JSON, env, CLI, API, and RPC data at boundaries; validate once with pydantic/msgspec or narrow typed code.
- Model dict-shaped data with `TypedDict`, `Literal`, and discriminated unions while it remains dict-shaped.
- Prefer pure transformations, immutable values, copy-on-write updates, protocols, dataclasses, comprehensions/generators, and small modules when they clarify code.
- Keep I/O, logging, retries, timeouts, mutation, and process exits in the imperative shell.
- Use mypy only for inherited repos that already use it.

## uv Essentials

Prefer `uv` over raw `python`, `pip`, `poetry`, and `python -m venv` when uv is the intended workflow.

```bash
uv run python script.py
uv run pytest
uv run pyright
uv run ruff check .
uv run ruff format --check .
uv run --with requests python script.py
uv add requests httpx
uv add --dev pytest pytest-asyncio pyright ruff
uv venv
uv init --script example.py --python 3.12
uv add --script example.py requests rich
uv lock --script example.py
```

Use inline script metadata for standalone scripts that need dependencies:

```python
# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx"]
# ///
```

## Quality Gate Essentials

- New projects: Pyright strict, Ruff lint/format, pytest.
- Inherited projects: preserve the existing checker stack unless changing it is part of the task.
- Baseline commands:
  - `uv run pyright`
  - `uv run ruff check .`
  - `uv run ruff format --check .`
  - `uv run pytest`
- Boundary-heavy code needs contract tests for JSON/API/RPC/CLI ingress and failure paths.
- Parser/transform-heavy code should use Hypothesis only for invariants, round-trips, idempotence, and lossless conversion properties.
- Ruff baseline: `E`, `F`, `I`, `UP`, `B`, `SIM`; expand deliberately after the baseline is clean.

## Build Note

Use `uv_build` for pure Python packages. For extension modules, prefer an appropriate backend such as `hatchling`.

```toml
[build-system]
requires = ["uv_build>=0.9.28,<0.10.0"]
build-backend = "uv_build"
```

Prefer `src/` layout unless the repository has a strong reason not to.

## Required follow-up reads

Only task-relevant references MUST be loaded.

| Need | Read | When |
| --- | --- | --- |
| Async I/O, concurrency, cancellation | `cookbook/async.md` | Async behavior is central |
| Typing and data boundaries | `reference.md`, `cookbook/correctness.md` | JSON, API, RPC, CLI, or validation boundaries matter |
| Testing and property-based invariants | `cookbook/testing.md`, then matching `cookbook/testing-*.md` | Designing or debugging tests |
| Modern syntax and runtime compatibility | `cookbook/modern.md`, then matching version guide | Target-version behavior matters |
| Functional, iterator, or design patterns | `cookbook/patterns.md`, then matching pattern guide | Choosing an implementation pattern |
| Packaging, uv, metadata, build backends | This file, project config, official tool output | Packaging or dependency work |

## Must / Must Not

- MUST type public APIs, validate untrusted inputs at boundaries, prefer pathlib, and respect the project runtime target.
- MUST use `uv` for running Python, adding deps, script metadata, and env setup when uv is intended.
- MUST keep validators, raw payloads, mocks, retries, and I/O out of core logic unless they are the domain being modeled.
- MUST NOT use mutable default args, bare `except`, untracked background tasks, blocking calls in async code, or broad fallbacks that hide bad input.
- MUST NOT keep known payloads as `dict[str, Any]`, propagate raw JSON inward, or carry boundary validator objects through core logic by accident.
