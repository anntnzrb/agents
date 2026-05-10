---
name: typescript
description: Develop TypeScript apps with TS 5.x patterns, repo-aware workflows, and production-first type safety. Use for .ts/.tsx/.mts/.cts, tsconfig.json, declaration files, package scripts, Node/Bun/Vite/Vitest/Jest toolchains, ESM/CJS issues, monorepos, JS-to-TS migration, type errors, or slow type-checks. Prefer repo scripts and the existing package manager. Pair with react-best-practices when React/Next render or bundle performance is central.
license: GPL-3.0-or-later
metadata:
  author: anntnzrb
allowed-tools: ""
disable-model-invocation: true
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
4. IMPLEMENT -> smallest safe change; unknown over any; narrow assertions
5. VALIDATE  -> repo scripts first; then typecheck, test, lint, build
6. TUNE      -> profile type performance or tsconfig breadth only if still needed
```

## Core Rules

- Prefer repo scripts over raw commands.
- Respect existing package manager: `bun`, `pnpm`, `yarn`, `npm`.
- Choose `moduleResolution` from runtime:
  - Bundlers (`vite`, `next`, frontend apps) -> `bundler`
  - Node or Bun apps/libraries -> `NodeNext`
- Prefer `interface` for extendable object contracts.
- Prefer `type` for unions, mapped types, template literal types, and helpers.
- Prefer `unknown` over `any`; validate at boundaries.
- Use `satisfies`, `as const`, discriminated unions, and type-only imports when they cut noise.
- Avoid assertion piles. Fix source types, exports, config first.
- Keep tsconfig changes narrow. Do not strictify a repo unless asked.
- Use one-shot diagnostics. No watch servers for validation.

## When to Use

- App or library work in TypeScript
- tsconfig, declarations, module resolution, path mapping
- Generics, utility types, branded domain types, public API hardening
- JS-to-TS migration, monorepos, project references, slow type-checking
- Type-safe testing, build/test/lint integration

## When Not to Use

- Pure React/Next render or bundle performance with no TS design issue: also load `react-best-practices`
- Fresh library/framework API docs: load `research`, then `context7` or `grep-app`

## Quick Start

### Detect the toolchain

```bash
if [ -f bun.lockb ] || [ -f bun.lock ]; then PM=bun;
elif [ -f pnpm-lock.yaml ]; then PM=pnpm;
elif [ -f yarn.lock ]; then PM=yarn;
else PM=npm; fi
echo "$PM"
```

### Validation ladder

- Run repo scripts first: `typecheck`, `test`, `lint`, `build`
- Fallback typecheck: `npx tsc --noEmit`
- Perf trace: `npx tsc --extendedDiagnostics --incremental false`
- Resolution trace: `npx tsc --traceResolution`

## Notes

Read when scope narrows:

- config, module mode, migration, monorepos -> `reference.md`
- advanced types, unions, branded types, helper patterns -> `cookbook/types.md`
- type tests, `@ts-expect-error`, Vitest, tsd -> `cookbook/testing.md`
- starter configs -> `assets/tsconfig-bundler.json`, `assets/tsconfig-nodenext.json`

## Research Tools

```bash
gh search code "satisfies Record<string, unknown>" --language=TypeScript
gh search code "expectTypeOf<" --language=TypeScript
gh search code "\"moduleResolution\": \"NodeNext\"" --language=JSON
```

## Files

- `reference.md` - runtime-mode choice, error patterns, migration, monorepos
- `cookbook/types.md` - high-signal type patterns
- `cookbook/testing.md` - compile-time and runtime test patterns
- `assets/tsconfig-bundler.json` - strict bundler-first app baseline
- `assets/tsconfig-nodenext.json` - strict Node/Bun baseline
