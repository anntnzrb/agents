# Pi Extensions

## Guidelines
Prefer functional/stateless where practical.
- Favor pure data-in/data-out helpers.
- Minimize mutable module state; isolate unavoidable state in UI components/caches.
- Keep side effects at edges: I/O, UI, model calls.

## Event-loop hygiene

- **Never** use synchronous child-process APIs (`execFileSync`, `spawnSync`, `execSync`) inside async tool handlers, UI render callbacks, event listeners, or Promise constructors. They freeze the entire TUI/agent event loop.
- Use `child_process.spawn` / `execFile` with Promise wrappers or stream handlers for all subprocess work in hot paths.
- Use `node:fs/promises` in async functions; avoid `existsSync` + `readFileSync` pairs. Prefer `try { await readFile(...) } catch (ENOENT) { ... }`.
- Cold-path binary resolution (`search-binaries.ts`) may remain sync if it is cached and not invoked per tool call, but document the exception explicitly.
- When a sync interface wraps an async implementation (e.g. `refresh: () => void` calling `async` code), either: (a) swallow rejections with try/catch inside, or (b) change the interface to return `Promise<void>` and await call sites. Never discard returned Promises silently.

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

## Extension change loop

1. Load skills first:
   - `/skill:typescript` for TS/tests/schemas/tool registration/renderers/config TS.
   - `/skill:effect` for Effect imports/APIs/runtimes.
2. Read touched extension `AGENTS.md` files.
3. Map public surface: schema, promptSnippet, description, render labels, commands, events, guardrail hints, docs/tests.
4. Red when practical: add/update failing test for intended behavior/API.
5. Patch smallest coherent unit. Personal-agent policy: rewrite/renew freely; no legacy args, shims, deprecations, fallback compatibility unless user explicitly asks.
6. Green loop: format/lint/test/typecheck. Any red gate => diagnose, patch, rerun same gate class until green or hard blocker.
7. Runtime/model-facing change => scenario-specific ephemeral Pi validation before user reload.
8. Sync after green when SSOT changes must reach runtime homes.
9. Report: changed surface, gates, ephemeral Pi result, reload need.

## Ephemeral Pi validation

Goal: validate fresh extension runtime via child Pi; minimize user reloads.

Use when parent may be stale or change touches model/runtime surface: tools, schemas, prompt snippets, commands, events, guardrails, context, provider behavior, file effects.

- One-shot/default: `pi --no-extensions -e <extension.ts> --no-session --mode json -p --tools <tools> "<natural-language scenario>"`
- Multi-extension: repeat `-e <extension.ts>` for collision/interaction tests.
- JSON mode: preferred for automation; parse JSONL events, not pretty text.
- RPC mode: use only for multi-turn/client/UI protocol tests needing stdin commands or extension UI protocol.
- Parse with small Bun/TS scripts for assertions. `jq` ok for ad hoc inspection; avoid brittle grep over mixed stdout/stderr.
- Inspect relevant events:
  - tools: `tool_execution_start`, `tool_execution_end`, `message_end`
  - prompts/context: `message_*`, final assistant text, provider-facing behavior when observable
  - commands/events: messages, tool calls/results, stderr/stdout, exit code, file effects
- Write natural-language scenarios that force changed behavior through Pi. Assert exact relevant facts: tool names, args, forbidden args absent, results, errors, emitted messages, command effects, filesystem state.
- `pi ... --help` only proves startup/load. Never count it as behavior validation.
- Direct Bun import harnesses validate deterministic internals; they do not replace child Pi for model-facing behavior.
- Child Pi does not update parent session. Ask user reload/restart only for parent-runtime adoption or visual/TUI inspection.

## QA gates

Run from each touched extension dir:
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
- Keep files 500-1000 SLOC excluding comments; beyond 500L, modularize.
- If extension lacks `tsconfig.json`, add one extending `../tsconfig.base.json` with `../_shared/types/**/*.d.ts` included before strict typecheck.
- All extensions need `AGENTS.md`: description + navigation.

## Native Pi tool override philosophy

When modifying/overriding built-in Pi tools (`read`, `write`, `edit`, `grep`, `find`, etc.):
- Prefer thin wrappers and UI-only overrides over reimplementing execution.
- Minimize behavioral drift from native defaults unless explicitly required.
- Keep change-surface small, reversible, easy to diff.
- Guidance, not hard cap; break only with clear justification.
