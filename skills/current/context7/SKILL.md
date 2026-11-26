---
name: context7
description: "Use when fetching library or framework docs, API signatures, and examples via Context7, not for OpenAI OpenAPI specs."
license: AGPL-3.0-or-later
compatibility: Requires Context7 MCP server via MCPorter.
---

# Context7

Fetch verified, version-accurate documentation and code examples via the dynamic MCP runner (`mcporter call context7.<tool>`).

Tool schemas are dynamic and authoritative. When discovering capabilities or parameter requirements, inspect the live server directly.

## Discovery Workflow for Agents (Cold Start)

1. **Roster of available tools (Short listing):**
   ```sh
   mcporter list context7 --brief
   ```
2. **Inspect exact parameters and schema for a specific tool:**
   ```sh
   mcporter list context7.<tool_name> --schema
   ```

## Core Workflow

Documentation retrieval is a two-step process:

### 1. Resolve Library to Context7 ID
Search the index with the library name (e.g., `"Next.js"`, `"React"`, `"OpenAI"`, `"Effect"`, `"Pydantic"`):
```sh
mcporter call context7.resolve-library-id libraryName="Next.js" query="App Router Server Actions" --output json
```
*(Returns candidate library IDs starting with `/`, such as `/vercel/next.js` or `/openai/openai-node`).*

### 2. Query Documentation Snippets
Fetch targeted documentation using the resolved library ID:
```sh
mcporter call context7.query-docs libraryId="/vercel/next.js" query="App Router Server Actions" language="TypeScript" --output json
```

## Best Practices
- **Single-topic queries:** Keep each query focused on a single topic (e.g. routing, caching, auth).
- **Exact library ID:** Always pass the full library ID starting with `/` returned by step 1 as `libraryId`; pass the optional version as `version`, not as a suffix you construct yourself.
- **Resolution inputs:** `resolve-library-id` requires both `libraryName` and a focused `query`. The query is sent to Context7, so never include credentials, personal data, or proprietary code.
- **Do not guess:** If a library is not found, search with official punctuation.
