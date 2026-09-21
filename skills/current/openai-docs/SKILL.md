---
disable-model-invocation: true
name: openai-docs
description: "Search and fetch official OpenAI API reference, endpoints, OpenAPI specs, and developer docs via MCPorter."
license: AGPL-3.0-or-later
compatibility: Requires openai-docs remote MCP server via MCPorter.
---

# OpenAI Docs

Search and fetch official OpenAI documentation, API endpoints, and OpenAPI specifications via the first-party OpenAI Developer Docs MCP server (`mcporter call openai-docs.<tool>`).

Tool schemas are dynamic and authoritative. When discovering capabilities or parameter requirements, inspect the live server directly.

## Discovery Workflow for Agents (Cold Start)

1. **Roster of available tools (Short listing):**
   ```sh
   mcporter list openai-docs --brief
   ```
2. **Inspect exact parameters and schema for a specific tool:**
   ```sh
   mcporter list openai-docs.<tool_name> --schema
   ```

## Core Operations

### 1. Search Official Documentation
Search across all official guides, conceptual docs, and migration manuals:
```sh
mcporter call openai-docs.search_openai_docs query="structured outputs response_format json_schema" --output json
```

### 2. Fetch Full Document by URL / Path
Retrieve the complete content of a specific documentation page:
```sh
mcporter call openai-docs.fetch_openai_doc url="https://developers.openai.com/docs/guides/structured-outputs" --output json
```

### 3. List API Endpoints
List all current API endpoints published by OpenAI:
```sh
mcporter call openai-docs.list_api_endpoints --output json
```

### 4. Get OpenAPI Spec & Code Examples
Fetch the exact OpenAPI schema and code examples for a specific endpoint:
```sh
mcporter call openai-docs.get_openapi_spec url="/v1/chat/completions" languages='["python", "typescript"]' --output json
```
