# Correctness and Boundaries

Use smallest tool making failures obvious: basedpyright first; runtime validation only at edges; plain typed objects elsewhere.

## basedpyright baseline

New projects MUST start with basedpyright (`typeCheckingMode = "all"`). Legacy repos MAY retain mypy as a secondary check, never the primary gate.

### `pyproject.toml`

```toml
[tool.basedpyright]
typeCheckingMode = "all"
include = ["src", "tests"]
exclude = [".venv", "build", "dist"]
```

### `basedpyrightconfig.json`

```json
{
  "typeCheckingMode": "all",
  "include": ["src", "tests"],
  "exclude": [".venv", "build", "dist"]
}
```

Baseline checks:

```bash
uv add --dev basedpyright ruff pytest
uv run basedpyright
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Inherited loose codebases: existing configured mode or standard mode migration step only. New projects MUST start with `typeCheckingMode = "all"`.

## Boundary validation

Known JSON shape → static types:

|Shape|Prefer|
|---|---|
|object with fixed keys|`TypedDict`|
|fixed field value|`Literal`|
|small variant set|discriminated union (`kind` / `type` tag)|

Bytes or JSON crossing a boundary → runtime validators:

|Need|Tool|
|---|---|
|fast typed decode/encode and lightweight structs|`msgspec`|
|richer validation, aliases, or an existing Pydantic API|`pydantic`|

Exactly one boundary tool per edge. Parse once, normalize once → plain typed objects for the app.

## Prohibitions

- NEVER use `Any` in annotations or `dict[str, Any]` for known payloads.
- NEVER keep `BaseModel` or `Struct` objects in core business logic.
- NEVER validate every function argument at runtime.
- NEVER silently coerce bad input with ad hoc `str()`, `int()`, or defaulting chains.
- NEVER stack multiple validation libraries on one edge.

## Tiered quality gates

Choose the smallest gate matching project shape:

|Project shape|Baseline gate|Add when needed|
|---|---|---|
|small library / CLI|`basedpyright` + `ruff` check/format + `pytest`|:|
|API or service with external input|baseline + boundary tests|schema fixtures for request/response shapes|
|parser / transformer / serializer|baseline + boundary tests|targeted Hypothesis properties|
|legacy codebase|`basedpyright` on new code first|expand repo-wide once the debt is paid|

Gate order: `basedpyright` -> lint/format -> tests.
