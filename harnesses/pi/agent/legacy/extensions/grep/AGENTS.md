# Grep Extension (native override + auto-enable)

## Purpose

Keep `grep` active; add repo-search ergonomics without changing the broad native search contract:

- `type` filter (`ts`, `js`, `py`, `rs`, ...)
- `paths` multipath + dedupe
- `offset` pagination + bounded probing
- `outputMode`:
  - `content` — default line matches via `rg --json`
  - `files_with_matches` — files via `rg --files-with-matches`
  - `count` — per-file counts via `rg --count-matches --with-filename`
- stable sorted pagination for file/count modes
- bounded `timeoutMs`
- optional `literal`, `ignored`, `pcre2`
- slash-glob normalization: `src/*.ts` -> `**/src/*.ts`
- `.gitignore` outside git repos via `--no-require-git`
- default `**/.git/**` exclusion unless explicit `glob`
- stable `content` pagination over rg order; per-page round-robin display only
- compact UI: shortened paths, explicit `offset:` / `limit:`, concise mode labels

## Files

- `index.ts` — override, schema, activation hooks, pagination/output orchestration
- `ripgrep.ts` — rg argv + output-mode process adapters
- `logic.ts` — pure normalization/type-filter helpers
- `output.ts` — content/context output formatting
- `render.ts` — compact call/result rendering
- `index.test.ts` — helper behavior
- `index.render.test.ts` — compact rendering
- `tsconfig.json` — strict TS config

## Behavior Notes

- Dynamic activation preserves active tools while forcing `grep` on.
- Overrides built-in `grep` with rg-backed paging, multipath, output modes, timeout, type ergonomics.
- `pcre2`: passes `--pcre2` for look-around/backreferences unless `literal` is enabled.
- `content`: match-oriented; paginates rg order before display-only balancing to avoid duplicate pages.
- `files_with_matches`/`count`: bounded file-level probe (`MAX_INTERNAL_PROBE`) before sort/page to avoid duplicate pages.
- Output bounded by result limits + 50KB truncation metadata.
- Explicit `glob` owns filtering; suppresses default `**/.git/**` exclusion.

## Stop Rules

- Preserve native `grep` intent unless the task explicitly targets override behavior.
- Keep changes tactical: schema, rg argv, pagination, output formatting, or compact rendering.
