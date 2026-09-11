# CLIProxyAPI

CLIProxyAPI provides the OpenAI-compatible endpoint for harnesses that configure a `cliproxy` provider. `tools/cliproxyapi/deployment.json` is the only deployment-specific resource. It selects the gateway host, listener, and client endpoint.

Use the procedures to change credentials, authenticate ChatGPT, run the gateway, and check model access. Use the reference sections for field definitions and routing settings.

## Set the deployment

Keep the gateway host and endpoint values in `tools/cliproxyapi/deployment.json`. [Deployment file](#deployment-file) defines the field definitions. Do not copy these values into harness sources or documentation.

To move the gateway, update `deployment.json`, start CLIProxyAPI on the new host, and run sync on the clients. A client keeps its existing generated configuration and harness endpoints until the new `/models` endpoint returns a non-empty `data` array.

## Configure local secrets

Create the ignored secrets file if it does not exist:

```bash
cp secrets.local.example.json secrets.local.json
chmod 600 secrets.local.json
$EDITOR secrets.local.json
```

Set every credential pool referenced by `tools/cliproxyapi/config.yaml.tmpl`. [Local secrets](#local-secrets) defines the file shape. The gateway accepts requests without a client key. Keep the listener on a trusted private interface.

Never commit `secrets.local.json` or files under `~/.cli-proxy-api/`.

## Add an API-key account

Append an account to the matching array in `CLIPROXY_CREDENTIAL_POOLS`:

```json
{
	"CLIPROXY_CREDENTIAL_POOLS": {
		"cline-pass": [
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
uv run --project sync sync sync
```

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

## Start the gateway

On the configured gateway host, start CLIProxyAPI in the foreground:

```bash
cli-proxy-api
```

The managed wrapper supplies `--config ~/.cli-proxy-api/config.yaml`. Sync reads the listener and client endpoint from `tools/cliproxyapi/deployment.json`. Use a process manager when the gateway must survive logout or reboot.

## Open the control panel

Open `http://<listen-host>:<listen-port>/management.html` with the values from `tools/cliproxyapi/deployment.json`.

The panel uses `remote-management.secret-key` from `tools/cliproxyapi/config.yaml.tmpl`. Treat that value as a credential. Do not expose the panel through the public internet, Tailscale Funnel, or an untrusted LAN.

Do not make durable configuration changes in the control panel. Sync replaces the generated configuration from `tools/cliproxyapi/config.yaml.tmpl` and `secrets.local.json`.

## Rebuild the control-panel asset

The panel is upstream `main` plus a local quota-card framework (`tools/cliproxyapi/panel.patch`) and the card definitions in `tools/cliproxyapi/quota-cards.ts`. Rebuild after changing a card or adopting upstream changes:

```bash
sh tools/cliproxyapi/panel.rebuild.sh
```

The script clones upstream (ref `main`; export `PANEL_REF` to pin a tag, branch, or commit), applies the framework patch with a 3-way merge, copies `quota-cards.ts` into the build tree, and runs `bun install --frozen-lockfile && bun run build`. It writes `tools/cliproxyapi/panel.html` and requires `git` and `bun` on `PATH`.

`BASE` in the script records the commit the patch was generated against; it keeps the 3-way merge preimage available on shallow clones. When upstream drift overlaps the framework the apply fails with conflicts; rebase the patch against the new upstream `main` and update `BASE`.

## Quota cards

`tools/cliproxyapi/quota-cards.ts` defines the panel's custom quota cards. Each entry declares a title, how to match auth-file rows (and optionally an API-key compatibility base URL, which makes the panel synthesize rows for providers that `/auth-files` does not list), the upstream request, and a parser returning display windows:

```ts
{
  id: 'my-provider',
  title: 'My Provider',
  matchesBaseUrl: (baseUrl) => baseUrl.includes('my-provider.example'),
  matches: (file) => String(file.baseUrl ?? '').includes('my-provider.example'),
  request: () => ({
    method: 'GET',
    url: 'https://my-provider.example/v1/usage',
    header: { Authorization: 'Bearer $TOKEN$' },
  }),
  parse: (payload) => [{ id: '5h', label: '5 Hour', remainingPercent: 80, resetAtMs: null }],
}
```

The gateway substitutes the selected credential for `$TOKEN$` and routes the call through `/v0/management/api-call`. After editing cards:

```bash
sh tools/cliproxyapi/panel.rebuild.sh
uv run --project sync sync
```

Sync deploys the built asset to `~/.cli-proxy-api/static/management.html` on the gateway host.

## Model IDs

The template exposes upstream model names as-is. Aliases, forked model variants, and forced payload mappings are not used. Credentials without a `prefix` field share one pool per provider and expose upstream model names.

`force-model-prefix` remains `true`: a credential or compatibility profile that carries a `prefix` exposes its models as `<prefix>/<model>`, and requests without that prefix cannot use the prefixed credential.

## Verify model access

Query the gateway without a client key:

```bash
base_url="$(jq -r '.client.baseUrl' tools/cliproxyapi/deployment.json)"
curl -fsS "$base_url/models" | \
	jq -e '.data | type == "array" and length > 0'
unset base_url
```

`jq` prints `true` when the response contains at least one model. Model IDs depend on the current configured providers and authenticated OAuth accounts.

## Deploy on a home server

Bind the gateway to a trusted private interface. For a Tailscale deployment, use the server's tailnet address.

Back up `secrets.local.json` through an encrypted channel. Reauthenticate OAuth accounts after recovery instead of backing up active refresh tokens.

## Artifacts

| Artifact | Path |
| --- | --- |
| Portable configuration template | `tools/cliproxyapi/config.yaml.tmpl` |
| Deployment endpoints | `tools/cliproxyapi/deployment.json` |
| Release manifest | `tools/cliproxyapi/release.json` |
| Control-panel asset | `tools/cliproxyapi/panel.html` |
| Control-panel patch source | `tools/cliproxyapi/panel.patch` |
| Control-panel rebuild script | `tools/cliproxyapi/panel.rebuild.sh` |
| Quota-card definitions | `tools/cliproxyapi/quota-cards.ts` |
| Local secrets | `secrets.local.json` |
| Generated configuration | `~/.cli-proxy-api/config.yaml` |
| Deployed control panel | `~/.cli-proxy-api/static/management.html` |
| OAuth files | `~/.cli-proxy-api/*.json` |
| Managed command | `~/.local/bin/cli-proxy-api` |

The release manifest lists macOS ARM64 and Linux x86_64 archives. Sync verifies the selected release's SHA-256 checksum and extracts only the manifest's executable.

Sync prepares the managed binary and wrapper only on the gateway host. Client hosts remove a previously owned `cli-proxy-api` wrapper on their next sync.

## Deployment file

`tools/cliproxyapi/deployment.json` contains these fields:

| Field | Constraint | Meaning |
| --- | --- | --- |
| `server.hostname` | Local OS hostname | Host that runs the CLIProxyAPI gateway |
| `listen.host` | Specific host or interface address | Address that CLIProxyAPI binds |
| `listen.port` | Integer from 1 through 65,535 | Port that CLIProxyAPI binds |
| `client.baseUrl` | HTTP or HTTPS `/v1` URL without credentials, query, or fragment | Endpoint used by harnesses and readiness checks |

Sync rejects wildcard listeners, unspecified IPv6 addresses, unknown fields, malformed client URLs, raw query or fragment delimiters, and invalid ports. It renders the listener into `~/.cli-proxy-api/config.yaml` and replaces `${CLIPROXY_CLIENT_BASE_URL}` in configured harness targets.

Sync compares the local OS hostname with `server.hostname` to choose the host role:

- The gateway host writes the server configuration and deploys the control-panel asset.
- A client host checks `client.baseUrl/models` without authentication.
- An unavailable client endpoint preserves existing harness endpoint files.
- A ready client endpoint lets sync update harness endpoints without replacing the local server configuration.

Endpoint publication is transactional. Publication preserves Codex-owned hook and project trust tables in `~/.codex/config.toml`. To change the gateway host or endpoint values, use [Set the deployment](#set-the-deployment).

## Local secrets

`secrets.local.json` contains one top-level field:

| Field | Type | Meaning |
| --- | --- | --- |
| `CLIPROXY_CREDENTIAL_POOLS` | Non-empty object of account arrays | API-key accounts grouped by provider pool |

Each credential account accepts these fields:

| Field | Required | Constraint |
| --- | --- | --- |
| `apiKey` | Yes | Non-empty string, unique within its pool |
| `weight` | No | Integer from 1 through 1,000,000 |
| `proxyUrl` | No | Non-empty string passed to CLIProxyAPI as `proxy-url` |

Pool names start with a lowercase letter and contain lowercase letters, digits, or hyphens. Every pool must contain at least one account. The template must reference every pool in the secrets file.

The renderer rejects unknown account fields, duplicate keys within a pool, invalid weights, missing pools, and unreferenced pools.

## Generated files and credentials

Sync writes the generated configuration with mode `0600`.

The generated configuration includes the `remote-management.secret-key` value from the template. The control panel uses that value for management requests. Keep the listener on a trusted private interface.

No harness reads `secrets.local.json`. The gateway accepts requests without a client key; a provider that requires a non-empty key uses a static placeholder.

## Model prefixes

The template sets `force-model-prefix: true`, so a prefixed credential or compatibility profile namespaces its models.

A `prefix` belongs to the credential's generated auth file, so reauthentication removes it. Add one back only when you deliberately want to scope a credential to a separate model namespace.

## Routing settings

The committed template sets these CLIProxyAPI values:

| Setting | Value |
| --- | --- |
| `routing.strategy` | `weighted-round-robin` |
| `routing.session-affinity` | `true` |
| `routing.session-affinity-ttl` | `1h` |
| `request-retry` | `3` |
| `max-retry-credentials` | `0` |
| `max-retry-interval` | `30` |
| `disable-cooling` | `false` |
| `save-cooldown-status` | `true` |
| `streaming.bootstrap-retries` | `1` |
| `ws-auth` | `false` |

Sync passes these values through to CLIProxyAPI. It does not derive or override them at runtime.

## Control panel

The control panel is available at `http://<listen-host>:<listen-port>/management.html`. Sync deploys the committed `tools/cliproxyapi/panel.html` only on the gateway host.

The template sets `remote-management.disable-auto-update-panel` to `true`, so upstream never replaces the locally built asset.

Custom quota cards request their endpoints through the gateway's `/v0/management/api-call` proxy. The gateway substitutes the selected credential, so API keys do not reach the browser. Card definitions live in `tools/cliproxyapi/quota-cards.ts`.

## Provider limits

CLIProxyAPI has no repository-configured import or login flow for Perplexity or GitHub Copilot OAuth credentials. Those credentials remain available only through harness-native providers.
