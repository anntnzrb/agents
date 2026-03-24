# Turn Stats Extension

## Purpose
Auto-show per-turn stats in Pi interactive UI.

## Files
- `index.ts` — hooks `agent_start`/`agent_end`, computes output speed plus input/output counts, emits `ctx.ui.notify(...)`
- `tsconfig.json` — strict TS config matching sibling extensions

## Notes
- Minimal implementation
- UI-only
- No tools
- No hidden context injection
- Supports both `usage.input/output` and `usage.inputTokens/outputTokens`
