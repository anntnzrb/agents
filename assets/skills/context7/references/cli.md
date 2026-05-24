# ctx7 CLI Reference

Use this when command behavior, auth, output shape, telemetry, or failures matter.

## Contract

This skill uses `bun x ctx7@latest` directly. There is no install step and no MCP path.

Primary commands:

```text
bun x ctx7@latest library <name> "<query>"
bun x ctx7@latest docs <libraryId> "<query>"
```

Structured output:

```text
bun x ctx7@latest library <name> "<query>" --json
bun x ctx7@latest docs <libraryId> "<query>" --json
```

## `library`

Resolves a library/framework/SDK/product name to Context7 IDs.

```text
bun x ctx7@latest library react "How to clean up useEffect with async operations" --json
bun x ctx7@latest library "Next.js" "How to set up app router middleware" --json
bun x ctx7@latest library zap "zig http server routes websocket" --json
```

Always pass a query. The query changes ranking and disambiguation.

### Selection fields

Common `--json` fields:

- `id`: Context7 ID to pass to `docs`.
- `title`: display name; not unique.
- `description`: best discriminator for same-name packages.
- `totalSnippets`: indexed coverage size, not correctness by itself.
- `trustScore`: source reputation.
- `benchmarkScore`: retrieval quality signal; `0` can appear for niche/exact projects.
- `versions`: version-specific suffixes when indexed.

Selection rules:

1. Exact package/project match first.
2. Description must match the user's ecosystem and task.
3. Website/manual IDs are often best for API docs; repo IDs are often best for project internals.
4. Snippet count, trust score, and benchmark score are tiebreakers, not substitutes for relevance.
5. Include language/runtime in the query when names collide across ecosystems.

## `docs`

Fetches documentation for a Context7 ID.

```text
bun x ctx7@latest docs /reactjs/react.dev "How does useState batch updates?"
bun x ctx7@latest docs /tokio-rs/tokio "select cancellation pinning timeout"
bun x ctx7@latest docs /ziglang/zig "allocator comptime error unions build system"
```

Library IDs must start with `/` and usually look like:

```text
/org/project
/org/project/version
/websites/site_name
```

If the user already supplied an exact ID, skip `library` and call `docs` directly.

## JSON mode

Use `--json` when the agent needs structured parsing or exact fields. Do not require `jq`; parse the JSON directly in the model or with an existing structured tool if needed.

Observed shapes:

- `library --json`: array of result objects.
- `docs --json`: object with `codeSnippets` and `infoSnippets`.

Useful `docs --json` fields:

- `codeTitle`, `codeDescription`, `codeLanguage`
- `codeId`: provenance URL or Context7 generated-doc ID
- `codeList[].language`, `codeList[].code`
- `infoSnippets[].breadcrumb`, `infoSnippets[].content`, `infoSnippets[].pageId`

Prefer `docs --json` for provenance-sensitive answers, comparing snippets, or debugging odd output. Prefer plain `docs` for a direct human-readable answer.

## Auth and rate limits

Docs commands work without authentication at lower public limits.

For higher limits, the CLI reads:

```text
CONTEXT7_API_KEY
```

Do not run persistent auth flows from this skill. In normal skill use, do not run `ctx7 login`, `ctx7 setup`, or anything that writes agent configuration.

If a command reports quota or rate limiting:

1. State that Context7 returned a quota/rate-limit failure.
2. Suggest setting `CONTEXT7_API_KEY` in the environment for higher limits.
3. Do not silently fall back to training data as if it were current docs.

## Telemetry

The upstream CLI may send anonymous usage telemetry. To disable for a command:

```text
CTX7_TELEMETRY_DISABLED=1 bun x ctx7@latest docs /reactjs/react.dev "useState hook"
```

## Error handling

- Invalid ID: rerun `library` and use the exact `/org/project` ID.
- No results: retry once with the official package/project name; otherwise say no good Context7 match was found.
- Ambiguous results: retry once with language/runtime/package qualifiers; then ask if ambiguity remains.
- Thin results: say Context7 coverage is thin and route to repo docs/code search.
- Network/registry failure: report that `bun x ctx7@latest` or the Context7 API could not be reached.
- Rate limit/quota: report it and suggest `CONTEXT7_API_KEY`.

Keep total Context7 calls to three per user question unless the user explicitly asks for broader search.
