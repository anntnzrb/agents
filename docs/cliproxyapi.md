# Operate CLIProxyAPI

Use this guide to change gateway credentials, authenticate ChatGPT, refresh models, run the gateway, and verify access. For field definitions and discovery rules, see the [CLIProxyAPI reference](cliproxyapi-reference.md).

## Select the deployment

Keep the gateway host and endpoint values in `assets/cliproxyapi.deployment.json`. Set `server.hostname` to the host that runs CLIProxyAPI. Set `listen.host` and `listen.port` to the listener on that host. Set `client.baseUrl` to the `/v1` endpoint that clients use. Do not copy these values into harness sources or documentation.

When you move the gateway, update that file, start the new gateway, and run sync on clients. A client keeps its existing generated configuration and endpoints until the new endpoint passes the `/models` readiness check.

## Configure local secrets

Create the ignored secrets file if it does not exist:

```bash
cp secrets.local.example.json secrets.local.json
chmod 600 secrets.local.json
$EDITOR secrets.local.json
```

Set a non-empty management key and every credential pool referenced by `assets/cliproxyapi.yaml.tmpl`. The gateway accepts client requests without client keys; the tailnet is the access boundary.

Generate the local management key with:

```bash
openssl rand -hex 32
```

Never commit `secrets.local.json` or files under `~/.cli-proxy-api/`.

## Add an API-key account

Append an account to the matching array in `CLIPROXY_CREDENTIAL_POOLS`:

```json
{
	"CLIPROXY_CREDENTIAL_POOLS": {
		"deepseek": [
			{
				"apiKey": "first-key",
				"weight": 1
			},
			{
				"apiKey": "second-key",
				"weight": 1
			}
		]
	}
}
```

Use the same weight for accounts with equal priority. Add `proxyUrl` only when that account requires a proxy.

Apply the change:

```bash
bun ./sync/src/cli.ts sync --refresh-models
```

If the gateway is not running, omit `--refresh-models` for the first sync. Start the gateway, then run the forced refresh.

## Authenticate ChatGPT

On macOS, use browser OAuth:

```bash
cli-proxy-api --codex-login
```

On a headless Linux host, use device OAuth:

```bash
cli-proxy-api --codex-device-login
```

Restrict the generated file:

```bash
chmod 600 ~/.cli-proxy-api/codex-*.json
```

Do not run two gateways with the same active refresh token. Before moving OAuth state, stop the old gateway. Reauthentication on the new host is safer than copying an active token.

After authentication, refresh the shared catalog:

```bash
bun ./sync/src/cli.ts sync --refresh-models
```

## Start the gateway

On the configured gateway host, start CLIProxyAPI in the foreground:

```bash
cli-proxy-api
```

The managed wrapper supplies `--config ~/.cli-proxy-api/config.yaml`. Sync reads the listener and client endpoint from `assets/cliproxyapi.deployment.json`. Use a process manager when the gateway must survive logout or reboot.

## Open the control panel

Open the control panel at the configured gateway listener:

```text
http://<listen-host>:<listen-port>/management.html
```

For the current deployment, use:

```text
http://munich.trex-gamut.ts.net:8317/management.html
```

Authenticate with `CLIPROXY_MANAGEMENT_KEY`. The page is reachable without authentication, but its management API requires the key.

Do not make durable configuration changes in the control panel. Sync replaces the generated configuration from `assets/cliproxyapi.yaml.tmpl` and `secrets.local.json`.

## Verify model access

The gateway accepts requests without client keys. Query it directly:

```bash
CLIPROXY_DEPLOYMENT=assets/cliproxyapi.deployment.json
CLIPROXY_BASE_URL="$(jq -r '.client.baseUrl' "$CLIPROXY_DEPLOYMENT")"
curl -fsS "$CLIPROXY_BASE_URL/models" | \
	jq -r '.data[].id'
unset CLIPROXY_BASE_URL
```

The command prints the currently available model IDs. The list changes with provider catalogs and OAuth accounts.

To verify that the response contains at least one model, use:

```bash
CLIPROXY_DEPLOYMENT=assets/cliproxyapi.deployment.json
CLIPROXY_BASE_URL="$(jq -r '.client.baseUrl' "$CLIPROXY_DEPLOYMENT")"
curl -fsS "$CLIPROXY_BASE_URL/models" | \
	jq -e '.data | type == "array" and length > 0'
unset CLIPROXY_BASE_URL
```

`jq` prints `true` on success.

## Refresh stale catalogs

Force every catalog request after an account or provider change:

```bash
bun ./sync/src/cli.ts sync --refresh-models
```

The forced refresh bypasses freshness windows and rejects stale fallback data. Use a normal sync for routine launches so a transient provider failure can fall back to a valid cache.

## Deploy on a home server

Bind the gateway only to a trusted private interface. For a Tailscale deployment, use the server's tailnet address. Remote management is enabled for tailnet clients and requires `CLIPROXY_MANAGEMENT_KEY`.

Do not expose the gateway through the public internet, Tailscale Funnel, or an untrusted LAN.

Back up `secrets.local.json` through an encrypted channel. Reauthenticate OAuth accounts after recovery instead of backing up active refresh tokens.
