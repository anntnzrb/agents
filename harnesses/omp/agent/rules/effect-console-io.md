---
description: Prohibit raw console.log and process.stdout.write in Effect codebases; require yield* Console.log
condition:
  - "(?:\\bprocess\\s*\\.\\s*(?:stdout|stderr)\\s*\\.\\s*write\\s*\\(|\\bconsole\\s*\\.\\s*(?:log|error|warn|info)\\s*\\()"
scope:
  - tool:edit(*.ts)
  - tool:edit(**/*.ts)
  - tool:write(*.ts)
  - tool:write(**/*.ts)
---

Do not call raw `console.log`, `console.error`, `process.stdout.write`, or `process.stderr.write` in Effect business logic, commands, or CLI entrypoints. Use the `Console` service from `effect`.

## Rules

- In Effect generator functions (`Effect.fn` / `Effect.gen`), yield `Console.log(...)`, `Console.error(...)`, `Console.warn(...)`, or `Console.info(...)` from `effect`.
- Do not use global `console.log` or write directly to Node/Bun `process.stdout` or `process.stderr`.
- Let the application root provide `BunServices.layer` or `NodeContext.layer` to handle runtime stream redirection.

## Why

- Global `console` and `process.stdout` writes bypass Effect fiber runtime context, tracing spans, test interceptors, and platform loggers.
- Using `Console` from `effect` ensures that all I/O is testable in memory, redirectable across platform layers, and respects fiber concurrency ordering.

## Example

```typescript
// BAD — Unmanaged raw Node/Bun stdout write
function printOutput(data: Report): void {
  process.stdout.write(JSON.stringify(data) + "\n");
}

// BAD — Global un-traced console call
const logReport = Effect.gen(function* () {
  console.log("Starting report generation...");
});

// GOOD — Managed Effect Console service
import { Console, Effect } from "effect";

const emitReport = Effect.fn("emitReport")(function*(data: Report) {
  yield* Console.log(JSON.stringify(data, null, 2));
});
```
