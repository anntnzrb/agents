---
name: n8n
description: "Use when n8n workflows must be inspected or operated through the bundled REST CLI or targeted MCP tools."
license: AGPL-3.0-or-later
metadata:
  author: anntnzrb

---

# n8n

Routes: choose one; NEVER start either automatically.
- Bundled REST CLI — author/administer through n8n REST.
- Optional MCPorter — discover current endpoint tools/schemas.

MCP catalog: instance state.
- NEVER infer tools, arguments, or response fields.
- Live discovery MUST define tools/input schemas.
- Only published output schemas contractual.
- Observed calls MUST remain samples, not contracts.

## Bundled REST CLI

REST workflow operations SHOULD use bundled CLI:

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
REST requires `N8N_BASE_URL` and `N8N_API_KEY`.
MUST read `reference.md` before REST work or credential troubleshooting.

## Optional MCPorter route

- MUST read `references/mcporter.md` first.
- MUST use configured registry explicitly.
- Missing `mcporter`: MUST use Nix fallback.
- MUST run quiet health gate first.
- Nonzero status MUST stop discovery.

```text
mcporter --config <agent-config-root>/assets/mcporter.jsonc list n8n --status --quiet --no-oauth
```

After success:
- MUST discover the compact live inventory, then inspect only each selected tool.
- MUST call only a discovered tool.

```text
mcporter --config <agent-config-root>/assets/mcporter.jsonc list n8n --brief
mcporter --config <agent-config-root>/assets/mcporter.jsonc list n8n.<DISCOVERED_TOOL> --schema --all-parameters
mcporter --config <agent-config-root>/assets/mcporter.jsonc call n8n.<DISCOVERED_TOOL> --args '<JSON_MATCHING_DISCOVERED_SCHEMA>'
```

- MUST copy exact live tool/input schemas.
- MUST copy only published output schemas.
- Unavailable catalog: MUST report unobserved response shape.
- NEVER invent tools or silently switch to REST.

## Required follow-up reads

- REST auth, endpoints, environment lookup → `reference.md`; before REST work.
- MCP prerequisites, safe status, discovery, failures → `references/mcporter.md`; MUST read before MCPorter work.
- MCP transport definition → `<agent-config-root>/assets/mcporter.jsonc`; diagnose transport; MUST NOT print resolved secrets.
- Workflow authoring recipes → `cookbook/basics.md`; when a REST or MCP task matches.
- End-to-end authoring sequence → `cookbook/blueprints.md`; when creating or iterating a workflow.
