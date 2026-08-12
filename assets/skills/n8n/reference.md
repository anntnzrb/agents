# n8n Reference

Bundled REST route only. Optional MCP route → `references/mcporter.md`; MCP credentials, transport, and live schemas independent of REST API.

## Bundled REST CLI

REST endpoint: `<N8N_BASE_URL>/api/v1`; auth header: `X-N8N-API-KEY`.
Required environment: `N8N_BASE_URL`, `N8N_API_KEY`.
Environment load order: `N8N_ENV_FILE` → skill-local `.env` → nearest ancestor `skills/n8n/.env`; missing required variable reported before request.

MUST use bundled CLI, not raw HTTP:

```text
uv run --script <skill-dir>/scripts/cli.py list --limit 5
uv run --script <skill-dir>/scripts/cli.py get <WORKFLOW_ID>
uv run --script <skill-dir>/scripts/cli.py export <WORKFLOW_ID> <OUT.json>
uv run --script <skill-dir>/scripts/cli.py validate <WORKFLOW.json>
```

MUST NOT infer MCP availability from REST success; routes have independent URLs, credentials, transports, and discovery.
