# Effect application engineering

Read this reference when creating or materially changing a user-owned Effect application. Also read `code-quality.md`, load the TypeScript skill, and read `references/bun-application.md` from that skill. The TypeScript reference owns Bun, TypeScript 7, ESM, Oxc, and `bun:test`; this reference owns Effect.

## Version and source policy

Use stable Effect v4 for new applications. Inspect installed metadata or query registry JSON with Bun and `fetch` to verify versions. Do not invoke npm for registry lookup.

Use matching stable v4 releases even if the registry still exposes beta or RC dist-tags. Preserve a prerelease only when maintaining a project that explicitly pins it.

```text
bun add effect@4 @effect/platform-bun@4
bun add --dev @effect/tsgo
bunx @effect/tsgo setup
```

Keep Effect runtime packages on the same version. Tooling such as `@effect/tsgo` uses its own version series.

Verify the installed TypeScript, Effect, platform, and `@effect/tsgo` versions. Do not trust dist-tags to be compatible. Do not silently downgrade TypeScript or Effect. Report exact incompatibilities and ask for a decision.

Never mix Effect v3 and v4 packages, package names, imports, documentation, or examples.

When maintaining an existing project, inspect its manifest, lockfile, imports, installed exports, and declarations first. Honor the pinned major version for the requested maintenance task. Do not migrate an existing v3 project to v4 without approval, and never use v4 guidance as if it applied to v3.

Inspect the shared vendored Effect source checkout under the configured vendored sources directory (or the upstream repository `Effect-TS/effect`).

If the checkout is absent, clone it under the global vendored-source policy. Read `LLMS.md`, `MIGRATION.md`, package manifests, implementation, tests, and examples relevant to the task. Prefer source patterns over guesses and fragmented web snippets.

The project version remains authoritative. If the shared checkout does not match the installed project version, state the mismatch. Inspect the installed package or a temporary shallow clone of the matching tag instead of pretending that `main` is compatible.

## Diagnostics

Use `@effect/tsgo` as the sole TypeScript editor language service. Do not run the regular TypeScript-Go language server beside it. Keep compiler diagnostics and Effect-aware diagnostics as separate gates:

```text
bunx tsc --project tsconfig.json --noEmit
bunx @effect/tsgo diagnostics --project tsconfig.json
```

Add this script beside the TypeScript skill's standard scripts:

```json
{
  "scripts": {
    "effect:diagnostics": "bunx @effect/tsgo diagnostics --project tsconfig.json"
  }
}
```

Bun transpilation does not replace either diagnostic gate.

## Program structure

Keep pure business logic as ordinary pure TypeScript when it does not need Effect. Do not create a service, Layer, or Effect wrapper for a simple pure function.

Use current Effect v4 idioms:

- Use `Effect.gen` for readable sequential Effect programs.
- Use `Effect.fn("functionName")` for named functions that return Effects.
- Import `Schema` from `effect` for domain models, runtime validation, serialization, and unknown external data.
- Use `Schema.TaggedError` for expected domain and application failures.
- Use `Context.Service` for external or replaceable capabilities.
- Use `Layer` for dependency construction, composition, and replacement.
- Use `Config` instead of reading environment variables throughout business logic.
- Use `Schedule` for explicit retry and repetition policy.
- Use `Scope` and scoped Layers for owned resources.
- Use `Stream`, `Queue`, `Ref`, and `Deferred` only when the requirements need their semantics.
- Use `DateTime` instead of raw `Date` or scattered `Date.now()` for application-level time.
- Use Effect's structured logging, tracing, and metrics when the application needs observability.

Keep runtime-specific APIs behind Effect services and platform Layers. Keep domain logic independent from Bun-specific APIs.

Use `Effect.acquireRelease`, `Scope`, and scoped Layers for resources that must close. Make ownership, interruption, timeout, retry, and cleanup explicit.

Use `Effect.tryPromise` or the current v4 constructor when wrapping Promise APIs. Pass cancellation signals through supported boundaries. Do not make an Effect-returning function `async` or wrap a yielded Effect in JavaScript `try/catch`.

Represent expected failures in the Effect error channel. Preserve actionable context. Translate external failures once; recover selectively by tag. Do not use exceptions as the normal domain-error mechanism, hide expected failures as defects, swallow failures in broad catches, or catch merely to log and rethrow.

Do not leave Effects floating. Yield, compose, return, or intentionally assign every Effect; use `return yield*` for terminal Effects. Do not call `Effect.runPromise`, `Effect.runSync`, or equivalent runners inside business logic, and never bounce an Effect through a Promise and back into Effect.

For a standalone Bun application, run the final program at the process boundary with the current `BunRuntime.runMain` API. A host framework such as Pi owns its process; follow that host's boundary policy instead of installing another main runtime.

## External capabilities

Use `Context.Service` and `Layer` for databases, APIs, configuration, filesystems, clocks, queues, and other capabilities that tests or deployments replace. Add each service only for a concrete boundary or reuse need.

For CLI applications, use the v4 CLI modules from `effect/cli`:

```ts
import { Argument, Command, Flag } from "effect/cli"

const searchCommand = Command.make("search", {
  query: Argument.String("query").pipe(
    Argument.withDescription("Search query words"),
    Argument.variadic({ min: 1 })
  ),
  provider: Flag.String("provider").pipe(
    Flag.withDescription("Explicit provider name"),
    Flag.optional
  ),
  limit: Flag.Int("limit").pipe(
    Flag.withDescription("Source limit"),
    Flag.withDefault(2)
  )
}, (config) => handleSearch(config)).pipe(
  Command.withDescription("Search CLI tool")
)
```
For HTTP applications, use the current v4 HTTP modules and Bun platform adapter:

```ts
import * as Http from "effect/http"
import * as HttpApi from "effect/http-api"
```

Do not add Express, Fastify, Hono, or Elysia by default.

For SQL applications, use `effect/sql` and the matching v4 driver. Add only the required driver:

```text
bun add @effect/sql-sqlite-bun@4
bun add @effect/sql-pg@4
```

Use Effect SQL directly unless the user requests an ORM. Do not add Prisma, Drizzle, Sequelize, or TypeORM by default.

For new OTLP export, prefer `effect/observability`. Add `@effect/opentelemetry` only to integrate with an existing OpenTelemetry setup.

Do not add Effect AI packages because an AI agent writes the code. Use `effect/ai` or `@effect/ai-*` only for requested AI functionality.

Stable v4 does not stabilize every API. Check the installed API's `@stability` tag. Unstable APIs can break in minor releases; experimental APIs can break in patch releases.

Do not add cluster, workflow, persistence, reactivity, workers, sockets, event-log, or other advanced modules unless a requirement specifically needs them.

## Testing

Use Bun's built-in `bun:test`. Do not add Vitest, Jest, or `@effect/vitest` by default.

Test:

- pure domain logic
- successful Effect execution
- expected typed failures
- service behavior and Layer replacement
- resource acquisition, interruption, and cleanup
- concurrency behavior when relevant
- configuration decoding
- HTTP, CLI, SQL, or other boundaries that the application exposes
Prefer test Layers, test services, `TestClock`, in-memory edges, and dependency replacement over global module mocking. Keep tests deterministic. Do not require live credentials unless the task explicitly requests an integration test.

Effect platform services such as `FileSystem` and `Path` perform asynchronous operations (`exists`, `readFileString`). Attempting to drive them with `Effect.runSync` will fail. Always drive platform-dependent Effect programs with `await Effect.runPromise(...)` in test suites.
## Dependency exclusions

Do not use old Effect package names or v3-only tutorials:

- `@effect/schema`
- old `@effect/cli`
- old `@effect/platform`
- old `@effect/rpc`
- old `@effect/cluster`
- `effect-smol`

Do not add Zod, fp-ts, neverthrow, RxJS, an HTTP framework, an ORM, or unnecessary utility libraries beside Effect unless a concrete integration requirement makes the dependency unavoidable. Explain the tradeoff before adding excluded technology.

## Workflow

Before coding:

1. Define the requested outcome and acceptance criteria.
2. Inspect the project versions, installed exports, declarations, and nearest working code.
3. Inspect matching vendored Effect source, `LLMS.md`, `MIGRATION.md`, tests, and examples.
4. Read `code-quality.md` and use live Effect v4 documentation for API questions.
5. State the smallest architecture, services, Layers, and dependencies for non-trivial work.
6. Add or update a failing test first when the behavior has a cheap local test path.

While coding:

1. Keep domain logic pure where practical.
2. Decode unknown data once with `Schema` at the boundary.
3. Keep external capabilities behind explicit services and Layers.
4. Do not invent Effect APIs from memory.
5. Preserve existing user changes and avoid unrelated files.
6. Add no compatibility shim, fallback, abstraction, or package without a current caller or failure mode.
7. Keep Effect sequencing, typed failures, concurrency, and resource ownership inside Effect; bridge foreign control flow once at the edge.

After coding, perform the mandatory review pass in `code-quality.md`, then run the TypeScript skill's gates plus:

```text
bun run effect:diagnostics
```

Run the application or relevant command with Bun when possible. Fix failures introduced by the change and rerun the failed gate.

Report the implementation, changed files, dependencies, commands, diagnostics, tests, assumptions, and remaining risks or decisions.

## Authoritative sources

Use sources in this order:

1. Project manifest, lockfile, installed `effect/AGENTS.md`, exports, and declarations.
2. Matching vendored Effect implementation, tests, examples, `LLMS.md`, and `MIGRATION.md`.
3. Current official documentation and source:
   - <https://www.effect.website/docs/v4>
   - <https://github.com/Effect-TS/effect/tree/main>
   - <https://github.com/Effect-TS/effect/blob/main/LLMS.md>
   - <https://github.com/Effect-TS/effect/blob/main/MIGRATION.md>
   - <https://github.com/Effect-TS/tsgo>

When these sources disagree, follow the project-installed version and state the mismatch. Never guess an API from model memory.
