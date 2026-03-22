# TypeScript Reference

## Runtime Mode Selection

Pick module mode from runtime, not fashion:

| Target | `module` | `moduleResolution` | Notes |
|---|---|---|---|
| Vite / Next / frontend bundlers | `ESNext` | `bundler` | Bundler resolves aliases and extensionless imports |
| Node / Bun apps | `NodeNext` | `NodeNext` | Match runtime semantics and package exports |
| Published libraries | `NodeNext` | `NodeNext` | Keep build config separate from editor config |

Use `assets/tsconfig-bundler.json` for bundler-first apps.
Use `assets/tsconfig-nodenext.json` for Node/Bun projects.

If a project already works, do not flip module mode casually.

## Validation Order

1. Existing repo scripts: `typecheck`, `test`, `lint`, `build`
2. Compiler fallback: `npx tsc --noEmit`
3. Resolution trace: `npx tsc --traceResolution`
4. Perf trace: `npx tsc --extendedDiagnostics --incremental false`

Prefer package-manager-native script execution when the repo already standardizes on it.

## Strictness Baseline

Useful defaults:

- `strict`
- `noUncheckedIndexedAccess`
- `exactOptionalPropertyTypes`
- `noImplicitOverride`
- `noPropertyAccessFromIndexSignature`
- `useUnknownInCatchVariables`
- `verbatimModuleSyntax`
- `isolatedModules`

Usually safe for large repos:

- `skipLibCheck`
- `incremental`

Avoid broad tsconfig churn when the task is local.

## Common Failure Patterns

### "Cannot find module" but file exists

Check, in order:

1. `moduleResolution` matches runtime
2. `baseUrl` and `paths` match actual import style
3. package `exports` or workspace package names are correct
4. file extensions are correct for `NodeNext`
5. generated `.d.ts` outputs are current

### Path aliases compile but fail at runtime

TypeScript `paths` are compile-time only.

- Bundlers: configure the bundler alias too
- Node/Bun apps: prefer package imports, package `imports`, or a runtime alias strategy
- Published libraries: do not leak private path aliases into emitted JS or `.d.ts`

### "Type instantiation is excessively deep"

Common causes:

- recursive conditional types
- giant unions
- circular generic constraints
- deeply composed mapped types

Usual fixes:

- cap recursion depth
- split helper types into named aliases
- prefer simpler object interfaces over giant type intersections
- move impossible-to-read type gymnastics behind a tested helper

### "The inferred type of X cannot be named"

Usually caused by:

- circular type references
- missing exported helper types
- internal anonymous types escaping public APIs

Fixes:

- export the helper type explicitly
- add explicit public return types
- replace a leaking expression type with `ReturnType<typeof fn>` or an interface

### ESM / CJS interop weirdness

Check:

- `package.json` `"type"`
- `module` / `moduleResolution`
- default import vs namespace import behavior
- emitted file extensions

For `NodeNext`, write imports the way the runtime expects them, including file extensions when required.

### Missing declarations for a dependency

Options:

1. install matching `@types/*`
2. add a narrow local `*.d.ts`
3. wrap the dependency behind a typed adapter

Prefer the narrowest declaration that unblocks the task.

## JS to TS Migration

Good migration order:

1. Enable `allowJs`
2. Enable `checkJs` if the repo can absorb it
3. Type public boundaries first: API payloads, config, adapters, database edges
4. Rename modules gradually
5. Turn on stricter flags in batches, not all at once

Do not mass-convert the entire tree unless the task asks for it.

## Monorepos and Project References

Use project references when packages compile independently and share typed outputs.

Rules:

- one `tsconfig.json` per package
- keep root `references` explicit
- avoid root `include: ["**/*"]`
- sync package `exports`, `types`, and tsconfig paths
- cache `.tsbuildinfo` per package, not globally

If the monorepo already builds via a framework tool, do not introduce references just because they are theoretically cleaner.

## Lint / Format Choices

Use Biome when:

- speed matters
- rules are mostly style and common correctness
- repo wants single-tool lint + format

Stay with ESLint when:

- repo already depends on type-aware rules
- framework plugins matter
- custom rules or ecosystem plugins are central

## Library Packaging

For libraries, keep editor config and build config separate.

Typical split:

- `tsconfig.json` -> `noEmit: true`, editor/typecheck
- `tsconfig.build.json` -> emits JS and `.d.ts`

Public package checklist:

- explicit `exports`
- `types` path
- declaration output checked in CI
- type tests for public API
