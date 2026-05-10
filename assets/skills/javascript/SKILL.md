---
name: javascript
description: Primary skill for implementing and debugging modern JavaScript across Node.js and browser runtimes with runtime-aware module choices, semantics-first debugging, async/concurrency patterns, performance tuning, and test strategy. Use whenever work touches .js/.mjs/.cjs, package.json module fields, ESM/CJS interop, Promises, event loop behavior, fetch/streams/workers, browser APIs, Node.js APIs, Jest/Vitest/Testing Library, legacy JS refactors, or weird JavaScript behavior. Also use for plain-language requests like 'convert require to import', 'why is this undefined', 'why did Promise run before setTimeout', 'fix flaky JS tests', 'stream this instead of buffering', or 'debug this Node/browser JavaScript bug'. Pair with typescript when .ts/.tsx type-system work is central.
license: GPL-3.0-or-later
metadata:
  author: anntnzrb
allowed-tools: ""
disable-model-invocation: true
---

# JavaScript Development

Modern JS. Runtime-aware. Semantics first. No cargo-cult sludge.

## Activation Triggers

- `.js`, `.mjs`, `.cjs`
- `package.json` when `type`, `exports`, `imports`, entrypoints, or ESM/CJS interop are involved
- `jest.config.*`, `vitest.config.*`, Testing Library setup in JavaScript-first repos
- `import` / `export` / `require`, `type: module`, `exports`, `imports`, dynamic `import()`
- Promises, `async`/`await`, task/microtask ordering, `AbortController`, `fetch`, streams, workers
- closures, `this`, coercion, prototypes, hoisting, TDZ, stale captures, unexpected `undefined`
- Node.js or browser runtime behavior when JavaScript semantics are central
- JS-specific test structure, mocking, fake timers, async test flakiness
- legacy JavaScript refactors where preserving runtime behavior matters

## Workflow

```text
1. DETECT    -> runtime, package manager, module mode, test runner, build tool
2. CLASSIFY  -> semantics bug | async flow | module/interop | runtime API | tests | perf/refactor
3. MODEL     -> data flow, mutation points, cancellation/error boundaries, public API
4. IMPLEMENT -> smallest safe change; prefer native APIs; keep module mode coherent
5. VALIDATE  -> repo scripts first; then targeted tests/lint/build; no watch mode by default
6. HARDEN    -> inspect leaks, circular deps, hot paths, retries/timeouts only where risk justifies
```

## Core Rules

- Choose patterns from **runtime + toolchain**, not aesthetics.
- Prefer **const**, local immutability, and pure transforms by default. Mutate locally when it is simpler or measurably faster.
- Use `async` / `await` for orchestration. Use Promise combinators for concurrency. Expose **cancellation** on long-lived or user-driven work.
- For independent async work, check for accidental serialization in loops before optimizing anything else.
- Debug weird behavior from **language semantics first**: coercion, equality, `this`, closures, prototype chain, task queues.
- Keep one **module story** per package. Treat module mode as a package-level contract first, file-level syntax choice second.
- Prefer **native platform features** before adding dependencies.
- Test behavior at the right layer:
  - pure transforms -> unit
  - I/O boundaries -> integration
  - UI behavior -> Testing Library and user-observable queries
- Mock **external edges**, not your own core logic.
- Use the repo's existing runner. If no runner exists, choose the lowest-friction runner that matches the repo's toolchain instead of introducing a second stack.
- Do not cargo-cult coverage numbers; add tests where failure risk lives.

## Expected outputs

Match output to task size:

- small fix -> root cause + minimal patch + targeted validation
- refactor -> migration plan + coherent code changes + risk notes
- debugging -> likely cause ranking + repro/inspection steps + fix
- testing task -> runner-aware test additions with mocked external edges only
- module issue -> explicit package/module decision and any required file or `package.json` changes

## When to Use

- JS app, library, CLI, service, or automation work
- async flow design, cancellation, streams, workers
- Node.js or browser API usage
- module/package.json/interop issues
- testing strategy or flaky JS tests
- performance debugging, legacy refactors, weird runtime behavior

## When Not to Use

- `.ts` / `.tsx` type-system design is central -> also load `typescript`
- React / Next render or bundle work dominates -> also load `react-best-practices`
- Fresh external library API docs matter more than JS mechanics -> load `research`, then `context7` or `grep-app`

## Quick Start

1. Detect runtime, package manager, module mode, runner, and build tool.
2. Classify the task: semantics | async | modules/interop | runtime API | tests | perf/refactor.
3. Make the smallest coherent change for that runtime.
4. Validate with repo scripts first; use targeted checks before broad suites.
5. Read the smallest relevant file before improvising across module boundaries, async flow, or test architecture.

Defaults, validation order, and interop rules live in `reference.md`.

## Read Next

Read the smallest relevant file before implementing when the task crosses one of these boundaries:

- weird coercion / `this` / closure / prototype bugs -> `cookbook/semantics.md`
- modern syntax, transforms, iterators, immutable updates -> `cookbook/patterns.md`
- promises, cancellation, event loop, queues, async iterators -> `cookbook/async.md`
- ESM/CJS, exports, resolution, dynamic import -> `cookbook/modules.md`
- Node.js APIs, streams, workers, processes -> `cookbook/node.md`
- browser APIs, workers, storage, observers, perf APIs -> `cookbook/browser.md`
- tests, mocks, fixtures, timers, Testing Library -> `cookbook/testing.md`
- routing matrix, validation defaults, failure modes -> `reference.md`

## Assets

- `assets/vitest.config.mjs` - minimal starter Vitest config for JS repos
- `assets/jest.config.mjs` - minimal starter Jest config for JS repos

## Files

- `reference.md` - decision matrix, interop defaults, validation ladder
- `cookbook/semantics.md` - language quirks and debugging heuristics
- `cookbook/patterns.md` - ES2023+ syntax, transforms, generators, perf-friendly patterns
- `cookbook/async.md` - concurrency, event loop, cancellation, streams
- `cookbook/modules.md` - package/module structure and resolution
- `cookbook/node.md` - Node.js runtime patterns
- `cookbook/browser.md` - browser runtime patterns
- `cookbook/testing.md` - Jest/Vitest/Testing Library patterns
- `evals/evals.json` - starter eval prompts for future skill iteration

## Research tools

```bash
gh search code '"type": "module"' --language=json
gh search code 'AbortController' --language=javascript
gh search code 'defineConfig({ test:' --language=javascript
gh search code 'createRequire(import.meta.url)' --language=javascript
```
