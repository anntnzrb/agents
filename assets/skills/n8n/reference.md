# n8n Reference

This reference covers the bundled REST route. For the optional MCP route, read
`references/mcporter.md`; its credentials, transport, and live schemas are
independent of the REST API.

## Bundled REST CLI

The CLI calls the n8n REST API at `<N8N_BASE_URL>/api/v1` with `X-N8N-API-KEY`.

Required environment:

- `N8N_BASE_URL`
- `N8N_API_KEY`

The CLI loads `N8N_ENV_FILE`, then its skill-local `.env`, then the nearest ancestor `skills/n8n/.env`. It reports a missing required variable before making a request.

Use the bundled CLI rather than raw HTTP:

```text
uv run --script <skill-dir>/scripts/cli.py list --limit 5
uv run --script <skill-dir>/scripts/cli.py get <WORKFLOW_ID>
uv run --script <skill-dir>/scripts/cli.py export <WORKFLOW_ID> <OUT.json>
uv run --script <skill-dir>/scripts/cli.py validate <WORKFLOW.json>
```

MUST NOT infer MCP availability from REST success; routes have independent URLs,
credentials, transports, and discovery.
