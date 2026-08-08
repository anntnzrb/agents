---
name: javascript
description: "Implement and debug JavaScript in Node or browsers: modules, async, APIs, tests, and performance."
license: GPL-3.0-or-later
metadata:
  author: anntnzrb

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
- Inspect the nearest working implementation before designing; reuse an adequate existing helper, platform API, or installed dependency.
- Prefer **const**, local immutability, and pure transforms by default. Mutate locally when it is simpler or measurably faster.
- Parse and normalize untrusted input at the API, file, queue, CLI, or environment boundary. Keep raw transport data, retries, logging, and process exits at I/O boundaries.
- Give distinct domain values clear names and represent meaningful outcomes explicitly. Do not hide a state machine in truthy values or a pile of optional fields.
- Use `async` / `await` for orchestration. Use Promise combinators for concurrency. Expose **cancellation** on long-lived or user-driven work.
- For independent async work, check for accidental serialization in loops before optimizing anything else.
- Debug weird behavior from **language semantics first**: coercion, equality, `this`, closures, prototype chain, task queues.
- Catch only to recover, translate, or add context; preserve the original cause when wrapping and never silence a failure.
- Keep one **module story** per package. Treat module mode as a package-level contract first, file-level syntax choice second.
- Prefer **native platform features** before adding dependencies.
- Do not add a dependency, abstraction, parser, normalization layer, or defensive branch without a concrete caller, boundary, or failure mode.
- Test behavior at the right layer:
  - pure transforms -> unit
  - I/O boundaries -> integration
  - UI behavior -> Testing Library and user-observable queries
- Mock **external edges**, not your own core logic.
- Prefer real values, in-memory fakes, or wire-level fakes before mocks when they keep the test deterministic and isolated.
- Treat a large file, parameter bundle, negative-name maze, redundant post-action check, or broad catch as a review trigger—not an automatic rewrite order.
- Use `rg` for repository discovery and `ast-grep` for structural search when it makes the question cheaper to answer.
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

## Required follow-up reads

| Need | Read | When |
| --- | --- | --- |
| Coercion, `this`, closures, prototypes | `cookbook/semantics.md` | Debugging language-semantics failures |
| Syntax, transforms, iterators, immutable updates | `cookbook/patterns.md` | Selecting implementation patterns |
| Promises, cancellation, queues, async iterators | `cookbook/async.md` | Designing or debugging async flow |
| ESM/CJS, exports, resolution, dynamic imports | `cookbook/modules.md` | Crossing module boundaries |
| Node.js APIs, streams, workers, processes | `cookbook/node.md` | Node runtime behavior matters |
| Browser APIs, workers, storage, observers | `cookbook/browser.md` | Browser runtime behavior matters |
| Tests, mocks, fixtures, timers, Testing Library | `cookbook/testing.md` | Testing behavior or flakiness |
| Routing, validation defaults, failure modes | `reference.md` | Before implementation when route is unclear |

## Assets

- `assets/vitest.config.mjs` - minimal starter Vitest config for JS repos
- `assets/jest.config.mjs` - minimal starter Jest config for JS repos

## Research tools

```bash
gh search code '"type": "module"' --language=json
gh search code 'AbortController' --language=javascript
gh search code 'defineConfig({ test:' --language=javascript
gh search code 'createRequire(import.meta.url)' --language=javascript
```
