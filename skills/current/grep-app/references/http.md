# Grep.app HTTP Reference

Base URL: `https://grep.app/api/search`; public searches require no auth.

Environment: tracked template `.env.example`; optional override `GREP_APP_BASE_URL`.

Parameters
- Required: `q`; literal or regex pattern.
- Modifiers: `regexp=true` treats `q` as regex; `case=true` matches case; `words=true` whole-word-ish matching.
- Filters: `f.repo=owner/repo`; `f.path=src/`; `f.lang=TypeScript`.

Examples

Literal search:

```text
uv run --script <skill-dir>/scripts/cli.py search "useState(" f.lang=TypeScript
```

Regex search:

```text
uv run --script <skill-dir>/scripts/cli.py regex "useState\\(" f.lang=TypeScript
```

Scoped search:

```text
uv run --script <skill-dir>/scripts/cli.py search "errgroup.WithContext(" f.repo=golang/sync
```

Response: JSON fields `time`, `facets`, `hits.total`, `hits.hits[]`.
Hit fields: `repo`, `branch`, `path`, `content.snippet`, `total_matches`.

Notes
- Response snippets HTML, not plain text.
- Facets help narrow a broad first pass before repeating with `f.repo`, `f.path`, or `f.lang`.
- HTTP `429` possible under rate limiting → service throttle, not helper initialization problem.

Validation

```text
uv run --script <skill-dir>/scripts/cli.py --help
```
