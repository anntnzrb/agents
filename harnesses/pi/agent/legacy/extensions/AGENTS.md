# Pi Extensions

<critical>
- In async tool handlers, UI render callbacks, event listeners, and Promise constructors, NEVER use synchronous child-process APIs: `execFileSync`, `spawnSync`, or `execSync`. They freeze the TUI/agent event loop.
- Use `child_process.spawn` / `execFile` with Promise wrappers or stream handlers for subprocess work in hot paths.
- Use `node:fs/promises` in async functions; AVOID `existsSync` + `readFileSync` pairs. Prefer `try { await readFile(...) } catch (ENOENT) { ... }`.
- Cold-path binary resolution (`search-binaries.ts`) MAY remain sync only when cached, not invoked per tool call, and documented as an explicit exception.
- When a sync interface wraps async work, e.g. `refresh: () => void` calling `async` code, handle rejection with `try/catch` inside or change the interface to `Promise<void>` and await call sites. NEVER discard returned Promises silently.
</critical>

## Engineering Principles

- Prefer functional/stateless design where practical.
- Favor pure data-in/data-out helpers.
- Minimize mutable module state; isolate unavoidable state in UI components or caches.
- Keep side effects at the edges: I/O, UI, and model calls.

## Shared Utilities

Before adding helper logic, check `extensions/_shared/`:

- `tool-utils.ts`: `ensureToolActive`, `summarizeList`, `getFirstTextContent`.
- `search-input.ts`: `normalizeSearchRoots`.
- `line-process.ts`: line-stream subprocess runner; spawn/abort/timeout/limit/error path.
- `render-utils.ts`: compact-render theme types, separators, `Text` reuse, pluralization.
- `value-utils.ts`: unknown-value coercion helpers.
- `text-stats.ts`: logical line counting, UTF-8 content stats.
- `path-utils.ts`: POSIX normalization, compact display paths.
- `types/`: ambient TS declarations for extension `tsconfig.json`.

Rules:

- Reuse `_shared` helpers when they already cover the need.
- Extract to `_shared` when 2+ extensions need the same stable, non-trivial helper.
- Keep `_shared` generic and dependency-light.
- Keep ambient declarations under `_shared/types/`; support plumbing, not extensions.

## Directory Conventions

- Extension dirs use plain names: `grep/`, `find/`, `guardrails/`.
- Shared implementation/types live under `_shared/`.
- Tooling config lives under `.config/`; config-only, no importable runtime helpers.
- Every extension directory needs `AGENTS.md` with description + navigation.

## Modularization Policy

- Single-extension split: local modules first (`render.ts`, `output.ts`, `utils.ts`).
- Promote to `_shared` only with 2+ extension reuse.
- Keep `index.ts` orchestration-focused; move pure formatting/parsing/helpers out when file size drifts up.
- Keep files 500-1000 SLOC excluding comments; beyond 500L, modularize.
- If extension lacks `tsconfig.json`, add one extending `../tsconfig.base.json` with `../_shared/types/**/*.d.ts` included before strict typecheck.

<workflow>
Default loop for behavior or runtime-facing changes:

1. Load the relevant skill when work touches TS/tests/schemas/tool registration/renderers/config TS (`/skill:typescript`) or Effect imports/APIs/runtimes (`/skill:effect`).
2. Read touched extension `AGENTS.md` files.
3. Map public surface: schema, promptSnippet, description, render labels, commands, events, guardrail hints, docs/tests.
4. Red when practical: add/update failing test for intended behavior/API.
5. Patch the smallest coherent unit. Personal-agent policy permits rewrite/renew when requested by the task; AVOID legacy args, shims, deprecations, or fallback compatibility unless the user asks.
6. Green loop: format/lint/test/typecheck. Any red gate => diagnose, patch, rerun same gate class until green or hard blocker.
7. Runtime/model-facing change => scenario-specific ephemeral Pi validation before user reload.
8. Sync after green when SSOT changes must reach runtime homes.
9. Report changed surface, gates, ephemeral Pi result, and reload need.
   </workflow>

Stop/skip rules:

- Docs-only edits: skip runtime validation unless public invocation or model-facing instructions changed.
- Pure internal helper/test edits: run targeted unit/type gates; child Pi is OPTIONAL unless behavior crosses tool/schema/runtime boundaries.
- Read-only analysis: NEVER mutate or validate beyond inspection.

## Ephemeral Pi Validation

Goal: validate fresh extension runtime via child Pi and minimize user reloads.

Use when parent may be stale or change touches model/runtime surface: tools, schemas, prompt snippets, commands, events, guardrails, context, provider behavior, file effects.

- One-shot/default: `pi --no-extensions -e <extension.ts> --no-session --mode json -p --tools <tools> "<scenario>"`
- Multi-extension: repeat `-e <extension.ts>` for collision/interaction tests.
- JSON mode: preferred for automation; parse JSONL events, not pretty text.
- RPC mode: use only for multi-turn/client/UI protocol tests needing stdin commands or extension UI protocol.
- Parse with small Bun/TS scripts for assertions. `jq` MAY be used for ad hoc inspection; AVOID brittle grep over mixed stdout/stderr.
- Inspect relevant events:
  - tools: `tool_execution_start`, `tool_execution_end`, `message_end`
  - prompts/context: `message_*`, final assistant text, provider-facing behavior when observable
  - commands/events: messages, tool calls/results, stderr/stdout, exit code, file effects
- Write natural-language scenarios that force changed behavior through Pi. Assert exact relevant facts: tool names, args, forbidden args absent, results, errors, emitted messages, command effects, filesystem state.
- `pi ... --help` proves startup/load only; it is not behavior validation.
- Direct Bun import harnesses validate deterministic internals; they NEVER replace child Pi for model-facing behavior.
- Child Pi does not update parent session. Ask user reload/restart only for parent-runtime adoption or visual/TUI inspection.

## QA Gates

Run the narrowest meaningful gate for the touched surface.

From each touched extension dir when code changes:

- `bun x biome format --write . --config-path ../.config/biome.json`
- `bun x biome lint . --config-path ../.config/biome.json --error-on-warnings`
- `bun test <targeted tests>`
- `bun x tsc -p tsconfig.json --noEmit` when `tsconfig.json` exists or TS touched.

Cross-extension changes:

- Run targeted gates for every touched extension.
- Run combined tests for coupled surfaces (`find+grep+guardrails`, render+logic, etc.).
- Run scenario-specific child Pi validation when public/runtime behavior changes.
- Run direct Bun harness or child Pi with all changed extensions loaded together when schemas/tools/events can collide.

Other requirements:

- Verify guideline criteria.
- Every extension directory needs `AGENTS.md`: description + navigation.

## Native Pi Tool Override Philosophy

When modifying/overriding built-in Pi tools (`read`, `write`, `edit`, `grep`, `find`, etc.):

- Prefer thin wrappers and UI-only overrides over reimplementing execution.
- Minimize behavioral drift from native defaults unless explicitly required.
- Keep change-surface small, reversible, and easy to diff.
- This is guidance, not a hard cap; break only with clear justification.

<critical>
- NEVER use `execFileSync`, `spawnSync`, or `execSync` in async handlers, UI callbacks, event listeners, or Promise constructors.
- NEVER silently discard Promises from sync-to-async wrappers; use `try/catch` or change the interface to `Promise<void>`.
- Preserve exact QA command syntax, especially `--config-path ../.config/biome.json`.
- Preserve the child Pi validation shape: `pi --no-extensions -e <extension.ts> --no-session --mode json -p --tools <tools> "<scenario>"`.
</critical>
