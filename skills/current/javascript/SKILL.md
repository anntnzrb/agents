---
name: javascript
description: "Implement and debug JavaScript in Node or browsers: modules, async, APIs, tests, and performance."
license: AGPL-3.0-or-later
metadata:
  author: anntnzrb

---

# JavaScript Development

Modern JS; runtime-aware; semantics first; no cargo-cult sludge.

## Activation Triggers

Use for `.js`, `.mjs`, `.cjs`; `package.json` when `type`, `exports`, `imports`, entrypoints, or ESM/CJS interop matter; `jest.config.*`, `vitest.config.*`, or Testing Library setup in JavaScript-first repos; `import`, `export`, `require`, `type: module`, `exports`, `imports`, or dynamic `import()`; Promises, `async`/`await`, task/microtask ordering, `AbortController`, `fetch`, streams, or workers; closures, `this`, coercion, prototypes, hoisting, TDZ, stale captures, or unexpected `undefined`; Node.js or browser behavior where JS semantics are central; JS-specific tests, mocking, fake timers, or async-test flakiness; legacy refactors where runtime behavior must remain unchanged.

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
- Inspect the nearest working implementation first; reuse an adequate helper, platform API, or installed dependency.
- Prefer **const**, local immutability, and pure transforms; mutate locally when simpler or measurably faster.
- Parse and normalize untrusted input at API, file, queue, CLI, or environment boundaries. Keep raw transport data, retries, logging, and process exits at I/O boundaries.
- Name distinct domain values clearly; represent meaningful outcomes explicitly. Do not hide state machines in truthy values or optional-field piles.
- Use `async`/`await` for orchestration and Promise combinators for concurrency. Expose **cancellation** on long-lived or user-driven work.
- Before optimizing, check independent async loops for accidental serialization.
- Debug weird behavior from language semantics first: coercion, equality, `this`, closures, prototype chain, task queues.
- Catch only to recover, translate, or add context; preserve original causes when wrapping; never silence failures.
- Keep one **module story** per package: module mode is a package-level contract before a file-level syntax choice.
- Prefer **native platform features** before dependencies.
- Add no dependency, abstraction, parser, normalization layer, or defensive branch without a concrete caller, boundary, or failure mode.
- Test at the right layer: pure transforms → unit; I/O boundaries → integration; UI behavior → Testing Library with user-observable queries.
- Mock **external edges**, not core logic. Prefer real values, in-memory fakes, or wire-level fakes when deterministic and isolated.
- Treat large files, parameter bundles, negative-name mazes, redundant post-action checks, and broad catches as review triggers, not automatic rewrites.
- Use `rg` for repository discovery and `ast-grep` for structural search when cheaper.
- Use the existing repo runner. If none exists, choose the lowest-friction runner matching the toolchain; do not introduce a second stack.
- Do not cargo-cult coverage numbers; add tests where failure risk lives.

## Expected Outputs

Match output to task size:
- small fix → root cause + minimal patch + targeted validation
- refactor → migration plan + coherent code changes + risk notes
- debugging → likely-cause ranking + repro/inspection steps + fix
- testing task → runner-aware tests with mocked external edges only
- module issue → explicit package/module decision and required file or `package.json` changes

## When to Use

- JS app, library, CLI, service, or automation
- async-flow design, cancellation, streams, or workers
- Node.js or browser APIs
- module, `package.json`, or interop issues
- testing strategy or flaky JS tests
- performance debugging, legacy refactors, or weird runtime behavior

## When Not to Use

- `.ts` / `.tsx` type-system design central → also load `typescript`
- React / Next render or bundle work dominant → also load `react-best-practices`
- Fresh external-library API docs more important than JS mechanics → load `research`, then `context7` or `grep-app`

## Quick Start

1. Detect runtime, package manager, module mode, runner, and build tool.
2. Classify: semantics, async, modules/interop, runtime API, tests, or perf/refactor.
3. Make the smallest coherent change for that runtime.
4. Validate with repo scripts first; use targeted checks before broad suites.
5. Read the smallest relevant file before improvising across module boundaries, async flow, or test architecture.

Defaults, validation order, and interop rules live in `reference.md`.

## Required Follow-up Reads

|Need|Read|When|
|---|---|---|
|Coercion, `this`, closures, prototypes|`cookbook/semantics.md`|Debugging language-semantics failures|
|Syntax, transforms, iterators, immutable updates|`cookbook/patterns.md`|Selecting implementation patterns|
|Promises, cancellation, queues, async iterators|`cookbook/async.md`|Designing or debugging async flow|
|ESM/CJS, exports, resolution, dynamic imports|`cookbook/modules.md`|Crossing module boundaries|
|Node.js APIs, streams, workers, processes|`cookbook/node.md`|Node runtime behavior matters|
|Browser APIs, workers, storage, observers|`cookbook/browser.md`|Browser runtime behavior matters|
|Tests, mocks, fixtures, timers, Testing Library|`cookbook/testing.md`|Testing behavior or flakiness|
|Routing, validation defaults, failure modes|`reference.md`|Before implementation when route is unclear|

## Assets

- `assets/vitest.config.mjs` - minimal starter Vitest config for JS repos
- `assets/jest.config.mjs` - minimal starter Jest config for JS repos

## Research Tools

```bash
gh search code '"type": "module"' --language=json
gh search code 'AbortController' --language=javascript
gh search code 'defineConfig({ test:' --language=javascript
gh search code 'createRequire(import.meta.url)' --language=javascript
```
