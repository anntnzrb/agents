# Built-ins Extension

## Purpose
Ensure Pi starts with selected core built-ins (`grep` and `find`) enabled.

## Files
- `index.ts` — adds `grep` + `find` to the active tool set on every `session_start`
- `tsconfig.json` — strict TS config aligned with sibling extensions

## Notes
- Uses built-in tools; no custom tool overrides
- Idempotent: only updates active tools when missing
- No persistent state
