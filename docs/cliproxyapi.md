# Model gateway clients

Harnesses reach models through a CLIProxyAPI gateway that exposes OpenAI-compatible and Anthropic-compatible endpoints. The machine configuration deploys and operates the gateway; this repository configures only its clients.

`gateway.base_url` in `agents.toml` is the `/v1` endpoint clients use. Change it when the gateway moves.

## Placeholders

Sync replaces endpoint placeholders in the harness files declared under `cliproxy_templates` and in `tools/summarize/config.json`:

- `${CLIPROXY_CLIENT_BASE_URL}` renders to `gateway.base_url`.
- `${CLIPROXY_CLIENT_ORIGIN}` renders to the same URL without `/v1`, for clients that append the version path themselves.

Tools that run outside a sync launch read the installed copy at `~/.local/share/agents/agents.toml`.

## Readiness gating

Before publishing rendered templates, sync requests `gateway.base_url` + `/models` without authorization. The response must be HTTP 2xx with a non-empty `data` array. Otherwise sync keeps the previously generated harness files and does not fail the run.
