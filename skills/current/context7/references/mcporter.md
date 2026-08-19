# Context7 MCPorter
Use for Context7 recovery, authentication, output shape, or failures.

MCPorter only Context7 transport in this skill.

## Known tools

The skill's direct recipes use:

```text
resolve-library-id(query: string, libraryName: string)
query-docs(libraryId: string, query: string)
```

Do not discover these tools or inspect their schemas before ordinary calls. If a call reports a missing tool or invalid input, or optional inputs matter, inspect only the affected tool:

```text
uv run --script <skill-dir>/scripts/cli.py list context7.resolve-library-id --schema
uv run --script <skill-dir>/scripts/cli.py list context7.query-docs --schema
```

Live schemas override this reference when inspected. Never load the whole server schema.

## Calls
Resolve a library:

```text
uv run --script <skill-dir>/scripts/cli.py call context7.resolve-library-id --args '{"query":"How to clean up useEffect with async operations","libraryName":"React"}'
```

Fetch documentation:

```text
uv run --script <skill-dir>/scripts/cli.py call context7.query-docs --args '{"libraryId":"/reactjs/react.dev","query":"How does useState batch updates?"}'
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
Context7 calls use `Authorization: Bearer ${CONTEXT7_API_KEY}` from the shared MCPorter registry when a key is configured. The key is optional: without it the launcher passes a header-stripped config copy and Context7 serves anonymous requests at low rate limits. Invoke MCPorter only through the skill launcher so credentials can come from the existing process environment or skill-local `.env`.

NEVER print, persist in tracked files, or pass credentials as command arguments. NEVER invoke OAuth.

Authentication, quota, or rate-limit failure:
1. State the failure.
2. Anonymous access is rate-limited; suggest `CONTEXT7_API_KEY` or the skill-local `.env` for higher limits.
3. Do not silently use training data as current documentation.

## Errors
- MCPorter missing, server absent, discovery failure, MCP transport failure, or network failure → report Context7 could not be reached.
- Invalid ID → resolve again and use exact returned `/org/project` ID.
- No results → retry once with official package/project name; otherwise state no good match was found.
- Ambiguous results → retry once with language/runtime/package qualifiers; then ask if material ambiguity remains.
- Thin results → state coverage is thin and route to repository docs or code search.
- Rate limit/quota → report it and suggest the user's normal secret-management path.

Keep Context7 retrieval calls to three per user question unless the user explicitly requests broader exploration. Diagnostics do not consume that retrieval budget.
