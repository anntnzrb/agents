# Context7 MCPorter Reference

Use this when MCPorter discovery, authentication, output shape, or failures matter.

## Contract

MCPorter is the only Context7 transport in this skill.

## MCPorter discovery

Before the first Context7 MCP call in a session:

```text
uv run --script <skill-dir>/scripts/cli.py --config <agent-config-root>/assets/mcporter.jsonc list context7 --brief

Expected tools:

```text
resolve-library-id(query: string, libraryName: string)
query-docs(libraryId: string, query: string)
```

Before the first call to each selected tool, inspect its live schema:

```text
uv run --script <skill-dir>/scripts/cli.py --config <agent-config-root>/assets/mcporter.jsonc list context7.resolve-library-id --schema
uv run --script <skill-dir>/scripts/cli.py --config <agent-config-root>/assets/mcporter.jsonc list context7.query-docs --schema
```

Inspect only the tool needed for the next operation. Live discovery overrides this reference; do not repeat successful discovery or schema inspection in the same session.

## MCPorter calls

Resolve a library:

```text
uv run --script <skill-dir>/scripts/cli.py --config <agent-config-root>/assets/mcporter.jsonc call context7.resolve-library-id --args '{"query":"How to clean up useEffect with async operations","libraryName":"React"}'
```

Fetch documentation:

```text
uv run --script <skill-dir>/scripts/cli.py --config <agent-config-root>/assets/mcporter.jsonc call context7.query-docs --args '{"libraryId":"/reactjs/react.dev","query":"How does useState batch updates?"}'
```

Use `--args` JSON so punctuation, spaces, and structured values cannot be misparsed by the shell.


## Library selection

Resolve with a task-shaped query. Selection rules:

1. Exact package/project match first.
2. Description must match the user's ecosystem and task.
3. Website/manual IDs are often best for API docs; repo IDs are often best for project internals.
4. Snippet count, source reputation, and benchmark score are tiebreakers, not substitutes for relevance.
5. Include language/runtime in the query when names collide across ecosystems.
6. Use a version-specific ID only when resolution returns it and the version matches the request.

Library IDs must start with `/` and usually look like:

```text
/org/project
/org/project/version
/websites/site_name
```

If the user supplied an exact ID, skip resolution.

## Output shapes

MCP commonly returns readable text or Markdown with code and source URLs. Treat observed formatting as a sample, not a stable output schema.

Use source URLs and matching language/context when comparing snippets. Do not infer undocumented response fields.

## Authentication and rate limits

Context7 calls use `Authorization: Bearer ${CONTEXT7_API_KEY}` from the shared MCPorter registry. Invoke MCPorter only through the skill launcher so credentials can come from the existing process environment or the skill-local `.env`.

Never print, persist in tracked files, or pass credentials as command arguments. Do not invoke OAuth.

If Context7 reports authentication, quota, or rate limiting:

1. State the failure.
2. Suggest checking `CONTEXT7_API_KEY` or the skill-local `.env`.
3. Do not silently use training data as though it were current documentation.


## Error handling

- MCPorter missing, server absent, discovery failure, MCP transport failure, or network failure: report that Context7 could not be reached.
- Invalid ID: resolve again and use the exact returned `/org/project` ID.
- No results: retry once with the official package/project name; otherwise state that no good match was found.
- Ambiguous results: retry once with language/runtime/package qualifiers; then ask if material ambiguity remains.
- Thin results: state that coverage is thin and route to repository docs or code search.
- Rate limit/quota: report it and suggest the user's normal secret-management path.

Keep Context7 retrieval calls to three per user question unless the user explicitly requests broader exploration. Discovery does not consume that retrieval budget.
