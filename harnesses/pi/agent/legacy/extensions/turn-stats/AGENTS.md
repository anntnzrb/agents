# Turn Stats Extension

## Purpose

Auto-show per-turn stats in Pi interactive UI.

## Files

- `index.ts` — hooks `agent_start`/`agent_end`, computes output speed plus input/output counts, appends context-gc broom stats when present, emits `ctx.ui.notify(...)`
- `index.test.ts` — helper tests for usage and broom-stat formatting
- `tsconfig.json` — strict TS config matching sibling extensions

## Invariants

- Minimal implementation
- UI-only
- No tools
- No hidden context injection
- Optional context-gc awareness via session custom entries; absent entries render nothing
- Supports both `usage.input/output` and `usage.inputTokens/outputTokens`

## Stop Rules

- Keep stats user-visible only.
- Do not add provider/model context mutation from this extension.
