# Operate CLIProxyAPI

Use this guide to change gateway credentials, authenticate ChatGPT, refresh models, run the gateway, and verify access. For field definitions and discovery rules, see the [CLIProxyAPI reference](cliproxyapi-reference.md).

## Select the deployment

Keep the gateway host and endpoint values in `assets/cliproxyapi/deployment.json`. Set `server.hostname` to the host that runs CLIProxyAPI. Set `listen.host` and `listen.port` to the listener on that host. Set `client.baseUrl` to the `/v1` endpoint that clients use. Do not copy these values into harness sources or documentation.

When you move the gateway, update that file, start the new gateway, and run sync on clients. A client keeps its existing generated configuration and endpoints until the new endpoint passes the `/models` readiness check.

## Configure local secrets

Create the ignored secrets file if it does not exist:

```bash
cp secrets.local.example.json secrets.local.json
chmod 600 secrets.local.json
$EDITOR secrets.local.json
```

Set every credential pool referenced by `assets/cliproxyapi/config.yaml.tmpl`. The gateway accepts client requests without client keys; the tailnet is the access boundary. Upstream API keys come from the provider accounts themselves.

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

For ClinePass, create a long-lived API key in **Settings > API Keys** at [app.cline.bot](https://app.cline.bot). Add the key to the `cline-pass` pool. Do not use an account OAuth token from the Cline extension or CLI. OAuth tokens expire and rotate, but CLIProxyAPI credential pools require stable API keys.

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

The managed wrapper supplies `--config ~/.cli-proxy-api/config.yaml`. Sync reads the listener and client endpoint from `assets/cliproxyapi/deployment.json`. Use a process manager when the gateway must survive logout or reboot.

## Open the control panel

Open the control panel at the configured gateway listener:

```text
http://munich.trex-gamut.ts.net:8317/management.html
```

The panel accepts the static management token committed in `assets/cliproxyapi/config.yaml.tmpl`. It is not a credential: the tailnet is the access boundary.

Do not make durable configuration changes in the control panel. Sync replaces the generated configuration from `assets/cliproxyapi/config.yaml.tmpl` and `secrets.local.json`.

## Control panel asset

The panel itself is a single HTML file. The default upstream panel cannot show OpenCode Go quota, so this repository pins a patched build. The gateway host syncs the asset from `assets/cliproxyapi/panel.html` to `~/.cli-proxy-api/static/management.html`; clients do not receive it.

The patch is upstream PR `router-for-me/Cli-Proxy-API-Management-Center#381` ("feat(quota): add OpenCode Go usage support"). The exact diff is committed as `assets/cliproxyapi/panel.patch`. The panel queries `https://opencode.ai/zen/go/v1/usage` through the gateway's `/v0/management/api-call` proxy, so API keys never leave the gateway. `remote-management.disable-auto-update-panel` stays `true` so the gateway never replaces the pinned build.

Rebuild the asset after adopting a new upstream revision:

```bash
sh assets/cliproxyapi/panel.rebuild.sh
```

The script pins the upstream head commit. When upstream merges the PR into a release, replace the pinned build with the official asset and delete the panel job from `sync/src/core/plan.ts`.

## Scope models by origin

Every model the gateway serves carries an origin prefix. See the [prefix table](cliproxyapi-reference.md#model-sources) for the full mapping. `force-model-prefix` drops the unprefixed IDs, so each model request names its origin. A name like `gpt-5.6-sol` therefore appears only as `chatgpt/gpt-5.6-sol` or `zen/gpt-5.6-sol`.

API-key pools get prefixes from `x-model-sources` in the template. OAuth accounts get prefixes from the top-level `prefix` field in their auth files under `~/.cli-proxy-api/`. Re-authentication recreates an auth file and drops its prefix. Re-apply it afterwards:

```bash
for f in ~/.cli-proxy-api/codex-*.json; do
	jq '.prefix = "chatgpt"' "$f" > "$f.tmp" && mv "$f.tmp" "$f"
done
chmod 600 ~/.cli-proxy-api/codex-*.json
systemctl --user restart cliproxyapi
```

After a prefix change, refresh the shared catalog so clients pick up the new IDs:

```bash
bun ./sync/src/cli.ts sync --refresh-models
```

Sessions and configurations that reference an old unprefixed ID stop working after its prefix appears; reselect the model.

## Verify model access

The gateway accepts requests without client keys. Query it directly:

```bash
CLIPROXY_DEPLOYMENT=assets/cliproxyapi/deployment.json
CLIPROXY_BASE_URL="$(jq -r '.client.baseUrl' "$CLIPROXY_DEPLOYMENT")"
curl -fsS "$CLIPROXY_BASE_URL/models" | \
	jq -r '.data[].id'
unset CLIPROXY_BASE_URL
```

The command prints the currently available model IDs. The list changes with provider catalogs and OAuth accounts.

To verify that the response contains at least one model, use:

```bash
CLIPROXY_DEPLOYMENT=assets/cliproxyapi/deployment.json
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

Bind the gateway only to a trusted private interface. For a Tailscale deployment, use the server's tailnet address. The tailnet is the access boundary; the management panel uses the static token committed in the template.

Do not expose the gateway through the public internet, Tailscale Funnel, or an untrusted LAN.

Back up `secrets.local.json` through an encrypted channel. Reauthenticate OAuth accounts after recovery instead of backing up active refresh tokens.
