# JavaScript Reference

Use this file when you need defaults, routing, or failure-mode triage before diving into a deeper cookbook.

## Decision matrix

| Situation                                     | Default                                      | Why                                                      |
| --------------------------------------------- | -------------------------------------------- | -------------------------------------------------------- |
| Existing repo already uses ESM                | Stay ESM                                     | Format churn is rarely the fix                           |
| Existing repo already uses CJS                | Stay CJS unless interop pain is the task     | Mixing both blindly multiplies failure modes             |
| Greenfield Node app / library                 | Prefer ESM                                   | Better alignment with modern tooling and native `import` |
| Browser / bundler app                         | Write ESM source                             | Bundler owns final output format                         |
| Shipping package to mixed consumers           | Consider dual exports only if demand is real | Dual mode adds surface area and testing burden           |
| Vite / bundler repo with no runner yet        | Prefer Vitest                                | Zero-friction module story and fast watchless runs       |
| Existing Jest monorepo / ecosystem-heavy repo | Stay on Jest                                 | Lower migration cost than novelty value                  |
| Large payloads or long-lived flows            | Prefer streams + cancellation                | Prevent memory spikes and hanging work                   |
| Weird language behavior                       | Check semantics before architecture          | JS bugs are often coercion / binding / queue issues      |
| External I/O logic                            | Use integration tests                        | Unit mocks hide boundary breakage                        |

## Failure-mode router

| Symptom                                                                             | Likely causes                                                     | Read next                                     |
| ----------------------------------------------------------------------------------- | ----------------------------------------------------------------- | --------------------------------------------- |
| `require is not defined`, `__dirname` missing, import path weirdness                | ESM/CJS mismatch, `type: module`, bad exports                     | `cookbook/modules.md`                         |
| `undefined` receiver, stale state, callback loses method context                    | call-site binding, closures, arrow vs function                    | `cookbook/semantics.md`                       |
| Logs appear out of order, `setTimeout(..., 0)` loses to Promise, hanging async work | task queue ordering, forgotten `await`, unhandled rejection       | `cookbook/async.md`                           |
| Process exits late or memory keeps growing                                          | open timers/listeners, unclosed streams, worker/process leaks     | `cookbook/async.md`, `cookbook/node.md`       |
| UI jank or observer/event leaks                                                     | hot loops on main thread, too many listeners, bad DOM observation | `cookbook/browser.md`, `cookbook/patterns.md` |
| Flaky tests around time, fetch, or UI                                               | bad fake-timer usage, over-mocking, async assertions missing      | `cookbook/testing.md`                         |

## Validation ladder

### Detect the package manager

```bash
if [ -f bun.lockb ] || [ -f bun.lock ]; then PM=bun;
elif [ -f pnpm-lock.yaml ]; then PM=pnpm;
elif [ -f yarn.lock ]; then PM=yarn;
else PM=npm; fi
echo "$PM"
```

### Run validations in this order

1. **Repo scripts first**
   - `$PM run test`
   - `$PM run lint`
   - `$PM run build`
2. **Cheap syntax / import checks**
   - `node --check path/to/file.js`
   - targeted runner command for the changed test file
3. **Runtime diagnostics when behavior is weird**
   - `NODE_OPTIONS=--trace-warnings node path/to/entry.mjs`
   - `node --inspect path/to/entry.mjs` when you need heap / CPU inspection
4. **Broader suites only when local validation passes**

Avoid defaulting to watch mode, dev servers, or broad end-to-end runs when the change is local and reversible.

## Interop rules that prevent pain

- `"type": "module"` changes what `.js` means inside that package
- Use `.cjs` for files that must stay CommonJS in an ESM package
- Use `.mjs` only when you need file-level ESM in an otherwise CJS package
- `package.json#exports` hides deep imports by default. Define subpath exports intentionally
- Use `createRequire(import.meta.url)` only at an interop edge. Do not spray it through a codebase
- Dynamic `import()` is for optional, environment-specific, or heavy code paths. It is not a band-aid for unclear module boundaries
- Circular imports usually mean execution-order bugs, not syntax bugs. Break the cycle with smaller modules or dependency inversion

## Testing rules that keep signal high

- Unit-test pure transforms and business rules
- Integration-test filesystem, HTTP, DB, queue, and browser boundary code
- UI-test rendered behavior, not implementation details
- Prefer factories / fixtures over giant inline objects
- Fake timers only when the code is actually timer-driven
- Use snapshots for stable structured output, not giant trees you will rubber-stamp forever

## Boundary and Design Checks

- Parse and normalize untrusted input once at an API, file, queue, CLI, or environment boundary. Pass the normalized value inward instead of repeating loose checks throughout the call chain
- Keep retries, timeouts, cancellation, cleanup, logging, and process exits at I/O boundaries. Pure transforms and private helpers should not own process-wide policy
- Model meaningful outcomes explicitly—tagged objects beat truthy sentinels and a forest of optional fields when callers must distinguish states
- Catch only where code can recover, translate for a caller, or add context. Preserve `cause` when wrapping and rethrow failures the boundary does not own
- Add dependencies, abstractions, parsers, normalization layers, and defensive branches only for a demonstrated caller or failure mode
- Review large files, parameter bundles, negative-name mazes, redundant post-action checks, and broad catches before extending them. Keep a local change local unless the task asks for a redesign

## Performance rules of thumb

- Prefer streaming or chunked processing over `await readFile()` on massive payloads
- Prefer `Promise.all` for independent work; avoid accidental serial loops
- Yield off the main thread for CPU-heavy browser work; use workers when the work is real
- Measure before rewriting hot paths. The bug is often event/listener churn, not syntax choice
- Avoid hidden quadratic work from nested loops, repeated spreads in hot paths, or cloning giant objects each iteration

## Neighbor skills

- `typescript` - load alongside this skill when types, declarations, or `tsconfig` dominate
- `react-best-practices` - load alongside this skill for React / Next render and bundle performance
- `research` -> `context7` / `grep-app` - load for library-specific API work, not language mechanics

## File map

- `cookbook/semantics.md` - coercion, equality, scope, closures, `this`, prototypes
- `cookbook/patterns.md` - modern syntax, immutable updates, iterators, utility patterns
- `cookbook/async.md` - event loop, cancellation, queues, async iteration, streams
- `cookbook/modules.md` - ESM/CJS, `package.json`, exports, imports, tree shaking
- `cookbook/node.md` - fs, path/url, streams, workers, processes
- `cookbook/browser.md` - fetch, workers, storage, observers, perf APIs
- `cookbook/testing.md` - runner choice, mocks, timers, UI testing, fixtures
