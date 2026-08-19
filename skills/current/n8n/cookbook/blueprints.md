# n8n Blueprint Cookbook

NL → workflow JSON → apply → enable MCP → discover live catalog → run discovered tool.

## NL to JSON to MCP Run

Plain-English request → runnable MCP workflow:

```bash
# 1) Export or create a JSON blueprint (by hand or with agent help)
# Save as <WORKFLOW.json>

# 2) Create or update
uv run --script <skill-dir>/scripts/cli.py create <WORKFLOW.json>
# or
uv run --script <skill-dir>/scripts/cli.py update <WORKFLOW_ID> <WORKFLOW.json>

# 3) Enable MCP + activate
uv run --script <skill-dir>/scripts/cli.py mcp-enable <WORKFLOW_ID>
uv run --script <skill-dir>/scripts/cli.py activate <WORKFLOW_ID>

# 4) Confirm MCP health without printing transport details
mcporter list n8n --status --quiet --no-oauth

# 5) Discover compact names, then inspect only the selected tool
mcporter list n8n --brief
mcporter list n8n.<DISCOVERED_TOOL> --schema --all-parameters

# 6) Call only the inspected tool
mcporter call n8n.<DISCOVERED_TOOL> --args '<JSON_MATCHING_DISCOVERED_SCHEMA>'
```

Before step 4, MUST read `../references/mcporter.md`. Workflow enablement MUST NOT imply any tool name or schema.

## Safe Iteration Loop

Update a workflow without breaking MCP access:

```bash
uv run --script <skill-dir>/scripts/cli.py export <WORKFLOW_ID> <WORKFLOW.json>
# edit <WORKFLOW.json>
uv run --script <skill-dir>/scripts/cli.py update <WORKFLOW_ID> <WORKFLOW.json>
uv run --script <skill-dir>/scripts/cli.py mcp-enable <WORKFLOW_ID>
uv run --script <skill-dir>/scripts/cli.py activate <WORKFLOW_ID>
```

After major edits, MUST re-apply `mcp-enable` to preserve `availableInMCP`.
