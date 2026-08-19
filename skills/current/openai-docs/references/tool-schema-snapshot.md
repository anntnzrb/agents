# OpenAI Docs MCP Tool Schema Snapshot

Snapshot: **2026-07-16**; MCPorter **0.12.3**  
Server: `openai-docs` at `https://developers.openai.com/mcp`  
Inventory: **5 tools**  
Live schema authoritative when inspected.
Load this snapshot only for broad tool comparison or targeted live-schema failure; the focused skill already provides ordinary recipes.
Declarations expose input schemas only; NEVER invent output fields or schemas.  
Descriptions and input schemas below exact.

Refresh when drift matters:

```text
mcporter list openai-docs.<tool> --schema
```

MUST inspect actual tool results.

## `search_openai_docs`

Description:

```text
Search across `platform.openai.com`, `developers.openai.com`, and `learn.chatgpt.com` docs. Use this
whenever you are working with the OpenAI API (including the Responses API), OpenAI API SDKs, ChatGPT
Apps SDK, or Codex. Results include URLs—**after `search`, use `fetch_openai_doc`** to read/quote
the exact markdown.
```

Signature:

```text
function search_openai_docs(query: string, limit?: number, cursor?: string);
```

Input schema:

```json
{
  "type": "object",
  "properties": {
    "query": {
      "type": "string",
      "minLength": 1
    },
    "limit": {
      "type": "integer",
      "minimum": 1,
      "maximum": 50
    },
    "cursor": {
      "type": "string"
    }
  },
  "required": [
    "query"
  ],
  "$schema": "http://json-schema.org/draft-07/schema#"
}
```

## `list_openai_docs`

Description:

```text
List or browse pages from `platform.openai.com`, `developers.openai.com`, and `learn.chatgpt.com`
that this server crawls (useful when you don’t know the right query yet or you’re paging through
results). Use this whenever you are working with the OpenAI API (including the Responses API),
OpenAI API SDKs, ChatGPT Apps SDK, or Codex. Results include URLs—**after `list`, use
`fetch_openai_doc`** on a result URL to get the full markdown.
```

Signature:

```text
function list_openai_docs(limit?: number, cursor?: string);
```

Input schema:

```json
{
  "type": "object",
  "properties": {
    "limit": {
      "type": "integer",
      "minimum": 1,
      "maximum": 50
    },
    "cursor": {
      "type": "string"
    }
  },
  "$schema": "http://json-schema.org/draft-07/schema#"
}
```

## `fetch_openai_doc`

Description:

```text
Fetch the markdown for a specific doc page from `developers.openai.com`, `platform.openai.com`, or
`learn.chatgpt.com` so you can quote or summarize exact, up-to-date guidance (schemas, examples,
limits, and edge cases). Prefer to **`search_openai_docs` first** (or `list_openai_docs` if you’re
browsing) to find the best URL, then `fetch_openai_doc` to pull the exact text; you can pass
`anchor` (for example, `#streaming`) to fetch just that section.
```

Signature:

```text
function fetch_openai_doc(url: string, anchor?: string);
```

Input schema:

```json
{
  "type": "object",
  "properties": {
    "url": {
      "type": "string",
      "minLength": 1
    },
    "anchor": {
      "type": "string"
    }
  },
  "required": [
    "url"
  ],
  "$schema": "http://json-schema.org/draft-07/schema#"
}
```

## `list_api_endpoints`

Description:

```text
List all OpenAI API endpoint URLs available in the OpenAPI spec.
```

Signature:

```text
function list_api_endpoints();
```

Input schema:

```json
{
  "type": "object",
  "properties": {},
  "$schema": "http://json-schema.org/draft-07/schema#"
}
```

## `get_openapi_spec`

Description:

```text
Return the OpenAPI spec for a specific API endpoint URL. Optionally filter code samples by language,
or return only code samples.
```

Signature:

```text
function get_openapi_spec(url: string, languages?: string[], codeExamplesOnly?: boolean);
```

Input schema:

```json
{
  "type": "object",
  "properties": {
    "url": {
      "type": "string",
      "minLength": 1
    },
    "languages": {
      "type": "array",
      "items": {
        "type": "string",
        "minLength": 1
      }
    },
    "codeExamplesOnly": {
      "type": "boolean"
    }
  },
  "required": [
    "url"
  ],
  "$schema": "http://json-schema.org/draft-07/schema#"
}
```
