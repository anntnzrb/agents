# Find Extension (native override + auto-enable)

## Purpose
Keep `find` active; add file-discovery ergonomics:
- `hidden` toggle
- `kind` filter:
  - `file` — default, `fd --type file`
  - `directory` — `fd --type directory`
  - `any` — no fd type filter
- `gitignore` / `noIgnore` controls (`noIgnore` overrides `gitignore`)
- `path | paths` multipath + dedupe
- slash-pattern scoped globs: `src/*.ts` -> `**/src/*.ts` with full-path matching
- deterministic returned output via local sort/dedupe
- `limit+1` probe for truncation notice
- bounded `timeoutMs` + explicit timeout error
- compact UI: shortened paths, explicit `limit:` labels

## Files
- `index.ts` — override, schema, activation hooks, fd execution, compact rendering
- `logic.ts` — pure normalization + fd argv construction
- `index.test.ts` — helper behavior
- `index.render.test.ts` — compact rendering
- `tsconfig.json` — strict TS config

## Notes
- Dynamic activation preserves active tools while forcing `find` on.
- Overrides built-in `find` with fd-backed multipath, kind, ignore, timeout behavior.
- Default `kind=file` matches tool contract; avoids surprise directories.
- `hidden` independent from ignore handling; `noIgnore` does not imply hidden files.
- No mtime sort/cache/index complexity; tactical filesystem discovery only.
