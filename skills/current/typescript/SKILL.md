---
name: typescript
description: "Use whenever TypeScript, TS, .ts files, tsconfig, Bun, Node.js, ESM, type errors, or TS tooling are involved."
license: AGPL-3.0-or-later
metadata:
  author: anntnzrb

---

# TypeScript development

Type-safe design. Runtime-aware config. One-shot validation. Minimal config churn.

## Activation triggers

- `.ts`, `.tsx`, `.mts`, `.cts`, `tsconfig*.json`, declaration files
- Type errors, `tsc`, `tsx`, `vitest`, `jest`, `biome`, `eslint`, `@types`
- Node, Bun, Vite, Next.js, CLIs, libraries, workspaces, project references
- ESM/CJS interop, path aliases, module resolution, JS-to-TS migration

## Workflow

```text
1. DETECT    -> package manager, runtime, scripts, tsconfig
2. MODEL     -> domain types, invariants, boundaries, public API
3. ALIGN     -> module mode, imports, paths, build/test tooling
4. IMPLEMENT -> smallest safe change, one control-flow owner, narrow assertions
5. VALIDATE  -> repo scripts first, trace one path, then typecheck, test, lint, build
6. TUNE      -> profile type performance or tsconfig breadth only if still needed
```

## Core rules

- When changed TypeScript imports `effect` or `@effect/*`, loading this file alone is incomplete. If the Effect skill is not already loaded, load `../effect/SKILL.md`. Read `../effect/references/code-quality.md` before editing.
- For Effect interop, TypeScript owns host contracts, module boundaries, and Promise adapters. Effect owns lazy programs, typed failures, fibers, and resources.
- Before editing mixed control flow, classify each changed function as pure TypeScript, a framework program, or a host adapter.
- Assign sequencing, errors, cancellation, and cleanup to one owner.
- Prefer repo scripts over raw commands
- For a new user-owned backend, CLI, automation, infrastructure, service, or data-processing app with no approved alternate stack, read `references/bun-application.md` and use its Bun and native TypeScript 7+ defaults
- Respect an existing repository's package manager and runtime unless the user requests migration. Do not create a second lockfile
- Inspect the nearest working implementation before designing. Reuse an adequate existing helper, platform API, or installed dependency
- Choose `moduleResolution` from the runtime and package contract:
  - New user-owned Bun applications -> `references/bun-application.md`
  - Bundlers (`vite`, `next`, frontend apps) -> `bundler`
  - Existing Node or Bun apps and published libraries -> preserve project config. Otherwise use `NodeNext`
- Prefer `interface` for extendable object contracts
- Prefer `type` for unions, mapped types, template literal types, and helpers
- Prefer `unknown` over `any`. Validate at boundaries
- Model validity by construction. Choose the shape that cannot build the illegal value. See `cookbook/types.md`. Strengthen a type only where a `!`, cast, or throw shows that the type is too weak
- Parse external data once into domain values. Keep raw transport data, retries, logging, and process exits at I/O boundaries
- Model domain concepts separately when mixing them would be a bug. Use discriminated unions for meaningful states and exhaustively handle variants you own
- Use `satisfies`, `as const`, discriminated unions, and type-only imports when they cut noise
- Avoid repeated assertions. Fix source types, exports, and config first
- Keep one primary control-flow and error abstraction per function. Adapt between Promises, callbacks, generators, framework programs, and `Result` types once at an explicit boundary instead of interleaving them
- Do not mark a function `async` when it only constructs a lazy program or forwards an existing Promise. Do not return a Promise that contains another lazy program. If a host contract requires that shape, isolate it in an adapter
- Catch only to recover, translate once, or add actionable context. Flatten nested catch ladders. Preserve the original cause. Never silence, log and rethrow, or use exceptions as ordinary branching
- Give long-lived I/O explicit ownership, cancellation, timeout, and cleanup when the runtime or caller supports them. Do not leave Promises, tasks, subscriptions, or child processes floating
- Do not add a dependency, abstraction, parser, normalization layer, or defensive branch without a concrete caller, boundary, or failure mode
- Test observable behavior at the lowest layer that exposes the regression. Prefer real values, in-memory fakes, or wire-level fakes. Mock unavailable external edges only
- Treat a large file, parameter bundle, many negated option names, redundant post-action check, mixed control-flow models, or broad catch as a review trigger, not an automatic rewrite order
- Before handoff, trace one representative changed path from its input or event to observable output. Review each changed `async`, `await`, `try`, `catch`, Promise constructor, assertion, and resource acquisition for a single clear owner
- Compiler and linter success do not prove clean control-flow boundaries. Complete the framework-specific structural review before calling mixed-framework TypeScript idiomatic
- Use `rg` for repository discovery and `ast-grep` for structural search when it makes the question cheaper to answer
- Keep tsconfig changes narrow. Do not strictify a repo unless asked
- Use one-shot diagnostics. No watch servers for validation

## Related skills

- Pure React/Next render or bundle performance with no TS design issue: also load `react-best-practices`
- Fresh library/framework API docs: load `research`, then `context7` or `grep-app`
- Effect application architecture or APIs: also load `effect`

## Quick start

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
|Effect composition and lifecycle|`../effect/SKILL.md`, then `../effect/references/code-quality.md`|Implementing, refactoring, or reviewing TypeScript that imports Effect|
|New Bun TypeScript application policy|`references/bun-application.md`|Creating a user-owned backend, CLI, automation, infrastructure, service, or data-processing app without another approved stack|
|Config, modules, migration, monorepos|`reference.md`|Scope includes toolchain/config|
|Advanced type patterns|`cookbook/types.md`|Designing non-trivial types|
|Type/runtime tests|`cookbook/testing.md`|Adding or debugging tests|
|Stack-specific implementation references|`references/advanced/README.md`, then its matching reference|A task needs a detailed framework, strict config, boundary modeling, or bootstrap recipe. Repository policy and existing tooling take precedence|
|Code-structure or logging review|`references/advanced/engineering/code-smells.md`, `references/advanced/engineering/logging.md`|Reviewing structure or observability beyond TypeScript-specific mechanics|
|Starter compiler config|`assets/tsconfig-bundler.json`, `assets/tsconfig-nodenext.json`|Creating a new matching config|

## Research commands

```bash
gh search code "satisfies Record<string, unknown>" --language=TypeScript
gh search code "expectTypeOf<" --language=TypeScript
gh search code "\"moduleResolution\": \"NodeNext\"" --language=JSON
```
