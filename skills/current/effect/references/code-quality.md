# Effect code quality

Read this reference before creating, materially changing, or reviewing Effect code. Apply API names only to matching v4 projects; preserve these structural rules with version-matched APIs in v3.

## One control-flow owner

- A function whose contract returns `Effect` is not `async`. Keep sequencing, failure, interruption, retry, timeout, and cleanup in Effect.
- Never use JavaScript `try/catch` around `yield*` to handle an Effect failure. Handle the Effect error channel with Effect combinators.
- Use `Effect.gen(function*() { ... })` for local sequential composition. Use `Effect.fn("qualifiedName")` for a reusable named Effect function instead of returning `Effect.gen` from a plain wrapper.
- Attach transforms as additional `Effect.fn` arguments. Do not pipe the function value itself.
- Use `return yield*` for terminal failures, interrupts, or other terminal Effects inside a generator.
- Yield, return, compose, or intentionally assign every Effect. A floating Effect does no work.

Convert non-Effect APIs once:

- Wrap synchronous code that may throw with `Effect.try` and map the unknown cause into a typed error.
- Wrap Promise APIs that may reject with `Effect.tryPromise`; pass its `AbortSignal` to APIs that support cancellation.
- Use `Effect.promise` only when rejection is impossible by contract. A rejection becomes a defect.
- Wrap callback APIs with `Effect.callback`; return a finalizer when interruption must unregister or cancel the callback source.
- Run an Effect only at the final process, host-framework, test, or legacy adapter boundary.
- Use one `ManagedRuntime` for a long-lived non-Effect host.
- Never bounce `Effect -> Promise -> Effect`, return `Promise<Effect<...>>`, or call a runner from a service or domain function.

A narrow JavaScript `try/catch` can be valid in a non-Effect host adapter or around local synchronous code. It catches JavaScript exceptions only. Prefer `Effect.try` inside Effect code. Never assume that JavaScript `try/catch` catches a yielded Effect failure.

## Errors carry domain meaning

- Model expected v4 failures with `Schema.TaggedError`; include operation-specific context and preserve the original cause when translating an external failure.
- Translate an external error once at its capability boundary. Do not repeatedly wrap the same failure through every call layer.
- Use `Effect.mapError` to translate without recovery. Use `Effect.catchTag` or `Effect.catchTags` for selective recovery. Use broad `Effect.catch` only when one semantic recovery handles every remaining expected error.
- Do not use defects, thrown exceptions, `orDie`, `catchCause`, or `catchDefect` for ordinary expected failures. Reserve defect-level handling for a deliberate fatal or outer runtime policy.
- Do not catch merely to log and rethrow. Log once where a failure is handled or exits the application boundary.
- Do not represent the same failure simultaneously as a thrown exception, typed Effect error, `Result` union, sentinel, and nullable value. Pick the representation owned by the current boundary.

## Services and Layers earn their existence

- Keep pure business transformations as pure TypeScript. Do not create an Effect, service, or Layer for a function with no effectful dependency.
- Create a `Context.Service` for a cohesive external or replaceable capability, not for every module, function, or data structure.
- Yield services explicitly near the start of a generator so dependencies remain visible. Prefer explicit `yield* Service` over hidden accessor callbacks in non-trivial workflows.
- Define Layers for construction, resource ownership, composition, and test replacement. Compose dependencies in Layer definitions, at the application boundary, or at the test boundary.
- Do not scatter `Effect.provide` through business functions, rebuild the same Layer per call, or add pass-through services that expose an underlying API unchanged.
- Add `Ref`, `Queue`, `Deferred`, `PubSub`, `Stream`, `LayerMap`, or another Effect abstraction only when its semantics match a current requirement.

## Resources, concurrency, and retry

- Use `Effect.acquireRelease`, `Effect.acquireUseRelease`, `Scope`, or scoped Layers for owned resources. Cleanup must run on success, failure, and interruption.
- Keep fiber ownership explicit. Prefer scoped or supervised concurrency; do not leave forked fibers or Promises running after their owner exits.
- Use Effect concurrency operators instead of `Promise.all`, hand-built races, timers, or `AbortController` choreography inside Effect code.
- Use `Schedule` for retries, repetition, and polling. Retry only failures known to be retryable, bound the policy, and ensure the operation is safe to repeat.
- Test interruption and cleanup whenever code owns a resource, background fiber, timeout, or cancellation bridge.

## Data boundaries

- Decode unknown external input once with `Schema` at the boundary. Keep decoded domain values typed and do not re-parse or re-validate them downstream.
- Use Effect `Predicate` helpers for small runtime checks instead of duplicating generic guard helpers.
- Do not repair weak models with `any`, broad assertions, non-null assertions, or repeated defensive checks. Strengthen the boundary schema or domain type.

## Mandatory review pass

1. Inspect the nearest version-matched Effect implementation, tests, `LLMS.md`, migration note, and project precedent for every unfamiliar API.
2. Trace one complete changed path from external input through domain logic and services to the runtime output. Confirm each concern has one owner.
3. Review every changed occurrence of `async`, `await`, `try`, `catch`, `Promise`, Effect runners, `Effect.provide`, manual timers, manual controllers, and diagnostic suppression. Keep only uses required by a boundary or demonstrated in matching source.
4. Reject these patterns unless a host boundary demonstrably requires them:
   - an `async` function constructing or returning `Effect.gen`
   - JavaScript `try/catch` around `yield*`
   - `Effect.runPromise` or `Effect.runSync` inside services or business logic
   - nested broad catches or catch-log-rethrow ladders
   - repeated per-call Layer construction or provisioning
   - manual Promise retry, race, timeout, or cleanup inside an Effect workflow
   - floating Effects, unmanaged fibers, or ignored cleanup
   - repeated schema decoding or parallel error representations
5. Run ordinary TypeScript diagnostics and `@effect/tsgo` diagnostics separately. Treat `tryCatchInEffectGen`, `floatingEffect`, `missingReturnYieldStar`, `returnEffectInGen`, `leakingRequirements`, and `multipleEffectProvide` findings as design failures to fix, not warnings to suppress.
6. Do not add `@effect-diagnostics` suppressions unless a version-matched upstream pattern proves the exceptional construct is intentional; document the reason beside the suppression.
7. Run focused tests for success, each expected error type, interruption, and cleanup. Compiler success alone does not prove runtime semantics.
