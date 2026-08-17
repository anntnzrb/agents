# Operate CLIProxyAPI

Use this guide to change gateway credentials, authenticate ChatGPT, run the gateway, and check model access. See the [CLIProxyAPI reference](cliproxyapi-reference.md) for field definitions, catalog rules, and routing settings.

## Set the deployment

Keep the gateway host and endpoint values in `assets/cliproxyapi/deployment.json`:

| Field | Set it to |
| --- | --- |
| `server.hostname` | The host that runs CLIProxyAPI |
| `listen.host` | The interface address that CLIProxyAPI binds |
| `listen.port` | The listener port |
| `client.baseUrl` | The client-facing `/v1` endpoint |

Do not copy these values into harness sources or documentation.

To move the gateway, update `deployment.json`, start CLIProxyAPI on the new host, and run sync on the clients. A client keeps its existing generated configuration and harness endpoints until the new `/models` endpoint returns a non-empty `data` array.

## Configure local secrets

Create the ignored secrets file if it does not exist:

```bash
cp secrets.local.example.json secrets.local.json
chmod 600 secrets.local.json
$EDITOR secrets.local.json
```

Set every credential pool referenced by `assets/cliproxyapi/config.yaml.tmpl`. The gateway accepts requests without a client key. Keep the listener on a trusted private interface.

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

Use the same weight for accounts with equal priority. Add `proxyUrl` only when an account requires a proxy.

For ClinePass, create a long-lived API key in **Settings > API Keys** at [app.cline.bot](https://app.cline.bot). Add the key to the `cline-pass` pool. Do not use an OAuth token from the Cline extension or CLI. CLIProxyAPI credential pools require stable API keys.

Apply the change:

```bash
bun ./sync/src/cli.ts sync --refresh-models
```

If the gateway is not running, run a normal sync first. Start the gateway, then run the forced refresh.

## Authenticate ChatGPT

On macOS, use browser OAuth:

```bash
cli-proxy-api --codex-login
```

On a headless Linux host, use device OAuth:

```bash
cli-proxy-api --codex-device-login
```

Restrict the generated OAuth files:

```bash
chmod 600 ~/.cli-proxy-api/codex-*.json
```

Do not run two gateways with the same active refresh token. Stop the old gateway before you move OAuth state. Reauthenticate on the new host instead of copying an active token.

After authentication, refresh the model catalog:

```bash
bun ./sync/src/cli.ts sync --refresh-models
```

## Start the gateway

On the configured gateway host, start CLIProxyAPI in the foreground:

```bash
cli-proxy-api
```

The managed wrapper supplies `--config ~/.cli-proxy-api/config.yaml`. Sync reads the listener and client endpoint from `assets/cliproxyapi/deployment.json`. Use a process manager when the gateway must survive logout or reboot.

## Open the control panel

Open `http://<listen-host>:<listen-port>/management.html` with the values from `assets/cliproxyapi/deployment.json`.

The panel uses `remote-management.secret-key` from `assets/cliproxyapi/config.yaml.tmpl`. Treat that value as a credential. Do not expose the panel through the public internet, Tailscale Funnel, or an untrusted LAN.

Do not make durable configuration changes in the control panel. Sync replaces the generated configuration from `assets/cliproxyapi/config.yaml.tmpl` and `secrets.local.json`.

## Rebuild the control-panel asset

The repository pins a management-panel revision and applies `assets/cliproxyapi/panel.patch`. Rebuild the asset after adopting a new upstream revision:

```bash
sh assets/cliproxyapi/panel.rebuild.sh
```

The script runs from any directory and requires `git` and `bun` on `PATH`. It writes `assets/cliproxyapi/panel.html`.

## Scope models by origin

The template enables `force-model-prefix`. Accounts with a prefix expose model IDs in `<prefix>/<alias>` form. See the [model prefix table](cliproxyapi-reference.md#model-prefixes).

API-key pools get prefixes from `x-model-sources` in the template. OAuth accounts get prefixes from the top-level `prefix` field in their auth files under `~/.cli-proxy-api/`. Reauthentication recreates an auth file and drops its prefix.

To restore the ChatGPT prefix after reauthentication:

```bash
set -eu
for f in ~/.cli-proxy-api/codex-*.json; do
	[ -f "$f" ] || continue
	tmp="$f.tmp"
	jq '.prefix = "chatgpt"' "$f" > "$tmp"
	chmod 600 "$tmp"
	mv "$tmp" "$f"
done
```

Restart the running gateway process after you edit the auth files. Then refresh the model catalog:

```bash
bun ./sync/src/cli.ts sync --refresh-models
```

Sessions and configurations that reference an old unprefixed ID stop working after its prefix appears. Select the prefixed model again.

## Verify model access

Query the gateway without a client key:

```bash
base_url="$(jq -r '.client.baseUrl' assets/cliproxyapi/deployment.json)"
curl -fsS "$base_url/models" | \
	jq -e '.data | type == "array" and length > 0'
unset base_url
```

`jq` prints `true` when the response contains at least one model. Model IDs depend on the current provider catalogs and authenticated OAuth accounts.

## Refresh model catalogs

Force every catalog request after an account or provider change:

```bash
bun ./sync/src/cli.ts sync --refresh-models
```

The forced refresh bypasses freshness windows and rejects stale fallback data. Use a normal sync for routine launches so a transient provider failure can use a valid cache.

## Deploy on a home server

Bind the gateway to a trusted private interface. For a Tailscale deployment, use the server's tailnet address.

Back up `secrets.local.json` through an encrypted channel. Reauthenticate OAuth accounts after recovery instead of backing up active refresh tokens.
