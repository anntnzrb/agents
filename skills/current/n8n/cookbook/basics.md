# n8n Cookbook

Practical recipes for authoring workflows via REST and running them via MCP.

---

## List Workflows

**Problem**: See what workflows exist.

**Solution**:

```bash
uv run --script <skill-dir>/scripts/cli.py list --limit 10
```

**Tip**: Add `--active true` to see only active workflows.

---

## Enable MCP for a Workflow

**Problem**: Expose a workflow so MCP can list/execute it.

**Solution**:

```bash
uv run --script <skill-dir>/scripts/cli.py mcp-enable <WORKFLOW_ID>
uv run --script <skill-dir>/scripts/cli.py activate <WORKFLOW_ID>
```

**Tip**: MCP lists workflows that are active and marked `availableInMCP`.

---

## Run a Workflow via MCP

**Problem**: Execute a workflow exposed by the current n8n MCP endpoint.

**Solution**:

```text
mcporter list n8n --status --quiet --no-oauth
mcporter list n8n --brief
mcporter list n8n.<DISCOVERED_TOOL> --schema --all-parameters
mcporter call n8n.<DISCOVERED_TOOL> --args '<JSON_MATCHING_DISCOVERED_SCHEMA>'
```

**Tip**: MUST read `../references/mcporter.md` first and use only live tool names
and schemas.

---

## Export Workflow JSON

**Problem**: Capture a workflow definition to edit or version-control.

**Solution**:

```bash
uv run --script <skill-dir>/scripts/cli.py export <WORKFLOW_ID> <OUT.json>
```

**Tip**: Edit JSON, then apply with `uv run --script <skill-dir>/scripts/cli.py update`.

---

## Find Node Type Identifiers

**Problem**: Get exact `type` strings (e.g., `n8n-nodes-base.httpRequest`).

**Solution (gh)**:

```bash
# list node folders
gh api repos/n8n-io/n8n/contents/packages/nodes-base/nodes \
  --jq '.[].name' | head

# search by keyword (example: openAi)
gh search code "openAi" --repo n8n-io/n8n --limit 20

# LangChain node type constants
gh api repos/n8n-io/n8n/contents/packages/workflow/src/constants.ts \
  --jq '.content' | base64 -d | rg "OPENAI"
```

**Solution (DeepWiki)**:
Use DeepWiki on `n8n-io/n8n-docs` to list OpenAI‑compatible LLM nodes and locate their doc paths.

**Tip**: After you find a file, fetch it with `gh api .../contents/... | base64 -d` to read the `node` field.
**Tip**: Confirm exact `type` strings with `gh` or workflow export.

---

## Validate a Workflow JSON

**Problem**: Check a workflow file for missing fields or bad references.

**Solution**:

```bash
uv run --script <skill-dir>/scripts/cli.py validate <WORKFLOW.json>
```

**Tip**: Validate, then apply `create` or `update`.
