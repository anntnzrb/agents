---
name: python
description: "Use when writing Python, editing .py files, configuring pyproject.toml, using uv, basedpyright typing, or pytest tests."
license: AGPL-3.0-or-later
metadata:
  author: anntnzrb

---

# Python Development

Python: uv-first, basedpyright, typed JSON/data shapes, boundary validation, practical tests, small composable modules.

## Activation Triggers

- `.py`, `pyproject.toml`, uv commands, Python packaging, inline script metadata
- pip/pip3/poetry/venv/virtualenv replacement or migration
- Python typing, basedpyright, inherited mypy, Ruff, pytest, Hypothesis
- TypedDict, Literal, discriminated unions, JSON/API/RPC payloads, pydantic, msgspec, boundary validation
- Async I/O, data pipelines, CLI tooling, parsing, test strategy

## Mandatory Read

Before writing or reviewing any Python, MUST read `cookbook/modern.md` in full: the baseline idioms and the Never table apply to every program, gated only by the project's `requires-python`.

## Workflow

```text
1. DETECT    -> package manager, runtime target, scripts, type/test gates
2. ROUTE     -> read `cookbook/modern.md`, then the task-specific follow-up docs for async, typing, engineering, tests, patterns, packaging
3. MODEL     -> typed payloads, invariants, boundaries, distinct domain concepts, public API types
4. COMPOSE   -> functional core, imperative shell, small modules; reuse the first adequate existing tool or helper
5. VALIDATE  -> parse untrusted input once at the edge; convert inward; make resource ownership, cancellation, timeouts, and errors explicit
6. VERIFY    -> basedpyright/Ruff/pytest gates appropriate to the repo; test observable behavior and failure paths
```

## Core Principles

- Respect the declared Python target first: `requires-python`, CI matrix, Docker image, Ruff `target-version`, basedpyright config
- Prefer explicit types and error paths; basedpyright with `typeCheckingMode = "all"` is the default for new projects; existing repo configs win
- Keep raw JSON, env, CLI, API, and RPC data at boundaries; validate once with pydantic/msgspec or narrow typed code
- Model dict-shaped data with `TypedDict`, `Literal`, and discriminated unions while it remains dict-shaped
- Prefer pure transformations, immutable values, copy-on-write updates, protocols, dataclasses, comprehensions/generators, and small modules when they clarify code
- Keep I/O, logging, retries, timeouts, mutation, and process exits in the imperative shell
- Give concepts that must not mix distinct types; use `NewType`, tagged unions, or domain records only when a mix-up would be a real bug
- Own resources with context managers and concurrency with explicit cancellation, timeout, and cleanup scopes
- Keep errors specific and actionable. Catch or translate them only where that layer can make a decision
- Do not add a dependency, abstraction, parser, normalization step, or defensive branch without a concrete caller, boundary, or failure mode
- Use mypy only for inherited repos that already use it

## Stack

Policy defaults for new code. Inherited project configs override defaults.

| Concern | Tool / Standard | Policy |
| --- | --- | --- |
| Packaging | `uv` | uv only; never pip, poetry, conda, or pipenv |
| Type checker | `basedpyright` | `typeCheckingMode = "all"`; existing config wins; mypy only if inherited |
| Linter / format | `ruff` | `select = ["ALL"]` with justified ignores; `ruff format` only |
| Async | `anyio` | `anyio.run`, `create_task_group()`, structured scopes; raw asyncio only if inherited |
| HTTP client | `httpx2` | `httpx2[http2,brotli,zstd]`; inherited code retains requests, aiohttp, or httpx until migrated |
| CLI | `typer` + `rich` | Multi-command apps; stdlib `argparse` for single-file scripts |
| Data | `@dataclass`, PEP 695 | Frozen slots dataclasses; polars + duckdb (never pandas) |
| Web | FastAPI + Pydantic v2 | Parse at edge, keep structs out of domain core |
| ORM | SQLAlchemy 2.x async | Async sessions and typed mapped columns |
| Testing | `pytest` + `anyio` | `@pytest.mark.anyio`; inherited code retains unittest or pytest-asyncio until migrated |

## uv Essentials

Prefer `uv` over raw `python`, `pip`, `poetry`, and `python -m venv` when uv is the intended workflow.

```bash
uv run python script.py
uv run pytest
uv run basedpyright
uv run ruff check .
uv run ruff format --check .
uv run --with httpx2 python script.py
uv add httpx2
uv add --dev pytest anyio basedpyright ruff
uv venv
uv init --script example.py --python 3.14
uv add --script example.py httpx2 rich
uv lock --script example.py
```

Use inline script metadata for standalone scripts that need dependencies:

```python
# /// script
# requires-python = ">=3.14"
# dependencies = ["httpx2"]
# ///
```

## Quality Gate Essentials

- New projects: basedpyright (`typeCheckingMode = "all"`), Ruff lint/format, pytest
- Inherited projects: preserve the existing checker stack unless changing it is part of the task
- Baseline commands:
  - `uv run basedpyright`
  - `uv run ruff check .`
  - `uv run ruff format --check .`
  - `uv run pytest`
- Boundary-heavy code needs contract tests for JSON/API/RPC/CLI ingress and failure paths
- Parser/transform-heavy code should use Hypothesis only for invariants, round-trips, idempotence, and lossless conversion properties
- Tests should be deterministic, isolated, and behavior-focused. Prefer real values, in-memory fakes, or wire-level fakes; mock only an unavailable external edge
- Do not pin private constants, incidental formatting, prose, or one implementation path when the user-visible contract is what matters
- Ruff baseline: `select = ["ALL"]` with narrow, justified per-project ignores; `ruff format` is the only formatter

## Build Note

Use `uv_build` for pure Python packages. For extension modules, prefer an appropriate backend such as `hatchling`.

```toml
[build-system]
requires = ["uv_build>=0.9.28,<0.10.0"]
build-backend = "uv_build"
```

Prefer `src/` layout unless the repository has a strong reason not to.

## Required follow-up reads

Always load `cookbook/modern.md`; load the other references only when the task matches.

| Need | Read | When |
| --- | --- | --- |
| Async I/O, concurrency, cancellation | `cookbook/async.md` | Async behavior is central (anyio) |
| Typing and data boundaries | `reference.md`, `cookbook/correctness.md` | JSON, API, RPC, CLI, or validation boundaries matter |
| Design, ownership, error, or test-quality decisions | `references/engineering.md` | Choosing models, error paths, resource lifecycles, abstractions, or behavioral tests |
| Opinionated stack recipes and deep implementation patterns | `references/advanced/README.md`, then its matching reference | Opinionated recipes that cannot override the policy; inherited projects keep their configured stack |
| Cross-language code-smell or logging review | `references/advanced/engineering/code-smells.md`, `references/advanced/engineering/logging.md` | Reviewing structure or observability beyond Python-specific mechanics |
| Testing and property-based invariants | `cookbook/testing.md`, then matching `cookbook/testing-*.md` | Designing or debugging tests |
| Baseline idioms and prohibitions | `cookbook/modern.md` | Always, before any Python work |
| Functional, iterator, or design patterns | `cookbook/patterns.md`, then matching pattern guide | Choosing an implementation pattern |
| Packaging, uv, metadata, build backends | This file, project config, official tool output | Packaging or dependency work |

## Must / Must Not

- MUST type public APIs, validate untrusted inputs at boundaries, prefer pathlib, and respect the project runtime target
- MUST use `uv` for running Python, adding deps, script metadata, and env setup when uv is intended
- MUST keep validators, raw payloads, mocks, retries, and I/O out of core logic unless they are the domain being modeled
- MUST NOT use mutable default args, bare `except`, untracked background tasks, blocking calls in async code, or broad fallbacks that hide bad input
- MUST NOT keep known payloads as `dict[str, Any]`, propagate raw JSON inward, or carry boundary validator objects through core logic by accident
- MUST follow every rule in `cookbook/modern.md` that the project's `requires-python` allows, and MUST NOT write anything in its Never table
