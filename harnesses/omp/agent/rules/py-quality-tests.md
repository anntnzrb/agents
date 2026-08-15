---
description: Prefer Pyright strict, Ruff modern linting, focused pytest, and property tests for Python invariants
condition:
  - "\\b(?:pyright|mypy|ruff|pytest|hypothesis|coverage|pytest-cov)\\b"
  - "\\[tool\\.(?:pyright|ruff|pytest|coverage)\\]|pyrightconfig\\.json|pyproject\\.toml"
  - "\\bmock\\.|\\bMock\\b|\\bMagicMock\\b|\\bpatch\\s*\\(|@pytest\\.mark\\.parametrize|pytest\\.raises"
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

- New Python projects should use Pyright strict as the primary static gate.
- Legacy repos may keep mypy if already established; do not churn checker stacks without a reason.
- Use Ruff for linting and formatting. Prefer `ruff format` as the formatter to avoid formatter churn.
- Prefer a curated Ruff lint set that includes:
  - `E` / `F` for basic correctness
  - `I` for imports
  - `UP` for safe pyupgrade modernization
  - `B` for bugbear correctness checks
  - `SIM` for simplification when it remains readable
- Once baseline is clean, consider opt-in Ruff families:
  - `C4` for better comprehensions
  - `PIE` for miscellaneous Pythonic cleanup
  - `RET` for cleaner return flow
  - `PTH` for pathlib migrations
  - `RUF` for Ruff-native correctness rules
- Respect configured `target-version`; do not modernize syntax beyond the project's runtime.

Recommended gate order:

1. `uv run pyright`
2. `uv run ruff check .`
3. `uv run ruff format --check .`
4. `uv run pytest`

Testing defaults:

- Use pytest.
- Test behavior and contracts, not internal wiring.
- Prefer parametrized tests with descriptive IDs for input matrices.
- Use `pytest.raises(..., match=...)` for error contracts when message semantics matter.
- Use `pytest.approx` for floating point comparisons.
- Use `tmp_path` and fixtures for filesystem boundaries.
- Use real parsers/serializers and boundary fixtures; do not test only that code "runs".
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
