---
name: effect-platform-boundary
description: "Keep Effect TypeScript business logic on injected platform services and typed CLI APIs"
condition: "(?:\\b(?:from\\s+|require\\s*\\(\\s*|import\\s*\\(\\s*)[\"']node:(?:fs(?:/promises)?|path|os)[\"']|\\bprocess\\s*\\.\\s*argv\\b|\\bBun\\s*\\.\\s*spawn\\s*\\(|\\bsetTimeout\\s*\\()"
scope: ["tool:edit(**.ts)", "tool:write(**.ts)"]
---

Do not introduce raw Node or Bun primitives into Effect business logic, even inside `Effect.try`, `Effect.sync`, or `Effect.promise`. Yield `FileSystem.FileSystem` and `Path.Path` services, define CLI inputs with `effect/unstable/cli`, and install `BunServices.layer` with `BunRuntime.runMain` only at the composition root. At unavoidable boundary adapters, set spawned-process `stdin` to `"ignore"`, call timer `unref()`, and clear timers when operations settle.