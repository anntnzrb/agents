# OMP Extensions

## Engineering Principles

Prefer functional/stateless design where practical.
- Favor pure data-in/data-out helpers.
- Minimize mutable module state.
- Keep side effects at edges: I/O, UI, model calls.

## Event-loop Hygiene

- In async handlers and event listeners, avoid synchronous child-process APIs; they freeze the TUI/agent event loop.
- Use `node:fs/promises` for directory operations in async functions.
- Use Bun file APIs for simple file reads/writes when they fit.
- Avoid `existsSync` + read pairs; prefer try/catch around the operation.

## Directory Conventions

- Extension dirs use plain names: `hide-disabled-skills/`.
- Each extension is a contained directory with `index.ts` as the module entry point.
- Each extension has its own `AGENTS.md` and `tsconfig.json`.
- Shared implementation/types live under `_shared/` only when 2+ extensions need them.
- Tooling config lives under `.config/`; config-only, no importable runtime helpers.

## Modularization Policy

- Single-extension split: local modules first (`logic.ts`, `render.ts`, `utils.ts`).
- Promote to `_shared` only with 2+ extension reuse.
- Keep `index.ts` orchestration-focused; move pure parsing/filtering helpers out when the file grows enough to justify it.

## QA Gates

Run from each touched extension dir when code changes:
- `bun x biome format --write . --config-path ../.config/biome.json`
- `bun x biome lint . --config-path ../.config/biome.json --error-on-warnings`
- `bun --check index.ts`
- targeted behavior validation for changed runtime behavior

## Invariants

- No dependency on Pi extension files, helpers, configs, or generated targets.
- OMP extension source of truth lives under `~/.config/agents/tools/omp/agent/extensions/`.
