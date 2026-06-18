# Brave Search future refactor notes

Read this when planning a larger Brave Search skill refactor. Do not load it for normal lookup usage.

## Expectations

- Default output stays compact and agent-shaped. Raw upstream JSON remains an explicit escape hatch (`raw` command or `raw=1`), never the default.
- `web` keeps `result_filter=web` by default unless the caller explicitly asks otherwise. Accidental video/news side-loads are context pollution.
- Provider failures stay concise. HTML, quota, validation, and rate-limit bodies must never be dumped verbatim to stderr.
- Usage/config errors remain plain stderr + rc=2. Provider/network errors remain compact JSON stderr.
- Live API quirks must be represented honestly in docs. If Brave stops returning a field, docs should say so instead of preserving folklore.
- The CLI must remain stdlib-only unless a future change proves the dependency pays for itself.

## Non-expectations

- This skill should not become a full research synthesizer. Exa or a dedicated research skill owns deeper multi-source synthesis.
- It should not eagerly fetch result pages. Search returns candidates; page extraction belongs elsewhere unless the user explicitly asks for that scope.
- It should not hide quota/rate-limit failures behind retries that burn the user’s API budget.
- It should not reintroduce a `search.ts` / `content.ts` parallel interface.
- It should not keep compatibility aliases for deleted command shapes unless real callsites still require them.

## Ideal shape

- One compact envelope per command:
  - `type`
  - `query`
  - `count`
  - `results`
  - optional provider metadata only when it affects agent decisions.
- Explicit raw mode:
  - `brave-search raw </path> ...`
  - `brave-search web "q" raw=1 ...`
- Errors use one schema across thin HTTP skills:
  - `error.provider`
  - `error.status`
  - `error.kind`
  - `error.message`
  - `error.body_bytes`
  - `error.body_preview`
  - `error.body_truncated`
- Field projection should be conservative. Keep fields that change decisions; drop UI scaffolding, thumbnails, favicons, duplicate URL metadata, and provider layout hints.

## Future refactor candidates

1. Move shared env loading and HTTP error shaping into a small shared helper used by Brave, Reddit, Exa, and Grep.app.
2. Add fixture-based tests for each endpoint shape (`web`, `news`, `local`, `image`, `video`) with real captured redacted payloads.
3. Add live smoke tests gated behind an env flag so normal test runs never spend quota.
4. Revisit the summarizer flow only if Brave reliably returns `summarizer.key` again. Until then, treat it as legacy/experimental.
5. Consider `--fields` or `fields=` only if compact defaults prove too rigid. Avoid adding a mini query language unless real callers need it.
6. Normalize HTML snippets in `description` only if it improves downstream agent quality; do not strip useful emphasis blindly without measuring.

## Regression traps

- `payload.query` may be a dict in real Brave payloads, but tests may use a string. Defensive type checks are intentional.
- `meta_url.path` is a breadcrumb, not the URL path. Do not claim it is fully derivable.
- `profile.img` duplicates favicon-style metadata; it is almost never agent-useful.
- `count` above 20 is a provider validation error; catching it locally avoids a wasted network call.
- `result_filter=web` is the primary byte-saving lever for web search.
