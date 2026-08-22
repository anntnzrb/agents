# Bun TypeScript application policy

Read this reference when creating a user-owned TypeScript backend, CLI, automation, infrastructure tool, service, or data-processing application without a different approved stack. Existing repositories keep their established runtime and package manager unless the user requests a migration.

## Default product scope

Own design, implementation, tests, debugging, maintenance, and documentation. Ask only for product decisions, credentials, or choices that materially change correctness, safety, cost, or scope.

Build backend, CLI, automation, infrastructure, service, and data-processing software. Do not add browser code, React, JSX, frontend frameworks, or UI behavior unless the user requests them.

Use the smallest architecture and dependency set that satisfies the current requirements. Do not install every tool or library in this reference automatically.

## Runtime and package manager

Use Bun only for JavaScript and TypeScript execution, package management, project scripts, development servers, tests, and bundling when bundling is necessary:

```text
bun install
bun add
bun remove
bun run
bun test
bun build
bunx
```

Do not invoke npm, pnpm, Yarn, Node.js, Deno, `ts-node`, `tsx`, or `nodemon` without explicit approval. Do not silently replace Bun because an example or dependency assumes Node.js.

Use native ESM, modern imports, and `"type": "module"`. Do not use CommonJS or `require`.

When developing a self-contained CLI tool, skill, or service in a nested directory, initialize the directory as its own package (`bun init` or local `package.json`) with its own pinned dependencies. Never reach across unrelated repository or directory boundaries with upward-traversing `tsconfig.json` path hacks.

Use package-level subpath imports (`#*` in `package.json` and matching `paths` in `tsconfig.json`) to organize internal modules across directories without relative `../` traversal ladders:

```json
{
  "imports": {
    "#models": "./lib/models.ts",
    "#config": "./lib/config.ts"
  }
}
```

Before adopting a dependency, inspect its exports and runtime assumptions. Verify Bun compatibility when the package is Node-specific or compatibility is uncertain. Explain the tradeoff before adding an incompatible or uncertain dependency.
## TypeScript compiler

Use the native Go-based `typescript` package at version 7 or newer. Install the requested current version, then verify the installed version instead of trusting a dist-tag:

```text
bun add --dev typescript@latest @types/bun
bunx tsc --version
```

Do not silently downgrade TypeScript to make the project compile. If TypeScript 7 is unavailable or incompatible with another required tool, report the exact versions and ask for the compatibility decision.

Use this baseline `tsconfig.json` for new Bun applications unless a concrete runtime or package constraint requires a documented change:

```json
{
  "compilerOptions": {
    "lib": ["ESNext"],
    "target": "ESNext",
    "module": "Preserve",
    "moduleResolution": "bundler",
    "moduleDetection": "force",
    "allowImportingTsExtensions": true,
    "verbatimModuleSyntax": true,
    "noEmit": true,
    "strict": true,
    "skipLibCheck": true,
    "noFallthroughCasesInSwitch": true,
    "noUncheckedIndexedAccess": true,
    "noImplicitOverride": true,
    "types": ["bun"]
  }
}
```

Bun transpiles TypeScript but does not type-check it. Run explicit compiler diagnostics.

Prefer `unknown` over `any`. Decode untrusted input once at its boundary. Model meaningful states with discriminated unions and exhaustively handle variants that the application owns. Use assertions only after code establishes the invariant.

## Lint, format, and tests

Use Oxlint for general JavaScript and TypeScript linting. Use Oxfmt for formatting. Do not silently substitute ESLint, Prettier, or Biome.

```text
bun add --dev oxlint oxfmt
bunx oxlint .
bunx oxfmt .
bunx oxfmt --check .
```

Use Bun's built-in `bun:test`. Do not add Vitest, Jest, or another test runner by default.

Recommended scripts for a new application are:

```json
{
  "scripts": {
    "dev": "bun run src/main.ts",
    "test": "bun test",
    "typecheck": "bunx tsc --project tsconfig.json --noEmit",
    "lint": "oxlint .",
    "format": "oxfmt .",
    "format:check": "oxfmt --check ."
  }
}
```

Test pure domain logic, successful boundary execution, expected failures, resource cleanup, configuration, and relevant concurrency. Prefer real values, in-memory fakes, and dependency replacement over global module mocking.

## Dependency discipline

Prefer Bun and Web platform APIs before dependencies. Add a package only for a current caller, boundary, or failure mode. Do not introduce frameworks, databases, ORMs, validation libraries, utility libraries, or infrastructure for hypothetical future requirements.

Do not add Zod, Valibot, fp-ts, neverthrow, or RxJS by default. Keep small validation local. If validation needs a framework, load the Effect skill and use its `Schema` policy instead of adding a competing library.

## Workflow

Before coding:

1. Define the requested outcome and observable acceptance criteria.
2. Inspect the repository runtime, package manager, scripts, compiler config, lockfile, and nearest working implementation.
3. Identify only decisions that materially affect the result.
4. State the smallest architecture and dependency set for non-trivial work.
5. Add or update a failing test first when the behavior has a cheap local test path.

While coding:

1. Keep pure domain logic separate from I/O and runtime adapters.
2. Preserve existing user changes and avoid unrelated files.
3. Keep long-lived I/O cancellable and resource cleanup explicit.
4. Do not invent compatibility layers, fallbacks, or abstractions without a current need.
5. Update existing documentation when public commands, configuration, or behavior changes.

After coding, run the applicable repository scripts. For a new application, the expected gate is:

```text
bun install
bun run typecheck
bun run lint
bun run format:check
bun test
```

Run the relevant application command with Bun when possible. Run `git diff --check`. Fix failures introduced by the change and rerun the failed gate.

Report the implementation, changed files, dependency changes, commands, validation results, assumptions, and remaining risks or decisions.

## Authoritative sources

Use installed package exports and declarations before model memory. Use current official sources for unresolved runtime and toolchain behavior:

- <https://bun.sh/docs>
- <https://www.typescriptlang.org/docs/>
- <https://oxc.rs/docs/guide/usage/linter>
- <https://oxc.rs/docs/guide/usage/formatter>
