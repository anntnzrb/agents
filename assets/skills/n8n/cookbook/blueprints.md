# n8n Blueprint Cookbook

End-to-end flow: natural language → workflow JSON → apply → enable MCP →
discover the live catalog → run a discovered tool.

---

## NL to JSON to MCP Run

**Problem**: Start from a plain-English request and end with a runnable MCP workflow.

**Solution**:

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
mcporter --config <agent-config-root>/assets/mcporter.jsonc list n8n --status --quiet --no-oauth

# 5) Discover the current tool names and schemas
mcporter --config <agent-config-root>/assets/mcporter.jsonc list n8n --schema --all-parameters

# 6) Call only a tool returned by discovery
mcporter --config <agent-config-root>/assets/mcporter.jsonc call n8n.<DISCOVERED_TOOL> --args '<JSON_MATCHING_DISCOVERED_SCHEMA>'
```

**Tip**: MUST read `../references/mcporter.md` before step 4. Workflow enablement
MUST NOT imply any tool name or schema.

---

## Safe Iteration Loop

**Problem**: Keep updating a workflow without breaking MCP access.

**Solution**:

```bash
uv run --script <skill-dir>/scripts/cli.py export <WORKFLOW_ID> <WORKFLOW.json>
# edit <WORKFLOW.json>
uv run --script <skill-dir>/scripts/cli.py update <WORKFLOW_ID> <WORKFLOW.json>
uv run --script <skill-dir>/scripts/cli.py mcp-enable <WORKFLOW_ID>
uv run --script <skill-dir>/scripts/cli.py activate <WORKFLOW_ID>
```

**Tip**: MUST re-apply `mcp-enable` after major edits to preserve `availableInMCP`.
