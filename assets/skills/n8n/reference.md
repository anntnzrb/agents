# n8n Reference

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

## Optional MCPorter route

The configured `n8n` MCPorter entry passes `N8N_MCP_URL` to `supergateway` and sends `N8N_MCP_TOKEN` as a bearer token. Both variables must be set.

```text
mcporter list n8n --brief
mcporter list n8n.<tool> --schema
mcporter call n8n.<tool> --args '<JSON object>'
```

Check `assets/mcporter.jsonc` for the selected registry's transport. Endpoint availability and exposed tools are instance-specific.
