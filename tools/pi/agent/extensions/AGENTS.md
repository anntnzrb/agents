# Pi Extensions

## Guidelines
Prefer functional over imperative, and stateless over stateful where practical.
- Favor pure helpers and data-in/data-out flows.
- Minimize mutable module state; isolate unavoidable state in small scopes (UI components, caches).
- Keep side effects at the edges (I/O, UI, model calls).

## Shared utilities (reuse first)
Before adding helper logic, check and reuse `extensions/_shared/`:
- `tool-utils.ts`: `ensureToolActive`, `summarizeList`, `getFirstTextContent`
- `search-input.ts`: `normalizeSearchRoots`
- `line-process.ts`: shared line-stream subprocess runner (spawn/abort/timeout/limit/error path)
- `render-utils.ts`: compact-render theme types, separators, `Text` reuse, pluralization
- `value-utils.ts`: small unknown-value coercion helpers
- `text-stats.ts`: logical line counting and UTF-8 content stats
- `path-utils.ts`: POSIX path normalization and compact display paths
- `types/`: ambient TypeScript declarations used by extension `tsconfig.json` files

Rules:
- Do not duplicate helpers already present in `_shared`.
- If two extensions need the same helper, extract to `_shared` immediately.
- Keep `_shared` generic and dependency-light.
- Keep ambient declaration files under `_shared/types/`; they are support plumbing, not extensions.

## Directory conventions

- Extension directories are plain names (`grep/`, `find/`, `guardrails/`).
- Shared implementation/type support lives under `_shared/`.
- Tooling config lives under `.config/` and should stay config-only; do not put importable runtime helpers there.

## Modularization policy (extension-local first)

- For single-extension splits, extract into local modules first (e.g. `render.ts`, `output.ts`, `utils.ts`).
- Promote to `_shared` only when reused across 2+ extensions.
- Keep `index.ts` orchestration-focused; move pure formatting/parsing/helpers out when file size drifts up.

## Skills for extension work

Load relevant skills early, before planning or editing:
- Load `/skill:typescript` eagerly for any TypeScript extension work (`*.ts`, tests, schemas, tool registration, renderers, config-adjacent TS validation).
- Load `/skill:effect` eagerly when code imports/uses Effect, when reviewing nearby Effect patterns, or when an extension change could affect Effect-style APIs/runtimes.
- If work is docs-only and does not require TS/Effect reasoning, skip them.

## QA

Gate for extension changes (run from the specific extension dir):
- `bun x biome format --write . --config-path ../.config/biome.json`
- `bun x biome lint . --config-path ../.config/biome.json --error-on-warnings`
- `bun test <targeted tests>`
- `bun x tsc -p tsconfig.json --noEmit` (for touched extensions using the local TS baseline)

Also:
- Verify guideline criteria are met.
- Keep files between 500-1000 SLOC (excluding comments). Beyond 500L, modularize.
- If an extension lacks `tsconfig.json`, add one extending `../tsconfig.base.json` with `../_shared/types/**/*.d.ts` included before running strict typecheck.
- All extensions must include AGENTS.md with description + navigation.

NOTE: Fallback to npm (`npx`) if `bun` is unavailable.

## Native Pi tool override philosophy

When modifying or overriding built-in Pi tools (`read`, `write`, `edit`, `grep`, `find`, etc.), use a conservative approach:
- Prefer thin wrappers and UI-only overrides over reimplementing tool execution.
- Minimize behavioral drift from native defaults unless explicitly required.
- Keep change-surface small, reversible, and easy to diff.
- Treat this as guidance, not a hard cap; break it only with clear justification.
