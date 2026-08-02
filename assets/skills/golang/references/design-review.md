# Go Design and Review Checks

Read this before changing domain types, concurrency ownership, tests, or a public package boundary.

## Types and states

- Give identifiers, units, paths rooted in different places, and similarly shaped values distinct named types when mixing them would be a real bug.
- Parse raw JSON, environment, CLI, database, and API data at the edge. Convert it to the domain representation once; do not carry `map[string]any`, request DTOs, or database rows through core logic.
- Use an unexported field and constructor when a value has an invariant that callers must not bypass. Keep an exported, zero-value-friendly struct when that invariant does not exist.
- Use typed string constants for externally visible enum values. Use a sealed interface only for a genuinely closed variant set owned by one package; do not simulate algebraic data types for ordinary structs.
- Prefer exhaustive handling of states you own. A catch-all is appropriate for forward-compatible external enums, where it must preserve or report the unexpected value.

## Boundaries and ownership

- Add a dependency, generic helper, parser, retry, normalization layer, or interface only when a concrete caller or boundary needs it. Reuse the first adequate stdlib feature or existing project helper.
- Put `context.Context` first, derive cancellation at the operation boundary, and call its cancel function. The code that opens a resource owns closing it unless ownership is explicitly transferred.
- Propagate or wrap failures with action context. Create a sentinel or typed error only when a caller needs to branch on the condition or data.
- Do not use context values for dependencies or business inputs. Keep deadlines, cleanup, and side effects at the I/O/concurrency edge.

## Tests and review

- Test inputs and observable outputs, not private helpers, prose, incidental formatting, or one implementation path.
- Start with real values and pure functions; then an in-memory fake, `httptest`, or an integration test. Mock only a genuinely unavailable external edge.
- Keep time, randomness, filesystem state, and network I/O deterministic when the assertion depends on them. Use `t.TempDir`, `t.Cleanup`, injected time/randomness, or an `httptest` server as needed.
- Treat a large file, parameter bundle, nested negative conditions, a broad recovery branch, or duplicated post-action verification as a design-review signal. Fix only when the task or a concrete defect warrants it.
