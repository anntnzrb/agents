# Effect code quality

Read this reference before creating, materially changing, or reviewing Effect code. Apply API names only to matching v4 projects. Preserve these structural rules with version-matched APIs in v3.

## Classify boundaries before editing

For every changed function that touches Effect or asynchronous control flow, classify it before the first edit:

- **Pure TypeScript** computes values without an effectful dependency. Keep it out of Effect.
- **Effect program** returns `Effect` and owns sequencing, expected failures, interruption, retry, and resources.
- **Host adapter** satisfies a framework, process, test, or legacy Promise or callback contract and converts once at the edge.

Before patching:

1. Assign sequencing, failure translation, interruption, and cleanup to one owner.
2. Trace at least one complete changed path.
3. Reject mechanical Promise-to-Effect syntax replacement as a design method.

For multi-step work, keep the classification and final review as an explicit todo or rubric.

Before implementation and again before handoff, inventory these changed constructs:

- JavaScript control flow: `async`, `await`, `Promise`, `try`, and `catch`
- Effect composition: `Effect.gen`, `Effect.fn`, runners, `Effect.promise`, and `Effect.tryPromise`
- Lifecycle: callbacks, fibers, scopes, acquisition, retry, timers, and controllers
- Type escapes: assertions and diagnostic suppressions

These constructs require review, but they are not automatic violations.

## One control-flow owner

- A function whose contract returns `Effect` is not `async`. Keep sequencing, failure, interruption, retry, timeout, and cleanup in Effect.
- Never use JavaScript `try/catch` around `yield*` to handle an Effect failure. Handle the Effect error channel with Effect combinators.
- Use `Effect.gen(function*() { ... })` for local sequential composition. Use `Effect.fn("qualifiedName")` for a reusable named Effect function instead of returning `Effect.gen` from a plain wrapper.
- Attach transforms as additional `Effect.fn` arguments. Do not pipe the function value itself.
- Use `return yield*` for terminal failures, interrupts, or other terminal Effects inside a generator.
- Yield, return, compose, or intentionally assign every Effect. A floating Effect does no work.

Convert non-Effect APIs once:

- Wrap synchronous code that may throw with `Effect.try` and map the unknown cause into a typed error.
- Wrap Promise APIs that may reject with `Effect.tryPromise`. Pass its `AbortSignal` to APIs that support cancellation.
- Use `Effect.promise` only when rejection is impossible by contract. A rejection becomes a defect.
- Wrap callback APIs with `Effect.callback`. Return a finalizer when interruption must unregister or cancel the callback source.
- Run an Effect only at the final process, host-framework, test, or legacy adapter boundary.
- Use one `ManagedRuntime` for a long-lived non-Effect host.
- Never bounce `Effect -> Promise -> Effect`, return `Promise<Effect<...>>`, or call a runner from a service or domain function.

A narrow JavaScript `try/catch` can be valid in a non-Effect host adapter or around local synchronous code. It catches JavaScript exceptions only. Prefer `Effect.try` inside Effect code. Never assume that JavaScript `try/catch` catches a yielded Effect failure.

## Errors carry domain meaning

- Model expected v4 failures with `Schema.TaggedError`. Include operation-specific context and preserve the original cause when translating an external failure.
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
- Keep fiber ownership explicit. Prefer scoped or supervised concurrency. Do not leave forked fibers or Promises running after their owner exits.
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
3. Review the candidate inventory from the entry pass. For each occurrence, identify who owns sequencing, failure translation, interruption, and cleanup. Keep only constructs required by a boundary or demonstrated in matching source.
4. Reject these patterns unless a host boundary demonstrably requires them:
   - an `async` function constructing or returning `Effect.gen`
   - JavaScript `try/catch` around `yield*`
   - `Effect.runPromise` or `Effect.runSync` inside services or business logic
   - nested broad catches or catch-log-rethrow ladders
   - repeated per-call Layer construction or provisioning
   - manual Promise retry, race, timeout, or cleanup inside an Effect workflow
   - floating Effects, unmanaged fibers, or ignored cleanup
   - repeated schema decoding or parallel error representations
5. Treat nested generators, runners, `Effect.promise`, and forked fibers as mandatory review points rather than blanket violations. Keep nested composition only when a local retry, scope, resource lifetime, or other semantic boundary requires it. Identify the final host boundary for every runner and the owner for every fiber.
6. Run ordinary TypeScript diagnostics and `@effect/tsgo` diagnostics separately. Treat `tryCatchInEffectGen`, `floatingEffect`, `missingReturnYieldStar`, `returnEffectInGen`, `leakingRequirements`, and `multipleEffectProvide` findings as design failures to fix, not warnings to suppress.
7. Validate the diagnostics setup before trusting it:
   - Confirm that the language-service plugin is active.
   - Require `filesChecked` to equal the intended nonzero file count.
   - If the setup is new or uncertain, test it with a deliberate known-diagnostic probe.
   - Treat zero checked files as a failed check.
8. Do not add `@effect-diagnostics` suppressions unless a version-matched upstream pattern proves that the exceptional construct is intentional. Document the reason beside the suppression.
9. Run focused tests for success, each expected error type, interruption, and cleanup. Compiler success alone does not prove runtime semantics.

Diagnostics detect configured hazards. They do not prove minimal nesting, correct boundaries, efficient resource ownership, or behavior preservation.

## Completion gate

- If a change touches more than three Effect files or changes resource, fiber, timeout, retry, or cancellation ownership, run an independent read-only review when delegation is available.
- If independent review is unavailable, perform a separate cold pass with the mandatory review rubric. Do not merely reread while implementing.
- Do not claim the work is green or idiomatic without recording the Effect version and source match, expected and checked diagnostic counts, ordinary TypeScript result, relevant tests, and structural review result.
- State deliberate exceptions such as required nested generators, host-boundary runners, or manually owned fibers. Separate introduced failures from verified baseline failures.
- Preserve behavior outside the requested Effect change.
- Treat unrelated rewrites found in the diff as regressions unless the user approved them.
