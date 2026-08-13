# JavaScript Reference

Use for defaults, routing, or failure-mode triage before a deeper cookbook.

## Decision defaults

- Existing ESM → stay ESM — format churn rarely fixes the issue.
- Existing CJS → stay CJS unless interop pain is the task — blind mixing multiplies failure modes.
- Greenfield Node app/library → prefer ESM — better modern-tooling and native-`import` alignment.
- Browser/bundler app → write ESM source — bundler owns final output format.
- Package shipping to mixed consumers → consider dual exports only when demand is real — dual mode adds surface area and testing burden.
- Vite/bundler repo without a runner → prefer Vitest — zero-friction module story and fast watchless runs.
- Existing Jest monorepo/ecosystem-heavy repo → stay on Jest — migration cost outweighs novelty value.
- Large payloads/long-lived flows → prefer streams + cancellation — prevent memory spikes and hanging work.
- Weird language behavior → check semantics before architecture — JS bugs often involve coercion, binding, or queue issues.
- External I/O logic → use integration tests — unit mocks hide boundary breakage.

## Failure-mode router

- `require is not defined`, `__dirname` missing, or weird import paths → ESM/CJS mismatch, `type: module`, or bad exports → `cookbook/modules.md`.
- `undefined` receiver, stale state, or callback losing method context → call-site binding, closures, or arrow-vs-function behavior → `cookbook/semantics.md`.
- Out-of-order logs, `setTimeout(..., 0)` losing to Promise, or hanging async work → task-queue ordering, forgotten `await`, or unhandled rejection → `cookbook/async.md`.
- Late process exit or growing memory → open timers/listeners, unclosed streams, or worker/process leaks → `cookbook/async.md`, `cookbook/node.md`.
- UI jank or observer/event leaks → main-thread hot loops, too many listeners, or bad DOM observation → `cookbook/browser.md`, `cookbook/patterns.md`.
- Flaky time/fetch/UI tests → bad fake-timer usage, over-mocking, or missing async assertions → `cookbook/testing.md`.

## Validation ladder

### Detect package manager

```bash
if [ -f bun.lockb ] || [ -f bun.lock ]; then PM=bun;
elif [ -f pnpm-lock.yaml ]; then PM=pnpm;
elif [ -f yarn.lock ]; then PM=yarn;
else PM=npm; fi
echo "$PM"
```

### Validate in order

1. Repo scripts first: `$PM run test`; `$PM run lint`; `$PM run build`.
2. Cheap syntax/import checks: `node --check path/to/file.js`; targeted runner command for the changed test file.
3. When behavior is weird: `NODE_OPTIONS=--trace-warnings node path/to/entry.mjs`; use `node --inspect path/to/entry.mjs` for heap/CPU inspection.
4. Run broader suites only after local validation passes.

For a local, reversible change, do not default to watch mode, dev servers, or broad end-to-end runs.

## Interop rules

- In a package, `"type": "module"` changes `.js` meaning.
- In an ESM package, use `.cjs` for files that must remain CommonJS.
- In an otherwise CJS package, use `.mjs` only for file-level ESM.
- `package.json#exports` hides deep imports by default; define subpath exports intentionally.
- Use `createRequire(import.meta.url)` only at an interop edge; do not spread it through the codebase.
- Use dynamic `import()` for optional, environment-specific, or heavy paths—not as a band-aid for unclear module boundaries.
- Circular imports usually indicate execution-order, not syntax, bugs; break cycles with smaller modules or dependency inversion.

## Testing rules

- Unit-test pure transforms and business rules.
- Integration-test filesystem, HTTP, DB, queue, and browser boundary code.
- UI-test rendered behavior, not implementation details.
- Prefer factories/fixtures over giant inline objects.
- Fake timers only when code is actually timer-driven.
- Use snapshots for stable structured output, not giant trees you will rubber-stamp forever.

## Boundary and design checks

- Parse and normalize untrusted input once at an API, file, queue, CLI, or environment boundary; pass the normalized value inward instead of repeating loose checks throughout the call chain.
- Keep retries, timeouts, cancellation, cleanup, logging, and process exits at I/O boundaries. Pure transforms and private helpers SHOULD NOT own process-wide policy.
- Model meaningful outcomes explicitly: tagged objects beat truthy sentinels and a forest of optional fields when callers must distinguish states.
- Catch only where code can recover, translate for a caller, or add context. Preserve `cause` when wrapping; rethrow failures the boundary does not own.
- Add dependencies, abstractions, parsers, normalization layers, and defensive branches only for a demonstrated caller or failure mode.
- Before extending large files, parameter bundles, negative-name mazes, redundant post-action checks, or broad catches, review them. Keep a local change local unless the task requests redesign.

## Performance

- Prefer streaming/chunked processing over `await readFile()` for massive payloads.
- Prefer `Promise.all` for independent work; avoid accidental serial loops.
- For CPU-heavy browser work, yield off the main thread; use workers when the work is real.
- Measure before rewriting hot paths. The bug is often event/listener churn, not syntax choice.
- Avoid hidden quadratic work from nested loops, repeated spreads in hot paths, or cloning giant objects each iteration.

## Neighbor skills

- `typescript` — load alongside this skill when types, declarations, or `tsconfig` dominate.
- `react-best-practices` — load alongside this skill for React/Next render and bundle performance.
- `research` → `context7` / `grep-app` — load for library-specific API work, not language mechanics.

## File map

- `cookbook/semantics.md` — coercion, equality, scope, closures, `this`, prototypes.
- `cookbook/patterns.md` — modern syntax, immutable updates, iterators, utility patterns.
- `cookbook/async.md` — event loop, cancellation, queues, async iteration, streams.
- `cookbook/modules.md` — ESM/CJS, `package.json`, exports, imports, tree shaking.
- `cookbook/node.md` — fs, path/url, streams, workers, processes.
- `cookbook/browser.md` — fetch, workers, storage, observers, perf APIs.
- `cookbook/testing.md` — runner choice, mocks, timers, UI testing, fixtures.
