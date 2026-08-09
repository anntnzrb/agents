# n8n MCPorter Reference

MUST read before using optional MCPorter `n8n`.

## What Is Knowable

The registry proves configuration only, not reachability, auth, or tools.

Live `list n8n --schema --all-parameters` is the sole authority for:

- current tool names;
- required and optional arguments;
- argument types and accepted values;
- tool descriptions;
- output fields only when the tool publishes an output schema

Catalogs are instance-, endpoint-, and workflow-dependent. MUST rediscover after
workflow/endpoint changes; MUST NOT preserve a catalog as timeless.

## Transport and Authentication Prerequisites

`<agent-config-root>/assets/mcporter.jsonc` starts `bun x supergateway`, bridges
stdio to `N8N_MCP_URL`, and sends `N8N_MCP_TOKEN` as a bearer token.

Before discovery:

- MUST confirm nonempty variable presence without printing values
- MUST confirm the URL is the intended reachable MCP endpoint, not REST
- MUST confirm `bun` availability and token validity

MUST NOT run `mcporter config get n8n`, print env values, or report resolved
arguments: the registry substitutes the bearer into a subprocess argument.

## Secret-Safe Health Gate

MUST run this quiet exit-code gate:

```text
mcporter --config <agent-config-root>/assets/mcporter.jsonc list n8n --status --quiet --no-oauth
```

If `mcporter` is unavailable on `PATH`, use:

```text
nix run github:numtide/llm-agents.nix#mcporter -- --config <agent-config-root>/assets/mcporter.jsonc list n8n --status --quiet --no-oauth
```

Zero permits discovery. Nonzero MUST stop; it does not classify missing env,
transport, downtime, or auth rejection.

MUST NOT capture `--status --json` or raw transport diagnostics: the observed
MCPorter/supergateway pair can expose the bearer token.

## Live Discovery and Calls

After gate success, MUST discover the complete live schema:

```text
mcporter --config <agent-config-root>/assets/mcporter.jsonc list n8n --schema --all-parameters
```

Discovery output is sensitive. MUST extract only needed names/schemas; MUST NOT
paste raw output into chat, issues, logs, or docs.

MUST call only a returned tool with its exact input schema:

```text
mcporter --config <agent-config-root>/assets/mcporter.jsonc call n8n.<DISCOVERED_TOOL> --args '<JSON_MATCHING_DISCOVERED_SCHEMA>'
```

Input schema MUST NOT imply output schema. Without one, response fields are
knowable only from a live call and MUST be labeled observed, not stable. Offline
means current inputs and outputs are unknown.

Before mutation, MUST show action/payload and confirm scope; SHOULD prefer an
exposed read tool. On schema errors or endpoint/auth changes, MUST rediscover;
MUST NOT guess fields.

## Failure Classification

| Evidence | Conclusion | Next action |
|---|---|---|
| Variable absent | Local prerequisite missing | MUST request config; MUST NOT invent it |
| Nonzero quiet status | Unknown health failure | MUST check reachability/auth safely or ask |
| No discovered tools | No live catalog | MUST stop; MUST NOT invent tools/fields |
| No output schema | No contractual response fields | MAY observe a call or MUST report the limit |
| Tool/schema changed | Live state changed | MUST rebuild from discovery |
| REST works; MCP fails | Independent route failure | MUST NOT claim MCP or switch silently |

## Captured Probe State

Snapshot only; MUST refresh before use.

- Date: 2026-07-16 (America/Guayaquil)
- MCPorter version: 0.12.3 from
  `github:numtide/llm-agents.nix#mcporter`.
- Registry: SSOT `assets/mcporter.jsonc`, `n8n` stdio-to-streamable-HTTP bridge
- Probe environment: `N8N_MCP_URL` and `N8N_MCP_TOKEN` were unset
- `list n8n --schema` result: tools unavailable; the bridge had no HTTP target
  and closed the MCP connection.
- Quiet status result: unhealthy (exit 1)
- Captured tool names, input schemas, or output schemas: none

The non-quiet schema command exited zero while tools were unavailable; MUST use
the quiet status gate for health.
