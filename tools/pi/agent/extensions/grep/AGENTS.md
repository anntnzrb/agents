# Grep Extension (Native override + auto-enable)

## Purpose
Keep `grep` always active and add high-signal repo-search ergonomics on top of native Pi behavior:
- `type` filtering (`ts`, `js`, `py`, `rs`, ...)
- `path | paths` multipath search with dedupe
- `offset` pagination with bounded probing
- `outputMode` for three workflows:
  - `content` — default line-match output via `rg --json`
  - `files_with_matches` — file discovery via `rg --files-with-matches`
  - `count` — per-file counts via `rg --count-matches --with-filename`
- stable sorted pagination for `files_with_matches` and `count`
- bounded `timeoutMs` searches
- optional `literal`, `gitignore`, `noIgnore`
- slash-glob normalization for scoped globs (`src/*.ts` -> `**/src/*.ts`)
- `.gitignore` support outside git repos via `--no-require-git`
- default `**/.git/**` exclusion when no explicit `glob` is supplied, to avoid hidden VCS object noise from `rg --hidden`
- stable `content` pagination over rg order, with per-page round-robin balancing for directory result display
- compact UI rendering with shortened paths, explicit `offset:` / `limit:`, and concise mode labels

## Files
- `index.ts` — tool override, schema, activation hooks, pagination/output orchestration
- `ripgrep.ts` — rg argv construction + output-mode process adapters
- `logic.ts` — pure normalization/type-filter helpers
- `output.ts` — content/context output formatting
- `render.ts` — call/result compact rendering
- `index.test.ts` — pure helper behavior checks
- `index.render.test.ts` — compact rendering checks
- `tsconfig.json` — strict TS config matching sibling extensions

## Notes
- Dynamic activation: preserves existing active tools while forcing `grep` on.
- Overrides built-in `grep` with an rg-backed implementation for paging, multipath, output modes, timeout, and type ergonomics.
- `content` mode remains match-oriented and paginates over rg order before display-only per-page balancing to avoid duplicate pages.
- `files_with_matches` and `count` modes collect a bounded file-level probe (`MAX_INTERNAL_PROBE`) before sorting/paging to avoid duplicate pages.
- Output remains bounded by result limits plus 50KB truncation metadata.
- Explicit `glob` input owns filtering semantics and suppresses the default `**/.git/**` exclusion.
