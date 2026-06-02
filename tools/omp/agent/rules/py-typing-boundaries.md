---
description: Prefer strict typing, typed JSON shapes, and single boundary validation for Python
condition:
  - "\\bAny\\b|\\bdict\\s*\\[\\s*str\\s*,\\s*(?:Any|object)\\s*\\]|\\bMapping\\s*\\[\\s*str\\s*,\\s*(?:Any|object)\\s*\\]"
  - "\\bjson\\.loads\\s*\\(|\\.json\\s*\\(\\)|\\bcast\\s*\\(|#\\s*type:\\s*ignore|pyright:\\s*ignore"
  - "\\bBaseModel\\b|\\bTypeAdapter\\b|\\bmsgspec\\.Struct\\b|\\bTypedDict\\b|\\bLiteral\\b|\\bProtocol\\b"
  - "\\bexcept\\s+Exception\\b|\\bexcept\\s*:|\\b(?:List|Dict|Tuple|Set|Optional|Union)\\b"
scope:
  - tool:edit(*.py)
  - tool:edit(**/*.py)
  - tool:write(*.py)
  - tool:write(**/*.py)
interruptMode: never
---

Use strict, explicit Python typing. Treat untyped data as a boundary problem, not a core-logic lifestyle.

Type-system defaults:

- Prefer Pyright strict for new projects (`typeCheckingMode = "strict"`). Mypy is fine for inherited repos that already use it, but do not introduce it as the default gate when Pyright strict is available.
- Public functions and methods should have explicit parameter and return types.
- Avoid `Any`. If an external library forces `Any`, contain it at the boundary, narrow immediately, and document the narrowing.
- Avoid `cast(...)` and `# type: ignore` unless the checker cannot express a real invariant. Prefer better modeling first.
- Use `@dataclass(frozen=True, slots=True)` for immutable domain value objects when appropriate.
- For arguments, prefer protocols and abstract collection types (`Iterable[T]`, `Sequence[T]`, `Mapping[K, V]`) when mutation is not required.
- For returns from concrete implementations, prefer concrete types (`list[T]`, `dict[K, V]`, domain objects).
- Use `object` instead of `Any` when a value may be anything but is only treated generically.
- Prefer `T | None` and put `None` last in unions.
- Prefer `Protocol` for structural interfaces over inheritance-heavy designs.
- Prefer `typing.Self` for fluent/chaining APIs when supported by the target Python version.
- Prefer `@override` for subclass overrides when supported.

JSON / API / RPC shape modeling:

- Use `TypedDict` for dict-shaped payloads with known keys.
- Use `Literal` for fixed field values and mode/status strings.
- Use discriminated unions (`kind`, `type`, `event`, etc.) for small variant sets.
- Do not use `dict[str, Any]` for known payloads.
- Do not pass raw `json.loads(...)`, `response.json()`, or CLI/env payloads through core logic without validation/narrowing.

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
