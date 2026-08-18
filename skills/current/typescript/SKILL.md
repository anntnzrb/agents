---
name: typescript
description: "Use whenever TypeScript, TS, .ts files, tsconfig, Bun, Node.js, ESM, type errors, or TS tooling are involved."
license: AGPL-3.0-or-later
metadata:
  author: anntnzrb

---

# TypeScript Development

Type-safe design. Runtime-aware config. One-shot validation. Minimal config churn.

## Activation Triggers

- `.ts`, `.tsx`, `.mts`, `.cts`, `tsconfig*.json`, declaration files
- Type errors, `tsc`, `tsx`, `vitest`, `jest`, `biome`, `eslint`, `@types`
- Node, Bun, Vite, Next.js, CLIs, libraries, workspaces, project references
- ESM/CJS interop, path aliases, module resolution, JS-to-TS migration

## Workflow

```text
1. DETECT    -> package manager, runtime, scripts, tsconfig
2. MODEL     -> domain types, invariants, boundaries, public API surface
3. ALIGN     -> module mode, imports, paths, build/test tooling
4. IMPLEMENT -> smallest safe change; one control-flow owner; narrow assertions
5. VALIDATE  -> repo scripts first; trace one path; then typecheck, test, lint, build
6. TUNE      -> profile type performance or tsconfig breadth only if still needed
```

## Core Rules

- Prefer repo scripts over raw commands
- For a new user-owned backend, CLI, automation, infrastructure, service, or data-processing app with no approved alternate stack, read `references/bun-application.md` and use its Bun and native TypeScript 7+ defaults
- Respect an existing repository's package manager and runtime unless the user requests migration; do not create a second lockfile
- Inspect the nearest working implementation before designing; reuse an adequate existing helper, platform API, or installed dependency
- Choose `moduleResolution` from the runtime and package contract:
  - New user-owned Bun applications -> `references/bun-application.md`
  - Bundlers (`vite`, `next`, frontend apps) -> `bundler`
  - Existing Node or Bun apps and published libraries -> preserve project config; otherwise use `NodeNext`
- Prefer `interface` for extendable object contracts
- Prefer `type` for unions, mapped types, template literal types, and helpers
- Prefer `unknown` over `any`; validate at boundaries
- Model validity by construction: choose the shape that cannot build the illegal value (see `cookbook/types.md`); strengthen a type only where a `!`, cast, or throw shows it is too weak
- Parse external data once into domain values. Keep raw transport data, retries, logging, and process exits at I/O boundaries
- Model domain concepts separately when mixing them would be a bug. Use discriminated unions for meaningful states and exhaustively handle variants you own
- Use `satisfies`, `as const`, discriminated unions, and type-only imports when they cut noise
- Avoid assertion piles. Fix source types, exports, config first
- Keep one primary control-flow and error abstraction per function. Adapt between Promises, callbacks, generators, framework programs, and `Result` types once at an explicit boundary instead of interleaving them
- Do not mark a function `async` when it only constructs or returns a lazy program. Do not accidentally return a Promise that contains another lazy program; if a host contract requires that shape, isolate it in an adapter
- Catch only to recover, translate once, or add actionable context. Flatten nested catch ladders; preserve the original cause; never silence, log-and-rethrow, or use exceptions as ordinary branching
- Give long-lived I/O explicit ownership, cancellation, timeout, and cleanup when the runtime or caller supports them. Do not leave Promises, tasks, subscriptions, or child processes floating
- Do not add a dependency, abstraction, parser, normalization layer, or defensive branch without a concrete caller, boundary, or failure mode
- Test observable behavior at the lowest layer that exposes the regression. Prefer real values, in-memory fakes, or wire-level fakes; mock unavailable external edges only
- Treat a large file, parameter bundle, negative-name maze, redundant post-action check, mixed control-flow models, or broad catch as a review trigger, not an automatic rewrite order
- Before handoff, trace one representative changed path from its input or event to observable output; review each changed `async`, `await`, `try`, `catch`, Promise constructor, assertion, and resource acquisition for a single clear owner
- Use `rg` for repository discovery and `ast-grep` for structural search when it makes the question cheaper to answer
- Keep tsconfig changes narrow. Do not strictify a repo unless asked
- Use one-shot diagnostics. No watch servers for validation

## When to Use

- App or library work in TypeScript
- tsconfig, declarations, module resolution, path mapping
- Generics, utility types, branded domain types, public API hardening
- JS-to-TS migration, monorepos, project references, slow type-checking
- Type-safe testing, build/test/lint integration

## When Not to Use

- Pure React/Next render or bundle performance with no TS design issue: also load `react-best-practices`
- Fresh library/framework API docs: load `research`, then `context7` or `grep-app`
- Effect application architecture or APIs: also load `effect`

## Quick Start

### Detect the toolchain

```bash
if [ -f bun.lockb ] || [ -f bun.lock ]; then PM=bun;
elif [ -f pnpm-lock.yaml ]; then PM=pnpm;
elif [ -f yarn.lock ]; then PM=yarn;
elif [ -f package-lock.json ]; then PM=npm;
else PM=unset; fi
echo "$PM"
```

### Validation ladder

- Run repo scripts first: `typecheck`, `test`, `lint`, `build`
- Bun fallback: `bunx tsc --noEmit`
- Bun performance trace: `bunx tsc --extendedDiagnostics --incremental false`
- Bun resolution trace: `bunx tsc --traceResolution`
- In an existing non-Bun repository, use its package-manager-native equivalent without changing the lockfile

## Required follow-up reads

|Need|Read|When|
|---|---|---|
|New Bun TypeScript application policy|`references/bun-application.md`|Creating a user-owned backend, CLI, automation, infrastructure, service, or data-processing app without another approved stack|
|Config, modules, migration, monorepos|`reference.md`|Scope includes toolchain/config|
|Advanced type patterns|`cookbook/types.md`|Designing non-trivial types|
|Type/runtime tests|`cookbook/testing.md`|Adding or debugging tests|
|Opinionated stack recipes and deep implementation patterns|`references/advanced/README.md`, then its matching reference|A task needs a detailed framework, strict-config, boundary-modeling, or bootstrap recipe; repository policy and existing tooling take precedence|
|Cross-language code-smell or logging review|`references/advanced/engineering/code-smells.md`, `references/advanced/engineering/logging.md`|Reviewing structure or observability beyond TypeScript-specific mechanics|
|Starter compiler config|`assets/tsconfig-bundler.json`, `assets/tsconfig-nodenext.json`|Creating a new matching config|

## Research Tools

```bash
gh search code "satisfies Record<string, unknown>" --language=TypeScript
gh search code "expectTypeOf<" --language=TypeScript
gh search code "\"moduleResolution\": \"NodeNext\"" --language=JSON
```
