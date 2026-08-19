# DeepWiki MCP tool schema snapshot

NEVER load this snapshot for ordinary known calls. Load it only after a call or
targeted-schema failure, or for broad comparison; live contracts MUST override it.

## Snapshot metadata

- Captured: 2026-07-17
- MCPorter: 0.12.3
- Server: `deepwiki` (`DeepWiki MCP`)
- Transport: HTTP
- Endpoint reported by MCPorter: `https://mcp.deepwiki.com/mcp`
- Inventory at capture: 3 tools; names/input schemas matched 3/3
- Refresh command:

```text
mcporter list deepwiki --schema --json
```

The command above captured this broad snapshot. Runtime calls SHOULD use the
focused skill's exact recipes directly. NEVER invent structured
response fields: all tools publish only the common string envelope below, not a
schema for the string's semantic content.

## Inventory

|Tool|Purpose|Required input|
|---|---|---|
|`read_wiki_structure`|List documentation topics for one GitHub repository|`repoName` string|
|`read_wiki_contents`|View documentation for one GitHub repository|`repoName` string|
|`ask_question`|Ask a context-grounded question about one or more GitHub repositories|`repoName` string or string array; `question` string|

## Common output envelope

All three tools publish this exact output schema:

```json
{
  "type": "object",
  "properties": {
    "result": {
      "type": "string"
    }
  },
  "required": [
    "result"
  ],
  "x-fastmcp-wrap-result": true
}
```

Only the `result` string wrapper is known. NEVER infer JSON fields or a stable
internal format without observing and labeling a live result.

## `read_wiki_structure`

Exact live description:

```text
Get a list of documentation topics for a GitHub repository.
Args:
repoName: GitHub repository in owner/repo format (e.g. "facebook/react")
```

Rendered declaration:

```text
function read_wiki_structure(repoName: string): object;
```

Exact input schema:

```json
{
  "type": "object",
  "properties": {
    "repoName": {
      "type": "string"
    }
  },
  "required": [
    "repoName"
  ]
}
```

Example:

```text
mcporter call deepwiki.read_wiki_structure repoName=facebook/react
```

## `read_wiki_contents`

Exact live description:

```text
View documentation about a GitHub repository.
Args:
repoName: GitHub repository in owner/repo format (e.g. "facebook/react")
```

Rendered declaration:

```text
function read_wiki_contents(repoName: string): object;
```

Exact input schema:

```json
{
  "type": "object",
  "properties": {
    "repoName": {
      "type": "string"
    }
  },
  "required": [
    "repoName"
  ]
}
```

Example:

```text
mcporter call deepwiki.read_wiki_contents repoName=facebook/react
```

`read_wiki_contents` may be large. SHOULD use structure or a narrow question
first unless full docs are required.

## `ask_question`

Exact live description:

```text
Ask any question about a GitHub repository and get an AI-powered, context-grounded response.
Args:
repoName: GitHub repository or list of repositories (max 10) in owner/repo format
question: The question to ask about the repository
```

Rendered declaration:

```text
function ask_question(repoName: unknown, question: string): object;
```

Exact input schema:

```json
{
  "type": "object",
  "properties": {
    "repoName": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "items": {
            "type": "string"
          },
          "type": "array"
        }
      ]
    },
    "question": {
      "type": "string"
    }
  },
  "required": [
    "repoName",
    "question"
  ]
}
```

Single-repository example:

```text
mcporter call deepwiki.ask_question repoName=facebook/react question='Where is concurrent rendering implemented?'
```

Multiple-repository example:

```text
mcporter call deepwiki.ask_question --args '{"repoName":["facebook/react","vuejs/core"],"question":"How do their reactivity models differ?"}'
```

The description limits repository lists to 10, but JSON Schema omits `maxItems`.
MUST respect the limit without claiming schema enforcement. MCPorter renders
`repoName` as `unknown` because `anyOf` accepts a string or string array.

## Drift recovery

- If a known call reports a missing tool, MAY inspect the brief inventory:

  ```text
  mcporter list deepwiki --brief
  ```

- MUST inspect the selected tool's live schema:

  ```text
  mcporter list deepwiki.ask_question --schema
  ```

- Managed `mcporter` supplies the generated registry.
- Live success MUST override this snapshot. On failure, MUST use only recorded
  tools/fields and report drift uncertainty.
