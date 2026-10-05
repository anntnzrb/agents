# CLIProxyAPI

CLIProxyAPI provides OpenAI-compatible and Anthropic-compatible endpoints for harnesses. The gateway service itself is operated outside this repository.

`tools/cliproxyapi/deployment.json` defines the client-side configuration for sync:

```json
{
  "client": {
    "baseUrl": "http://solna.trex-gamut.ts.net:8317/v1"
  }
}
```

## Client endpoint publication and placeholders

Sync replaces endpoint placeholders in harness configuration files declared under `cliproxy_templates`:

- `${CLIPROXY_CLIENT_BASE_URL}` renders to `client.baseUrl` (for example, `http://solna.trex-gamut.ts.net:8317/v1`).
- `${CLIPROXY_CLIENT_ORIGIN}` renders to `client.baseUrl` without the trailing `/v1` path (for example, `http://solna.trex-gamut.ts.net:8317`), for clients that append `/v1` themselves.

## Readiness gating

Before publishing rendered endpoint templates to harness homes, sync probes `client.baseUrl/models` without authorization. The endpoint must respond with HTTP 2xx and a JSON body containing a non-empty `data` array:

```bash
CLIPROXY_BASE_URL="$(jq -r '.client.baseUrl' tools/cliproxyapi/deployment.json)"
curl -fsS "$CLIPROXY_BASE_URL/models" | jq -e '.data | type == "array" and length > 0'
unset CLIPROXY_BASE_URL
```

If the endpoint is unreachable or returns an empty model list, sync preserves existing client configuration and harness endpoint files without failing or overwriting them.
