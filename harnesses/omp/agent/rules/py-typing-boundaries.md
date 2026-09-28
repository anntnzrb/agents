---
description: Prefer basedpyright, typed JSON shapes, and single boundary validation for Python
condition:
  - "\\bAny\\b|\\bobject\\b|\\bdict\\s*\\[\\s*str\\s*,\\s*(?:Any|object)\\s*\\]|\\bMapping\\s*\\[\\s*str\\s*,\\s*(?:Any|object)\\s*\\]"
  - "\\bjson\\.loads\\s*\\(|\\.json\\s*\\(\\)|\\bcast\\s*\\(|#\\s*(?:type|pyright|basedpyright):\\s*ignore|\\b(?:BROAD_EXCEPT_OK|OBJECT_OK)\\b"
  - "\\bBaseModel\\b|\\bTypeAdapter\\b|\\bmsgspec\\.Struct\\b|\\bTypedDict\\b|\\bLiteral\\b|\\bProtocol\\b|\\bassert_never\\b"
  - "\\bexcept\\s+(?:Exception|BaseException)\\b|\\bexcept\\s*:|\\b(?:List|Dict|Tuple|Set|Optional|Union|TypeVar|Generic|TypeAlias)\\b"
scope:
  - tool:edit(*.py)
  - tool:edit(**/*.py)
  - tool:write(*.py)
  - tool:write(**/*.py)
interruptMode: never
---

Use explicit Python typing (`skill://python/cookbook/modern.md`). Treat untrusted data as a boundary problem, not a core-logic lifestyle.

Type-system defaults:

- Use `basedpyright` (`uv run basedpyright`, never the `pyright` CLI). Set `typeCheckingMode = "all"` for new projects; an inherited repository's configured mode wins. Use `mypy` only for inherited repositories that already use it.
- Give public functions and methods explicit parameter and return types.
- `Any` is banned in annotations. When a third-party signature forces `Any`, contain it at the boundary and narrow immediately.
- `object` is the correct annotation for a genuinely unknown value (for example `__eq__(self, other: object) -> bool` or unvalidated boundary inputs before `isinstance`/`match` narrowing). NEVER use `object` where a `Protocol`, PEP 695 type parameter, union, or `TypedDict` can express the shape.
- Avoid `cast(...)` and `# pyright: ignore[rule]` / `# type: ignore[rule]` unless the checker cannot express a real invariant.
- Use `@dataclass(frozen=True, slots=True)` by default; use mutable dataclasses only when mutation is the documented purpose.
- On Python 3.12+, declare generics and aliases with PEP 695 syntax (`def f[T](...)`, `class Box[T]:`, `type Alias = ...`). Never use `TypeVar`, `Generic`, `TypeAlias`, `Optional`, `Union`, `List`, or `Dict`. Write unions as `X | None` with `None` last.
- On Python 3.14+, omit `from __future__ import annotations`; keep it below 3.14 where annotations need deferral.
- For parameters, prefer `Protocol` and `collections.abc` interfaces (`Iterable[T]`, `Sequence[T]`, `Mapping[K, V]`) when mutation is not required; return concrete types (`list[T]`, `dict[K, V]`, domain records).
- Prefer `typing.Self` (3.11+), `@override` (3.12+), and `TypeIs[T]` (3.13+) for narrowing predicates when supported by the target runtime.

Variant dispatch and error boundaries:

- Dispatch on discriminated types, enum members, or literal variants with `match` ending in `case _ as unreachable: assert_never(unreachable)`. A single `isinstance` check that narrows one value (such as narrowing `object` at a boundary) is fine.
- Catch the narrowest exception the layer can act on. NEVER use bare `except:` or `except BaseException`.
- Use `except Exception` only at process, request, or task boundaries, and only to log and then re-raise or map. Mark it with the real Ruff code and a reason: `# noqa: BLE001 - <reason>`. NEVER use invented comment codes such as `BROAD_EXCEPT_OK` or `OBJECT_OK`.

JSON / API / RPC shape modeling:

- Use `TypedDict` for dict-shaped payloads with known keys.
- Use `Literal` for fixed field values and mode/status strings.
- Use discriminated unions (`kind`, `type`, `event`, etc.) for variant sets.
- NEVER use `dict[str, Any]` or `dict[str, object]` for known payload shapes.
- Do not pass raw `json.loads(...)`, `response.json()`, or CLI/env payloads through core logic without validation or narrowing.

Boundary validation:

- Validate untrusted bytes/JSON/env/CLI/API inputs once at the edge.
- Use `msgspec` when fast typed decode/encode and lightweight structs fit.
- Use `pydantic` when aliases, richer validation, compatibility, or ecosystem integration matters.
- Prefer Pydantic `TypeAdapter` for validating standalone types and `TypedDict`s without inventing a `BaseModel`.
- Use Pydantic strict mode when coercion would hide bad input.
- Pick one validation library per boundary. Do not stack `pydantic` and `msgspec` for the same edge unless there is a real integration boundary.
- With `msgspec.Struct`, use `forbid_unknown_fields=True` for closed payloads where unexpected keys indicate a bug.
- Convert validated data into plain typed domain objects before core business logic when behavior/invariants matter.
- Do not carry `BaseModel` / `msgspec.Struct` objects through core logic unless the project intentionally uses them as domain models.
