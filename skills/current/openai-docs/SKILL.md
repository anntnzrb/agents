---
disable-model-invocation: true
name: openai-docs
description: "Use when fetching official OpenAI API reference, SDK documentation, and model specifications."
license: AGPL-3.0-or-later
compatibility: Redirects to Context7 MCPorter runner.
---

# OpenAI Docs

Official OpenAI developer documentation, API references, and SDK guidelines are provided directly via **Context7** (`context7` MCP server) or the official **OpenAI Docs MCP** (`openai-docs`).

## Preferred Entry Point: Context7 via MCPorter

Query OpenAI SDKs, Structured Outputs, Realtime API, and model capabilities through Context7:

1. **Resolve OpenAI library ID:**
   ```sh
   mcporter call context7.resolve_library_id query="openai" --output json
   ```
2. **Fetch verified documentation snippets:**
   ```sh
   mcporter call context7.get_library_docs library_id="/openai/openai-node" query="structured outputs schema" --output json
   ```

## Direct OpenAI Docs MCP (Alternative)

For live exploration against the official developer portal endpoint:
```sh
mcporter list openai-docs --brief
```
