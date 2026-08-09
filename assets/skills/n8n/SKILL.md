---
name: n8n
description: Inspect and operate n8n workflows through its bundled REST CLI or targeted MCP tools.
license: GPL-3.0-or-later
metadata:
  author: anntnzrb

---

# n8n

Choose one route. NEVER start either automatically.

- **Bundled REST CLI:** author and administer through n8n REST
- **Optional MCPorter:** discover current endpoint tools and schemas

The MCP catalog is instance state.

- NEVER infer tools, arguments, or response fields
- Live discovery MUST define tools and input schemas
- Only published output schemas are contractual
- Observed calls MUST remain samples, not contracts

## Bundled REST CLI

REST workflow operations SHOULD use the bundled CLI:

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

MCP-exposed workflows MUST also be active.

- REST requires `N8N_BASE_URL` and `N8N_API_KEY`
- MUST read `reference.md` before REST work or credential troubleshooting

## Optional MCPorter route

- MUST read `references/mcporter.md` first
- MUST use the configured registry explicitly
- Missing `mcporter`: MUST use the Nix fallback
- MUST run the quiet health gate first
- Nonzero status MUST stop discovery

```text
mcporter --config <agent-config-root>/assets/mcporter.jsonc list n8n --status --quiet --no-oauth
```

After success:

- MUST discover live schemas
- MUST call only a discovered tool

```text
mcporter --config <agent-config-root>/assets/mcporter.jsonc list n8n --schema --all-parameters
mcporter --config <agent-config-root>/assets/mcporter.jsonc call n8n.<DISCOVERED_TOOL> --args '<JSON_MATCHING_DISCOVERED_SCHEMA>'
```

- MUST copy exact live tool/input schemas
- MUST copy only published output schemas
- Unavailable catalog: MUST report unobserved response shape
- NEVER invent tools or silently switch to REST

## Required follow-up reads

| Need | Read | When |
|---|---|---|
| REST auth, endpoints, and environment lookup | `reference.md` | Before REST work |
| MCP prerequisites, safe status, discovery, and failures | `references/mcporter.md` | MUST read before MCPorter work |
| MCP transport definition | `<agent-config-root>/assets/mcporter.jsonc` | Diagnose transport; MUST NOT print resolved secrets |
| Workflow authoring recipes | `cookbook/basics.md` | When a REST or MCP task matches |
| End-to-end authoring sequence | `cookbook/blueprints.md` | When creating or iterating a workflow |
