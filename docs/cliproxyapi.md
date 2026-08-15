# Operate CLIProxyAPI

Use this guide to change gateway credentials, authenticate ChatGPT, refresh models, run the gateway, and verify access. For field definitions and discovery rules, see the [CLIProxyAPI reference](cliproxyapi-reference.md).

## Configure local secrets

Create the ignored secrets file if it does not exist:

```bash
cp secrets.local.example.json secrets.local.json
chmod 600 secrets.local.json
$EDITOR secrets.local.json
```

Set a non-empty management key, one or more unique client keys, and every credential pool referenced by `assets/cliproxyapi.yaml.tmpl`.

Generate local management and client keys with:

```bash
openssl rand -hex 32
```

Never commit `secrets.local.json` or files under `~/.cli-proxy-api/`.

## Add an API-key account

Append an account to the matching array in `CLIPROXY_CREDENTIAL_POOLS`:

```json
{
	"CLIPROXY_CREDENTIAL_POOLS": {
		"openrouter": [
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

Start CLIProxyAPI in the foreground:

```bash
cli-proxy-api
```

The managed wrapper supplies `--config ~/.cli-proxy-api/config.yaml`. Use a process manager when the gateway must survive logout or reboot. This repository does not install a service.

## Open the control panel

Open this local URL:

```text
http://127.0.0.1:8317/management.html
```

Authenticate with `CLIPROXY_MANAGEMENT_KEY`.

Do not make durable configuration changes in the control panel. Sync replaces the generated configuration from `assets/cliproxyapi.yaml.tmpl` and `secrets.local.json`.

## Verify model access

Query the gateway with the first configured client key:

```bash
CLIPROXY_KEY="$(jq -r '.CLIPROXY_CLIENT_API_KEYS[0]' secrets.local.json)"
curl -fsS http://127.0.0.1:8317/v1/models \
	-H "Authorization: Bearer $CLIPROXY_KEY" | \
	jq -r '.data[].id'
unset CLIPROXY_KEY
```

The command prints the currently available model IDs. The list changes with provider catalogs and OAuth accounts.

To verify that the response contains at least one model, use:

```bash
CLIPROXY_KEY="$(jq -r '.CLIPROXY_CLIENT_API_KEYS[0]' secrets.local.json)"
curl -fsS http://127.0.0.1:8317/v1/models \
	-H "Authorization: Bearer $CLIPROXY_KEY" | \
	jq -e '.data | type == "array" and length > 0'
unset CLIPROXY_KEY
```

`jq` prints `true` on success.

## Refresh stale catalogs

Force every catalog request after an account or provider change:

```bash
bun ./sync/src/cli.ts sync --refresh-models
```

The forced refresh bypasses freshness windows and rejects stale fallback data. Use a normal sync for routine launches so a transient provider failure can fall back to a valid cache.

## Deploy on a home server

Bind the gateway only to a trusted private interface. For a Tailscale deployment, use the server's tailnet address and keep remote management disabled.

Reach the local management endpoint through a Tailscale SSH port forward. Do not expose the gateway through the public internet, Tailscale Funnel, or an untrusted LAN.

Back up `secrets.local.json` through an encrypted channel. Reauthenticate OAuth accounts after recovery instead of backing up active refresh tokens.
