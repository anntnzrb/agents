# Pi Extensions

## Guidelines
Prefer functional/stateless where practical.
- Favor pure data-in/data-out helpers.
- Minimize mutable module state; isolate unavoidable state in UI components/caches.
- Keep side effects at edges: I/O, UI, model calls.

## Shared utilities (reuse first)
Before helper logic, check `extensions/_shared/`:
- `tool-utils.ts`: `ensureToolActive`, `summarizeList`, `getFirstTextContent`
- `search-input.ts`: `normalizeSearchRoots`
- `line-process.ts`: line-stream subprocess runner; spawn/abort/timeout/limit/error path
- `render-utils.ts`: compact-render theme types, separators, `Text` reuse, pluralization
- `value-utils.ts`: unknown-value coercion helpers
- `text-stats.ts`: logical line counting, UTF-8 content stats
- `path-utils.ts`: POSIX normalization, compact display paths
- `types/`: ambient TS declarations for extension `tsconfig.json`

Rules:
- Do not duplicate helpers already present in `_shared`.
- If 2+ extensions need same helper, extract to `_shared` immediately.
- Keep `_shared` generic and dependency-light.
- Keep ambient declarations under `_shared/types/`; support plumbing, not extensions.

## Directory conventions

- Extension dirs use plain names: `grep/`, `find/`, `guardrails/`.
- Shared implementation/types live under `_shared/`.
- Tooling config lives under `.config/`; config-only, no importable runtime helpers.

## Modularization policy (extension-local first)

- Single-extension split: local modules first (`render.ts`, `output.ts`, `utils.ts`).
- Promote to `_shared` only with 2+ extension reuse.
- Keep `index.ts` orchestration-focused; move pure formatting/parsing/helpers out when file size drifts up.

## Skills for extension work

Load relevant skills early, before planning/editing:
- `/skill:typescript` eagerly for TypeScript extension work: `*.ts`, tests, schemas, tool registration, renderers, config-adjacent TS validation.
- `/skill:effect` eagerly when code imports/uses Effect, reviewing nearby Effect patterns, or change may affect Effect-style APIs/runtimes.
- Docs-only with no TS/Effect reasoning: skip.

## QA

Gate for extension changes (run from specific extension dir):
- `bun x biome format --write . --config-path ../.config/biome.json`
- `bun x biome lint . --config-path ../.config/biome.json --error-on-warnings`
- `bun test <targeted tests>`
- `bun x tsc -p tsconfig.json --noEmit` for touched extensions using local TS baseline

Also:
- Verify guideline criteria.
- Keep files 500-1000 SLOC excluding comments; beyond 500L, modularize.
- If extension lacks `tsconfig.json`, add one extending `../tsconfig.base.json` with `../_shared/types/**/*.d.ts` included before strict typecheck.
- All extensions need AGENTS.md: description + navigation.

NOTE: fallback to npm (`npx`) if `bun` unavailable.

## Native Pi tool override philosophy

When modifying/overriding built-in Pi tools (`read`, `write`, `edit`, `grep`, `find`, etc.):
- Prefer thin wrappers and UI-only overrides over reimplementing execution.
- Minimize behavioral drift from native defaults unless explicitly required.
- Keep change-surface small, reversible, easy to diff.
- Guidance, not hard cap; break only with clear justification.
