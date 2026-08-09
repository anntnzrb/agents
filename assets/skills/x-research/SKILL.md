---
name: x-research
description: Research public X/Twitter posts, timelines, searches, and conversations with bounded FxTwitter evidence.
license: GPL-3.0-or-later
metadata:
  author: anntnzrb

---

# X Research

Use this skill for explicit public X/Twitter post URLs or IDs, bounded user timelines, topic searches, and conversation inspection. It is read-only and returns evidence for the calling agent; it does not write to X or generate sentiment itself.

## Hard limits

- The default provider is anonymous public FxTwitter v2 (`fxtwitter`); set `X_RESEARCH_BASE_URL` only for an explicit compatible deployment
- Make one bounded request per command. Never retry, auto-page, scrape HTML, use browser automation, use credentials, cache results, or silently switch providers
- Treat every result as unofficial, possibly incomplete evidence. A missing result does not establish deletion, suspension, or nonexistence
- Keep sentiment sample-scoped. The consuming agent classifies returned text and cites post IDs/URLs; this CLI does not infer public opinion
- For news, X posts are leads/evidence. Corroborate material claims with independent `web_search`/`read` sources

## Commands

Run from the repository root with the public entrypoint:

```text
uv run --script assets/skills/x-research/scripts/cli.py fetch TARGET [--provider fxtwitter] [--lang LANG] [--summary] [--pretty]
uv run --script assets/skills/x-research/scripts/cli.py user-posts HANDLE [--count 1..100] [--cursor CURSOR] [--include-replies] [--summary] [--pretty]
uv run --script assets/skills/x-research/scripts/cli.py search QUERY [--count 1..100] [--feed latest|top|media] [--cursor CURSOR] [--summary] [--pretty]
uv run --script assets/skills/x-research/scripts/cli.py conversation NUMERIC_ID [--ranking-mode likes|recency] [--cursor CURSOR] [--summary] [--pretty]
```

`fetch` accepts a numeric post ID or only an `https://x.com/.../status/<numeric-id>` or `https://twitter.com/.../status/<numeric-id>` URL, with an optional trailing slash. `user-posts` accepts a handle; replies are excluded unless `--include-replies` is explicit. Search whitespace is collapsed but the query's operators and text otherwise remain verbatim. No command automatically fetches another page.
`--summary` and `--pretty` are local presentation controls: they do not change the provider endpoint, request query, count, cursor, or number of wire calls. The default is the complete normalized compact JSON envelope.

Use `--summary` for routine output. It is a deterministic projection that preserves full post text, IDs, URLs, timestamps, citation fields, completeness, and provenance while omitting metrics and media. Use unflagged full output only when optional metrics or media are needed. `--pretty` changes only JSON whitespace; it remains machine-valid JSON with two-space indentation and a trailing newline. Direct invocation needs neither `jq` nor `pipefail`; `pipefail` matters only when a caller intentionally constructs a shell pipeline.

## Output and completeness

- By default, success is compact JSON on stdout: `{"ok":true,"schema_version":1,"command":"...","data":{...}}`; `--pretty` changes only its whitespace
- Failure is JSON on stderr with the same envelope and `error.code`, `error.message`, and `error.details`; it is compact by default. Exit `2` means usage/config/validation, and exit `1` means provider/network/HTTP/JSON/provider-payload failure
- Every successful data object carries `provider`, `official:false`, `auth_mode:"none"`, exact `source_url`, `endpoint`, UTC RFC3339 `fetched_at`, and `provider_status`
- Page data carries `requested_count`, `returned_count`, `complete`, and `complete_reason` (`bounded_page`, `provider_exhausted`, or `provider_incomplete`). It includes `cursor` and `has_more` only when a usable bottom cursor is supplied. Conversation data carries `target`, `thread`, `replies`, and the same cursor/completeness signals
- Report the requested query/handle/URL, returned count, cursor, and completeness reason when summarizing results. Never call a bounded page a complete timeline or population sample

## Agent workflows

### Latest posts from a user

Run one bounded page with `uv run --script assets/skills/x-research/scripts/cli.py user-posts HANDLE --count COUNT --summary [--pretty]` (choose a concrete count from 1–100; omit `--pretty` for default compact output). Report the handle, count requested/returned, whether replies were included, cursor, and completeness. Use unflagged full output only when optional metrics or media are needed. Use `conversation` only when the user asks for a particular thread.

### Sample-scoped sentiment

Run `uv run --script assets/skills/x-research/scripts/cli.py search QUERY --count COUNT --feed latest --summary [--pretty]` (or `uv run --script assets/skills/x-research/scripts/cli.py user-posts HANDLE --count COUNT --summary [--pretty]`) once with a fixed query and bounded count. Classify each returned post from its text as positive, negative, neutral, mixed, or unclear; cite its ID and URL; aggregate counts and confidence; label the result as a returned-sample observation, not public-opinion truth. Use unflagged full output only when optional metrics or media are needed.

### X-plus-web news exploration

Run `uv run --script assets/skills/x-research/scripts/cli.py search QUERY --count COUNT --feed latest --summary [--pretty]` for bounded X discovery/evidence, then use `web_search` and `read` for independent primary or credible sources. Use unflagged full output only when optional metrics or media are needed. Separate X evidence from independently verified claims, show timestamps and source roles, describe agreement/conflict, and retain uncertainty when either source set is incomplete.

## Required follow-up reads

| Need | Read | When |
| --- | --- | --- |
| Provider endpoints, response keys, status semantics | `references/provider.md` | Before interpreting provider fields, errors, or cursors |
| Detailed normalization and completeness caveats | `references/provider.md` | When optional fields are missing or a page is incomplete |
| News or sentiment workflow | This file | Before routing evidence to `web_search`/`read` or making sample-scoped classifications |
