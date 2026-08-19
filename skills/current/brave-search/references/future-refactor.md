# Brave Search future refactor

Scope: read for larger skill refactors, not normal lookup.

## Expectations
- Output compact and agent-shaped; raw upstream JSON explicit only via `raw` command or `raw=1`, never default.
- `web`: default `result_filter=web`; caller may override. Prevents accidental video/news context pollution.
- Provider failures concise: never dump HTML, quota, validation, or rate-limit bodies verbatim to stderr.
- Usage/config errors: plain stderr + rc=2. Provider/network errors: compact JSON stderr.
- Docs represent live API quirks honestly; if Brave stops returning a field, document that rather than folklore.
- CLI stdlib-only unless a future change proves the dependency pays for itself.

## Non-expectations
- Not a full research synthesizer; Exa or a dedicated research skill owns deeper multi-source synthesis.
- No eager result-page fetching: search returns candidates; page extraction belongs elsewhere unless the user explicitly asks for that scope.
- No retries that hide quota/rate-limit failures while burning the user’s API budget.
- No `search.ts` / `content.ts` parallel interface.
- No compatibility aliases for deleted command shapes unless real callsites still require them.

## Ideal shape
- One compact envelope per command: `type`, `query`, `count`, `results`; optional provider metadata only when it affects agent decisions.
- Explicit raw modes:
  - `brave-search raw </path> ...`
  - `brave-search web "q" raw=1 ...`
- One error schema across thin HTTP skills: `error.provider`, `error.status`, `error.kind`, `error.message`, `error.body_bytes`, `error.body_preview`, `error.body_truncated`.
- Conservative field projection: retain decision-changing fields; drop UI scaffolding, thumbnails, favicons, duplicate URL metadata, and provider layout hints.

## Future refactor candidates
1. Shared env loading + HTTP error shaping helper for Brave, Reddit, Exa, and Grep.app.
2. Fixture tests for each endpoint shape (`web`, `news`, `local`, `image`, `video`) using captured redacted payloads.
3. Live smoke tests behind an env flag; normal test runs never spend quota.
4. Revisit summarizer only if Brave reliably returns `summarizer.key`; until then, legacy/experimental.
5. Consider `--fields` or `fields=` only if compact defaults prove too rigid; no mini query language unless real callers need it.
6. Normalize HTML in `description` only if downstream agent quality improves; do not strip useful emphasis blindly: measure first.

## Regression traps
- `payload.query` may be a dict in real Brave payloads but a string in tests; defensive type checks intentional.
- `meta_url.path` is a breadcrumb, not the URL path; do not claim full derivability.
- `profile.img` duplicates favicon-style metadata and is almost never agent-useful.
- `count` above 20 is a provider validation error; catch locally to avoid a wasted network call.
- `result_filter=web` is the primary byte-saving lever for web search.
