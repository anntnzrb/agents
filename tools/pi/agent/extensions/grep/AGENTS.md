# Grep Extension (Native override + auto-enable)

## Purpose
Keep `grep` always active and add high-signal ergonomics on top of native Pi behavior:
- `type` filtering (`ts`, `js`, `py`, `rs`, ...)
- `offset` pagination with `limit+1` probing
- `path | paths` multipath search with dedupe
- optional `literal`, `gitignore`, `noIgnore`
- round-robin balancing across files
- sparse-match auto-context

## Files
- `index.ts` — tool override + activation hooks
- `index.test.ts` — pure helper behavior checks
- `tsconfig.json` — strict TS config matching sibling extensions

## Notes
- Dynamic activation: preserves existing active tools while forcing `grep` on
- Overrides built-in `grep` to add paging/multipath/type ergonomics
- Uses shell `rg` backend directly with bounded output and truncation metadata
