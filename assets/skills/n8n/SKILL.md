---
name: n8n
description: Inspect and operate n8n workflows through its bundled REST CLI or targeted MCP tools.
license: GPL-3.0-or-later
metadata:
  author: anntnzrb
allowed-tools: ""
---

# n8n

Choose one explicit route. Do not start either route automatically.

- **Bundled REST CLI:** authoring and administration through the n8n REST API.
- **Optional MCPorter route:** discover and call tools from a configured n8n MCP endpoint.

## Bundled REST CLI

Use the bundled CLI for listing, reading, creating, updating, exporting, activating, deactivating, and validating workflows:

```text
uv run --script <skill-dir>/scripts/cli.py list --limit 5
uv run --script <skill-dir>/scripts/cli.py get <WORKFLOW_ID>
uv run --script <skill-dir>/scripts/cli.py create <WORKFLOW.json>
uv run --script <skill-dir>/scripts/cli.py update <WORKFLOW_ID> <WORKFLOW.json>
uv run --script <skill-dir>/scripts/cli.py activate <WORKFLOW_ID>
uv run --script <skill-dir>/scripts/cli.py deactivate <WORKFLOW_ID>
uv run --script <skill-dir>/scripts/cli.py export <WORKFLOW_ID> <OUT.json>
uv run --script <skill-dir>/scripts/cli.py mcp-enable <WORKFLOW_ID>
uv run --script <skill-dir>/scripts/cli.py validate <WORKFLOW.json>
```

MCP-exposed workflows must also be active.

It requires `N8N_BASE_URL` and `N8N_API_KEY`. Read `reference.md` before REST work or credential troubleshooting; it defines the CLI's environment-file lookup.

## Optional MCPorter route

Use MCPorter only when `N8N_MCP_URL` and `N8N_MCP_TOKEN` are configured in the selected registry:

If `mcporter` is not on `PATH`, replace the leading `mcporter` in each command below with `nix run github:numtide/llm-agents.nix#mcporter --`.

```text
mcporter list n8n --brief
mcporter list n8n.<tool> --schema
mcporter call n8n.<tool> --args '<JSON object>'
```

Read `assets/mcporter.jsonc` before this route. Missing substitutions, authentication failures, and an unavailable endpoint are prerequisites to report; do not fabricate configuration or silently change routes.

## Required follow-up reads

| Need | Read | When |
|---|---|---|
| REST auth, endpoints, and environment lookup | `reference.md` | Before REST work |
| MCP transport and substitutions | `assets/mcporter.jsonc` | Before MCPorter work |
| MCP tool arguments/output | `mcporter list n8n.<tool> --schema` | After selecting a tool |
