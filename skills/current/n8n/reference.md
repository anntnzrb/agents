# n8n Reference

Bundled REST route only. Optional MCP route → `references/mcporter.md`; MCP credentials, transport, and live schemas independent of REST API.

## Bundled REST CLI

REST endpoint: `<N8N_BASE_URL>/api/v1`; auth header: `X-N8N-API-KEY`.
REST API commands require `N8N_BASE_URL`, `N8N_API_KEY`. `validate` is offline and does not require them.
Credential precedence: `--base-url` and `--api-key` flags win over process environment; process environment wins over env files. If either required variable is missing, the first readable env file wins in this order: `N8N_ENV_FILE`, then `$SKILLS_DIR/n8n/.env` when `SKILLS_DIR` is set, then `<cwd-or-ancestor>/skills/n8n/.env` scanning from the current directory upward. A file fills only variables missing from the process environment. Missing required variables are reported before any request.

MUST use bundled CLI, not raw HTTP:

```text
uv run --script <skill-dir>/scripts/cli.py list --limit 5
uv run --script <skill-dir>/scripts/cli.py get <WORKFLOW_ID>
uv run --script <skill-dir>/scripts/cli.py export <WORKFLOW_ID> <OUT.json>
uv run --script <skill-dir>/scripts/cli.py validate <WORKFLOW.json>
```

MUST NOT infer MCP availability from REST success; routes have independent URLs, credentials, transports, and discovery.
