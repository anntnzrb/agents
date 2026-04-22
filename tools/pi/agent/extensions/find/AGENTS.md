# Find Auto-Enable Extension

## Purpose
Ensure Pi's built-in `find` tool is active for every session without hardcoding the full tool list.

## Files
- `index.ts` — on `session_start` / `session_tree`, unions current active tools with `find`
- `tsconfig.json` — strict TS config matching sibling extensions

## Notes
- Dynamic: preserves whatever tools are already active
- No override: relies on Pi built-in `find` implementation
- No prompts or UI changes
