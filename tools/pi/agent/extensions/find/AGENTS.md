# Find Extension (Native override + auto-enable)

## Purpose
Keep `find` always active and add low-maintenance file-discovery ergonomics:
- `hidden` toggle
- `kind` filtering:
  - `file` — default, maps to `fd --type file`
  - `directory` — maps to `fd --type directory`
  - `any` — no fd type filter
- `gitignore` / `noIgnore` controls (`noIgnore` overrides `gitignore`)
- `path | paths` multipath discovery with dedupe
- slash-pattern handling for scoped globs (`src/*.ts` -> `**/src/*.ts` with full-path matching)
- deterministic output for returned results via local sort/dedupe
- `limit+1` probe for truncation notice
- bounded `timeoutMs` with explicit timeout error
- compact UI rendering with shortened paths and explicit `limit:` labels

## Files
- `index.ts` — tool override, schema, activation hooks, fd execution, compact rendering
- `logic.ts` — pure normalization + fd argv construction
- `index.test.ts` — pure helper behavior checks
- `index.render.test.ts` — compact rendering checks
- `tsconfig.json` — strict TS config matching sibling extensions

## Notes
- Dynamic activation: preserves existing active tools while forcing `find` on.
- Overrides built-in `find` with fd-backed multipath, kind, ignore, and timeout behavior.
- Default `kind` is `file` to match the tool contract and avoid surprise directories.
- `hidden` is independent from ignore handling: `noIgnore` does not imply hidden files.
- Avoids mtime sort/cache/index complexity by design; this remains tactical filesystem discovery, not indexed search.
