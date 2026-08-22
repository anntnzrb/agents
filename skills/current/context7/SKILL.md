---
name: context7
description: "Use when current library, SDK, or API documentation and code examples must be fetched. For up-to-date documentation."
license: AGPL-3.0-or-later
metadata:
  author: anntnzrb

---

# Context7

Use this skill to fetch up-to-date documentation, API signatures, migration guides, and verified code examples directly from Context7 for libraries, frameworks, SDKs, and CLI tools.

## Follow-up reads

| Need | Read | When |
|---|---|---|
| CLI subcommands and flags | [references/cli-reference.md](references/cli-reference.md) | Querying with custom API keys, timeouts, or running agent setup |
| Library selection heuristics | [references/library-resolution.md](references/library-resolution.md) | Disambiguating multiple library candidates or choosing versions |
| Practical workflows | [cookbook/recipes.md](cookbook/recipes.md) | Copying ready-to-run recipes for React, Next.js, Effect, and CLI scripting |

## When to use

- Fetching current API syntax, configuration options, and verified code snippets
- Investigating version migrations (e.g. Next.js 14 to 15, React 18 to 19)
- Library-specific debugging and setup guides
- Prefer over general web search for library, SDK, and framework documentation

Do NOT use for general programming concepts, debugging pure business logic, refactoring from scratch, or code review.

## Entry point

Run `bun x ctx7@latest` directly in terminal:

```bash
# Verify availability
bun x ctx7@latest --version
```

Set `CTX7_TELEMETRY_DISABLED=1` to disable telemetry.

## Core workflow

Documentation retrieval is a two-step process:

### 1. Resolve library name to Context7 ID

Search the Context7 index with the official library name and an optional task query:

```bash
bun x ctx7@latest library <name> ["<what to look up>"] [--json]
```

Use official punctuation (e.g. `"Next.js"` not `"nextjs"`, `"Three.js"` not `"threejs"`).

Results return candidate library IDs starting with `/` (such as `/reactjs/react.dev` or `/facebook/react`), alongside code snippet counts, source reputation, and benchmark scores.

### 2. Query documentation with Context7 ID

Fetch targeted documentation snippets with the resolved library ID:

```bash
bun x ctx7@latest docs <libraryId> "<single topic question>" [--json]
```

Queries MUST use the full library ID starting with `/`. Calling with a bare name will fail.

### Best practices and guardrails

- Keep each query focused on a single topic. If a question spans multiple distinct concepts (e.g. routing, auth, caching), run separate queries per concept. Combined queries dilute search ranking.
- Do not call `library` or `docs` more than 3 times per question. If unresolved after 3 attempts, proceed with the best available data.
- Never include credentials, API keys, or private code in queries.
- Always cite the resolved library ID in your final answer.

## Authentication and setup

- Anonymous queries: Documentation commands work without login.
- Higher rate limits: Authenticate via `bun x ctx7@latest login` or set `export CONTEXT7_API_KEY=your_key`.
- Configure agent MCP: `bun x ctx7@latest setup --mcp --claude` or `bun x ctx7@latest setup --mcp --cursor`.
