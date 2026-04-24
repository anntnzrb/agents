---
name: n8n
description: "n8n automation via REST API (authoring) and MCP (runtime). Use REST for workflow CRUD; use MCP for listing/triggering enabled workflows."
---

# n8n

Use **REST API** to create/update/activate workflows. Use **MCP** to list and run enabled workflows.

## When to use

- Authoring (no UI): REST API
- Running/triggering workflows: MCP
- Use `scripts/cli.py` for REST without curl/jq

Auth/config check policy: do not stop at `echo $N8N_BASE_URL` or `echo $N8N_API_KEY` in the parent shell. If credentials may live in the skill-local `.env`, prefer `uv run --script <skill-dir>/scripts/cli.py ...`; that entrypoint auto-loads the env file using the lookup order below. Only report missing credentials after the real command path fails.

## Entry point

Cross-platform:

```text
uv run --script <skill-dir>/scripts/cli.py ...
```

Set `<skill-dir>` to this skill directory. Do not rely on shell sourcing, executable bits, or shebang dispatch.

## Preconditions

- n8n instance URL (cloud, self-hosted, or local)
- REST API key (X-N8N-API-KEY)
- MCP URL + access token (instance-level MCP)
- Workflows marked `availableInMCP`

## Node discovery (tested)

- Exa: built-in node library docs (`https://docs.n8n.io/integrations/builtin/node-types/`)
- Context7: `/n8n-io/n8n-docs` for node docs + examples
- DeepWiki: repo Q&A over `n8n-io/n8n-docs`; pair with `gh` or workflow export to confirm `type` strings
- `gh`: list node folders, then search by keyword and open the `*.node.json` file to read the `node` field
- Export workflows to confirm exact `type` strings in your instance

## Quick start (REST)

If credentials live only in the skill-local `.env`, prefer `uv run --script <skill-dir>/scripts/cli.py ...` from the Scripts section; the raw `curl` examples below assume the relevant env is already exported into the current process.

```bash
# list workflows
curl -sS -H "X-N8N-API-KEY: <N8N_API_KEY>" \
  "<N8N_BASE_URL>/api/v1/workflows?active=true"

# create workflow (body from template)
curl -sS -X POST -H "X-N8N-API-KEY: <N8N_API_KEY>" \
  -H "Content-Type: application/json" \
  -d @workflow.json \
  "<N8N_BASE_URL>/api/v1/workflows"
```

## MCP (runtime)

Use the MCP URL for your instance (example: `N8N_MCP_URL`).

```bash
# stdio proxy for MCP clients that need headers
bun x supergateway --streamableHttp "<N8N_MCP_URL>" \
  --header "Authorization: Bearer <N8N_MCP_TOKEN>"
```

## Environment

- Tracked template: `.env.example`
- Common vars:
  - `N8N_BASE_URL`
  - `N8N_API_KEY`
  - `N8N_MCP_URL`
  - `N8N_MCP_TOKEN`
- `scripts/cli.py` dispatches to `n8nctl.py`, which auto-loads from:
  - `N8N_ENV_FILE`
  - `$SKILLS_DIR/n8n/.env`
  - nearest ancestor `skills/n8n/.env`
- Raw `curl` / `supergateway` commands still read process env only; source `.env` yourself or use direnv.

## Notes

- Workflows include a trigger node for MCP execution
- Keep `--header "Authorization: Bearer <...>"` as a single, quoted argument
- `n8nctl` uses REST endpoints and requires `N8N_BASE_URL` + `N8N_API_KEY`
- Replace `<N8N_CONTAINER>` with your Docker container name

## CLI (self-hosted)

For Docker installs, run inside the container:

```bash
docker exec -it "<N8N_CONTAINER>" n8n export:workflow --all
docker exec -it "<N8N_CONTAINER>" n8n import:workflow --input=/path/to/workflow.json
```

## Scripts

Minimal REST CLI (no curl):

```bash
uv run --script <skill-dir>/scripts/cli.py list --limit 5
uv run --script <skill-dir>/scripts/cli.py get <WORKFLOW_ID>
uv run --script <skill-dir>/scripts/cli.py create <WORKFLOW.json>
uv run --script <skill-dir>/scripts/cli.py update <WORKFLOW_ID> <WORKFLOW.json>
uv run --script <skill-dir>/scripts/cli.py activate <WORKFLOW_ID>
uv run --script <skill-dir>/scripts/cli.py mcp-enable <WORKFLOW_ID>
uv run --script <skill-dir>/scripts/cli.py validate <WORKFLOW.json>
```

## Query templates

See `assets/query-templates.json`.

## Reference

See `reference.md`.

## Cookbook

See `cookbook/basics.md` and `cookbook/blueprints.md`.
