# Grep Auto-Enable Extension

## Purpose
Ensure Pi's built-in `grep` tool is active for every session without hardcoding the full tool list.

## Files
- `index.ts` — on `session_start` / `session_tree`, unions current active tools with `grep`
- `tsconfig.json` — strict TS config matching sibling extensions

## Notes
- Dynamic: preserves whatever tools are already active
- No override: relies on Pi built-in `grep` implementation
- No prompts or UI changes
