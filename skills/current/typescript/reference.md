# TypeScript Reference

## Module mode
Select `module`/`moduleResolution` by runtime, not fashion:

|Target|`module`|`moduleResolution`|Notes|
|---|---|---|---|
|Vite / Next / frontend bundlers|`ESNext`|`bundler`|Bundler resolves aliases and extensionless imports|
|Node / Bun apps|`NodeNext`|`NodeNext`|Match runtime semantics and package exports|
|Published libraries|`NodeNext`|`NodeNext`|Keep build config separate from editor config|

Bundler-first apps → `assets/tsconfig-bundler.json`; Node/Bun projects → `assets/tsconfig-nodenext.json`. Working project: do not casually change module mode.

## Validation order
1. Existing repo scripts: `typecheck`, `test`, `lint`, `build`
2. Compiler fallback: `npx tsc --noEmit`
3. Resolution trace: `npx tsc --traceResolution`
4. Perf trace: `npx tsc --extendedDiagnostics --incremental false`

Prefer package-manager-native script execution when the repo standardizes on it.

## Strictness baseline
Useful defaults:
`strict`; `noUncheckedIndexedAccess`; `exactOptionalPropertyTypes`; `noImplicitOverride`; `noPropertyAccessFromIndexSignature`; `useUnknownInCatchVariables`; `verbatimModuleSyntax`; `isolatedModules`; `noFallthroughCasesInSwitch`; `forceConsistentCasingInFileNames`.

Usually safe for large repos: `skipLibCheck`; `incremental`. Local task: avoid broad tsconfig churn.

## Boundary and failure design
- Untrusted input: parse once at the API, file, queue, CLI, or environment boundary with the repository's existing validator; pass the parsed domain value inward; do not spread ad-hoc checks through business logic.
- Interchangeable primitives that could cause a real bug → distinct branded or opaque types. Callers needing outcome distinction → tagged union. Keep impossible states out of the representation where practical.
- Expected failure a nearby caller must handle → result union. Failure that should propagate across layers → throw an `Error` with context, with `cause` when wrapping.
- Catch only at a recovery or translation boundary; narrow errors before handling; rethrow failures the boundary does not own.
- Put timeout, cancellation, cleanup, retry policy, logging, and process exit behavior at I/O boundaries; do not hide them in pure helpers.
- Add dependencies or abstractions only for a demonstrated caller or failure mode; a local wrapper is not automatically cleaner than a direct platform API.

## Common failures
### `Cannot find module` but file exists
Check in order: (1) `moduleResolution` matches runtime; (2) `baseUrl` and `paths` match actual import style; (3) package `exports` or workspace package names are correct; (4) file extensions are correct for `NodeNext`; (5) generated `.d.ts` outputs are current.

### Path aliases compile but fail at runtime
TypeScript `paths` are compile-time only. Bundlers → configure the bundler alias too. Node/Bun apps → prefer package imports, package `imports`, or a runtime alias strategy. Published libraries → do not leak private path aliases into emitted JS or `.d.ts`.

### `Type instantiation is excessively deep`
Causes: recursive conditional types; giant unions; circular generic constraints; deeply composed mapped types. Fixes: cap recursion depth; split helper types into named aliases; prefer simpler object interfaces over giant type intersections; move impossible-to-read type gymnastics behind a tested helper.

### `The inferred type of X cannot be named`
Causes: circular type references; missing exported helper types; internal anonymous types escaping public APIs. Fixes: export the helper type explicitly; add explicit public return types; replace a leaking expression type with `ReturnType<typeof fn>` or an interface.

### ESM / CJS interop weirdness
Check `package.json` `"type"`; `module` / `moduleResolution`; default-import versus namespace-import behavior; emitted file extensions. For `NodeNext`, write imports as the runtime expects, including file extensions when required.

### Missing declarations for a dependency
Options: install matching `@types/*`; add a narrow local `*.d.ts`; wrap the dependency behind a typed adapter. Prefer the narrowest declaration that unblocks the task.

## JS to TS migration
1. Enable `allowJs`.
2. Enable `checkJs` if the repo can absorb it.
3. Type public boundaries first: API payloads, config, adapters, database edges.
4. Rename modules gradually.
5. Enable stricter flags in batches, not all at once.

Do not mass-convert the entire tree unless the task asks for it.

## Monorepos and project references
Use project references when packages compile independently and share typed outputs:
- one `tsconfig.json` per package
- keep root `references` explicit
- avoid root `include: ["**/*"]`
- sync package `exports`, `types`, and tsconfig paths
- cache `.tsbuildinfo` per package, not globally

If the monorepo already builds via a framework tool, do not introduce references just because they are theoretically cleaner.

## Lint / format choices
Use Biome when speed matters, rules are mostly style and common correctness, and the repo wants a single-tool lint + format.
Stay with ESLint when the repo already depends on type-aware rules, framework plugins matter, or custom rules or ecosystem plugins are central.

## Library packaging
Keep editor config and build config separate:
- `tsconfig.json` → `noEmit: true`, editor/typecheck
- `tsconfig.build.json` → emits JS and `.d.ts`

Public package checklist: explicit `exports`; `types` path; declaration output checked in CI; type tests for public API.
