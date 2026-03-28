# Correctness and Boundaries

Use the smallest tool that makes failures obvious: Pyright strict first, runtime validation only at the edges, and plain typed objects everywhere else.

## Pyright strict baseline

New projects should start with Pyright strict enabled. Treat it as the primary static gate; if a legacy repo still runs mypy, keep it as a secondary check, not the decision-maker.

### `pyproject.toml`

```toml
[tool.pyright]
typeCheckingMode = "strict"
include = ["src", "tests"]
exclude = [".venv", "build", "dist"]
```

### `pyrightconfig.json`

```json
{
  "typeCheckingMode": "strict",
  "include": ["src", "tests"],
  "exclude": [".venv", "build", "dist"]
}
```

Baseline checks:

```bash
uv add --dev pyright ruff pytest
uv run pyright
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

If you inherit a loose codebase, use `strict = ["src"]` only as a migration step. New projects should not stop there.

## Boundary validation

Use static types for known JSON shape:

| Shape | Prefer |
|-------|--------|
| object with fixed keys | `TypedDict` |
| fixed field value | `Literal` |
| small variant set | discriminated union (`kind` / `type` tag) |

Use runtime validators only when bytes or JSON text cross a boundary:

| Need | Tool |
|------|------|
| fast typed decode/encode and lightweight structs | `msgspec` |
| richer validation, aliases, or an existing Pydantic API | `pydantic` |

Choose one boundary tool per edge. Parse once, normalize once, then hand the rest of the app plain typed objects.

## What not to do

- Don't use `dict[str, Any]` for known payloads.
- Don't keep `BaseModel` or `Struct` objects in core business logic.
- Don't validate every function argument at runtime.
- Don't silently coerce bad input with ad hoc `str()`, `int()`, or defaulting chains.
- Don't stack multiple validation libraries on the same edge.

## Tiered quality gates

Pick the smallest gate that matches the project shape:

| Project shape | Baseline gate | Add when needed |
|---------------|---------------|-----------------|
| small library / CLI | `pyright` strict + `ruff` check/format + `pytest` | — |
| API or service with external input | baseline + boundary tests | schema fixtures for request/response shapes |
| parser / transformer / serializer | baseline + boundary tests | targeted Hypothesis properties |
| legacy codebase | strict on new code first | expand to full repo once the deltas are paid down |

Static gate order: `pyright` strict first, then lint/format, then tests.
