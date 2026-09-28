---
description: Prefer basedpyright, Ruff ALL linting, focused pytest, and property tests for Python invariants
condition:
  - "\\b(?:basedpyright|pyright|mypy|ruff|pytest|pytest-asyncio|hypothesis|coverage|pytest-cov)\\b"
  - "\\[tool\\.(?:basedpyright|pyright|ruff|pytest|coverage)\\]|pyrightconfig\\.json|pyproject\\.toml"
  - "\\bmock\\.|\\bMock\\b|\\bMagicMock\\b|\\bpatch\\s*\\(|@pytest\\.mark\\.(?:parametrize|anyio|asyncio)|pytest\\.raises"
  - "@pytest\\.mark\\.parametrize|pytest\\.raises|\\bpytest\\.approx\\b|\\bassert\\s+[^\\n]+==\\s+(?:True|False|None|\\[\\]|\\{\\}|\\(\\))\\b"
scope:
  - tool:edit(*.py)
  - tool:edit(**/*.py)
  - tool:write(*.py)
  - tool:write(**/*.py)
interruptMode: never
---

Use modern Python quality gates and tests that defend behavior.

Quality gate defaults:

- Use `basedpyright` (`uv run basedpyright`, never the `pyright` CLI) as the primary static type gate.
- Set `typeCheckingMode = "all"` for new projects; an inherited repository's configured mode wins.
- Keep `mypy` only for inherited repositories that already use it; do not introduce `mypy` in new projects.
- Use Ruff for linting and formatting. Configure `select = ["ALL"]` with narrow per-project ignores that are each justified. `ruff format` is the only formatter.
- Ban `Any` in annotations (contain third-party `Any` at boundaries and narrow immediately). Use `object` only for genuinely unknown values (`__eq__`, unvalidated boundary inputs before `isinstance`/`match`), never where a `Protocol`, PEP 695 type parameter, union, or `TypedDict` fits.
- Mark justified boundary `except Exception` catches with the real Ruff rule and a reason (`# noqa: BLE001 - <reason>`); NEVER use invented codes such as `BROAD_EXCEPT_OK` or `OBJECT_OK`.
- Respect configured `target-version` and `requires-python`; do not modernize syntax beyond the project's runtime.

Recommended gate order:

1. `uv run basedpyright`
2. `uv run ruff check .`
3. `uv run ruff format --check .`
4. `uv run pytest`

Testing defaults:

- Use `pytest` (never `unittest`).
- Use AnyIO's pytest plugin (`@pytest.mark.anyio`) for async tests, never `pytest-asyncio`.
- Test behavior and contracts, not internal wiring.
- Prefer parametrized tests with descriptive IDs for input matrices.
- Use `pytest.raises(..., match=...)` for error contracts when message semantics matter.
- Use `pytest.approx` for floating point comparisons.
- Use `tmp_path` and fixtures for filesystem boundaries.
- Use real parsers/serializers and boundary fixtures (such as `httpx2.MockTransport` for HTTP); do not test only that code runs.
- Avoid tautological tests and placeholder assertions.

Property-based testing:

- Use Hypothesis only when the property is the point: parsers, normalizers, serializers, idempotence, round-trips, and invariants.
- Keep strategies narrow and domain-shaped; turn useful counterexamples into normal regression tests.
- Do not use Hypothesis for one-off branch coverage, trivial getters/setters, or filesystem/network glue.

Mocking:

- Prefer dependency injection and boundary seams over patching global/module state.
- Patch where the dependency is used; use `AsyncMock` for async dependencies.
- Do not mock the unit under test or over-assert incidental call order.

Coverage:

- Coverage thresholds are only useful with meaningful behavior tests.
- Prefer edge-case and failure-path tests for parser/transform/API-boundary-heavy code.
