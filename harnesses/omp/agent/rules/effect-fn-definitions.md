---
description: Enforce Effect.fn("name") for named Effect-returning functions and prohibit raw Effect.gen returns
condition:
  - "(?:\\bfunction\\s+\\w+\\s*\\([^)]*\\)\\s*(?::\\s*Effect\\b|\\{.*return\\s+Effect\\.gen\\b)|\\bconst\\s+\\w+\\s*=\\s*\\([^)]*\\)\\s*=>\\s*Effect\\.gen\\b|\\basync\\s+function\\s+\\w+.*Effect\\b)"
scope:
  - tool:edit(*.ts)
  - tool:edit(**/*.ts)
  - tool:write(*.ts)
  - tool:write(**/*.ts)
---

When defining functions that return an `Effect`, use `Effect.fn("functionName")` with generator syntax. Avoid plain functions that return `Effect.gen(...)` and NEVER mark an Effect-returning function as `async`.

## Rules

- Use `Effect.fn("name")` for all top-level and exported functions that return an Effect.
- Always provide a descriptive string name to `Effect.fn("name")` to ensure informative stack traces and automatic OpenTelemetry/tracing span attachment.
- Reserve `Effect.gen` exclusively for local, inline sequential composition inside existing blocks (e.g. inside CLI action handlers or tests).
- NEVER mark a function `async` if it returns an `Effect` or constructs an Effect pipeline.

## Why

- `Effect.fn("name")` automatically attaches a tracing span, captures fiber location, and formats clear stack traces during fiber interruptions or defects.
- Plain functions returning `Effect.gen` lose function boundary spans and introduce unnecessary function invocation overhead.

## Example

```typescript
// BAD — Plain function returning Effect.gen without tracing span
export function scanDeals(query: string) {
  return Effect.gen(function* () {
    const results = yield* fetchDeals(query);
    return results;
  });
}

// BAD — Mixing async with Effect
export async function runQuery(query: string): Promise<Effect.Effect<void>> { ... }

// GOOD — Idiomatic Effect.fn with named tracing span
export const scanDeals = Effect.fn("scanDeals")(function*(query: string) {
  const results = yield* fetchDeals(query);
  return results;
});
```
