# Context7 MCPorter
Use for Context7 discovery, authentication, output shape, or failures.

MCPorter only Context7 transport in this skill.

## Discovery
Before first Context7 MCP call/session:

```text
uv run --script <skill-dir>/scripts/cli.py --config <agent-config-root>/assets/mcporter.jsonc list context7 --brief
```

Expected tools:

```text
resolve-library-id(query: string, libraryName: string)
query-docs(libraryId: string, query: string)
```

Before first call to each selected tool, inspect its live schema:

```text
uv run --script <skill-dir>/scripts/cli.py --config <agent-config-root>/assets/mcporter.jsonc list context7.resolve-library-id --schema
uv run --script <skill-dir>/scripts/cli.py --config <agent-config-root>/assets/mcporter.jsonc list context7.query-docs --schema
```

Inspect only the tool needed for the next operation. Live discovery overrides this reference; do not repeat successful discovery or schema inspection in the same session.

## Calls
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
Resolve with a task-shaped query:
1. Exact package/project match first.
2. Description must match user ecosystem and task.
3. Website/manual IDs often best for API docs; repo IDs often best for project internals.
4. Snippet count, source reputation, and benchmark score are tiebreakers, not relevance substitutes.
5. Include language/runtime when names collide across ecosystems.
6. Use a version-specific ID only when resolution returns it and version matches the request.

Library IDs start with `/` and usually look like:

```text
/org/project
/org/project/version
/websites/site_name
```

User-supplied exact ID → skip resolution.

## Output
MCP commonly returns readable text or Markdown with code and source URLs. Observed formatting is sample, not stable output schema.

Use source URLs and matching language/context when comparing snippets. Do not infer undocumented response fields.

## Authentication and rate limits
Context7 calls use `Authorization: Bearer ${CONTEXT7_API_KEY}` from the shared MCPorter registry. Invoke MCPorter only through the skill launcher so credentials can come from the existing process environment or skill-local `.env`.

NEVER print, persist in tracked files, or pass credentials as command arguments. NEVER invoke OAuth.

Authentication, quota, or rate-limit failure:
1. State the failure.
2. Suggest checking `CONTEXT7_API_KEY` or the skill-local `.env`.
3. Do not silently use training data as current documentation.

## Errors
- MCPorter missing, server absent, discovery failure, MCP transport failure, or network failure → report Context7 could not be reached.
- Invalid ID → resolve again and use exact returned `/org/project` ID.
- No results → retry once with official package/project name; otherwise state no good match was found.
- Ambiguous results → retry once with language/runtime/package qualifiers; then ask if material ambiguity remains.
- Thin results → state coverage is thin and route to repository docs or code search.
- Rate limit/quota → report it and suggest the user's normal secret-management path.

Keep Context7 retrieval calls to three per user question unless the user explicitly requests broader exploration. Discovery does not consume that retrieval budget.
