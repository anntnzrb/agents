# CLIProxyAPI

CLIProxyAPI provides the OpenAI-compatible endpoint for harnesses that configure a `cliproxy` provider, and the Anthropic Messages endpoint (`/v1/messages`) that Claude Code reaches through `ANTHROPIC_BASE_URL`. `tools/cliproxyapi/deployment.json` selects the gateway host, listener, and client endpoint. An optional HTTP facade adds System One classification without changing the upstream CLIProxyAPI binary.

T3 Code sessions on the gateway host also consume this endpoint through the Codex provider configuration; their load draws from the Codex OAuth pool.

Use the procedures to change credentials, authenticate ChatGPT, run the gateway, and check model access. See [System One classification](#system-one-classification) for the optional facade and its client contract.

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

For the MiMo Token Plan, use the API key shown with the plan's dedicated base URL in the MiMo platform console ([Plan Management](https://platform.xiaomimimo.com/#/console/plan-manage)) and add it to the `mimo` pool. The plan meters a fixed Credits quota and suspends its dedicated endpoint at exhaustion without falling back to bonus or account balance.

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

## Authenticate Antigravity

Use the control panel or the CLI. Both flows end at `http://localhost:51121/oauth-callback`, so the browser that completes Google OAuth must resolve `localhost:51121` to the gateway host. When operating the gateway remotely, forward the port first:

```bash
ssh -L 51121:localhost:51121 <gateway-host>
```

Panel flow: open the control panel and start Antigravity login. The gateway runs a temporary callback forwarder on port `51121`, exchanges the authorization code, writes the credential file under `~/.cli-proxy-api/`, and loads it without a restart.

CLI flow on the gateway host:

```bash
cli-proxy-api --antigravity-login --no-browser
```

Open the printed URL in the browser. Restrict the generated file:

```bash
chmod 600 ~/.cli-proxy-api/antigravity-*.json
```

## Authenticate Claude

Each Claude Pro or Max subscription is one OAuth file. Use the control panel or the CLI. Both flows end at `http://localhost:54545/callback`, so forward that port when operating the gateway remotely:

```bash
ssh -L 54545:localhost:54545 <gateway-host>
```

On the gateway host:

```bash
cli-proxy-api --claude-login --no-browser
chmod 600 ~/.cli-proxy-api/claude-*.json
```

Repeat per subscription. The gateway loads new files without a restart. To give a larger plan a bigger share of new sessions, add a top-level integer `"weight"` to its auth JSON; the default is `1`.

## Run the gateway

On the gateway host, sync runs CLIProxyAPI as the `cliproxyapi.service` systemd user unit and restarts it only when the unit changes (see [User services](sync/sync.md#user-services)). The managed wrapper supplies `--config ~/.cli-proxy-api/config.yaml`; sync reads the listener and client endpoint from `tools/cliproxyapi/deployment.json`. User units survive logout only with lingering enabled on the host (`loginctl enable-linger`).

```bash
systemctl --user status cliproxyapi.service
journalctl --user -u cliproxyapi.service -n 50
```

For a foreground debugging session, stop the unit first, then run `cli-proxy-api`.

## System One classification

The facade in `tools/cliproxyapi/gateway.py` sends `POST /v1/systemone` to the upstream configured in `tools/cliproxyapi/gateway.json`. It uses the native TypeSafe System One request and response format. The model must match an entry in the configured allowlist exactly. The facade selects a credential from the installed OpenRouter pool using thread-safe weighted round robin. Each valid request uses one key; classification does not add retries or failover.

Chat requests pass through to CLIProxyAPI. The facade enriches the model list as described in [Discovery metadata](#discovery-metadata). Classifiers do not appear in `/v1/models`: listing a classifier as a chat model would make clients invoke the wrong protocol. CLIProxyAPI retains its own routing, retries, and statistics for chat. Classification calls bypass that pipeline, so their budget and usage controls belong to the upstream provider. Set a spending limit on each OpenRouter key in the provider dashboard.

The facade accepts client requests without authentication on its private listener. It forwards inference routes and CLIProxyAPI's management surface (`/management.html`, `/v0/management/`, `/v8/management/`, and `/v0/resource/plugins/`), so the control panel stays on the client endpoint. Management requests keep their `Authorization` and `X-Management-Key` headers because CLIProxyAPI checks the panel's own key; inference requests have client credentials replaced. The public Funnel path keeps its separate bearer-token gate and refuses the management surface; see [Expose the gateway through Tailscale Funnel](#expose-the-gateway-through-tailscale-funnel).

The facade buffers request bodies, caps System One bodies at 16 MiB, and uses a 120-second I/O timeout while leaving forwarded CLIProxyAPI uploads uncapped.

Any HTTP client or native System One SDK can use the facade. Configure its base URL with the facade's `/v1` endpoint and register the classifier explicitly. A chat-only agent still needs a client adapter for System One. The server has no dependency on a particular harness or orchestrator.

### Enable the facade

The facade is opt-in. Enabling it changes the endpoint clients use, so schedule that change separately from local development.

1. Review the upstream and model allowlist in `tools/cliproxyapi/gateway.json`.
2. Add your OpenRouter keys to the `openrouter` array in `CLIPROXY_CREDENTIAL_POOLS` in the ignored `secrets.local.json`, following `secrets.local.example.json`. Keep the file at mode `0600`. The classifier supports pool weights; `proxyUrl` is rejected while classification is enabled.
3. Add a `gateway` listener to `tools/cliproxyapi/deployment.json`. Use a trusted private interface and a port distinct from `listen`; leave `listen` pointing at CLIProxyAPI.
4. Point `client.baseUrl` at the facade's `/v1` endpoint.
5. During the deployment window, run `uv run --project sync sync` on the gateway host, then on client hosts.

Sync installs the facade and its private configuration on the gateway host. On Linux, it manages `cliproxy-gateway.service`. The existing Funnel auth gateway forwards to the facade when the optional listener is configured. Public clients still use the Funnel bearer token, not the OpenRouter key.

### Verify changes in isolation

Run the facade's adjacent tests from the repository root:

```bash
uv run --project sync pytest -n 0 tools/cliproxyapi/tests
```

These tests use local fake upstreams. They do not require provider credentials or a running production proxy. A temporary home alone does not isolate sync service operations; see [Develop the sync application](sync/development.md#run-the-full-checks) before running sync tests.

On Linux, with dependencies already cached, run the tests in a network namespace:

```bash
unshare --user --map-root-user --net sh -c 'ip link set lo up && setpriv --bounding-set=-all --inh-caps=-all --ambient-caps=-all uv run --project sync pytest -n 0 tools/cliproxyapi/tests'
```

Only loopback networking is available. Dropping capabilities also keeps filesystem permission tests meaningful despite the namespace's root mapping.

## Expose the gateway through Tailscale Funnel

Hosted clients outside the tailnet (Amp) reach the gateway through Tailscale Funnel on port 443. CLIProxyAPI accepts any client key, so the public path goes through the auth gateway (`tools/cliproxyapi/auth-gateway.py`), which requires one bearer token and forwards to the private listener. The auth gateway answers `404` for CLIProxyAPI's management surface before it checks the token, so the control panel is never reachable from the internet, even with a valid client token. It matches the decoded, slash-normalized path, so encoded or doubled slashes cannot bypass the check. Sync installs the script on the gateway host and runs it as `cliproxy-auth-gateway.service` only while `CLIPROXY_FUNNEL_TOKEN` is set in `secrets.local.json`; removing the token removes the service and its env file.

The Funnel mapping itself lives in Tailscale's state, not in this repository. Recreate it on a new gateway host:

```bash
tailscale funnel --bg 8318
```

Rotate the token:

1. On the gateway host, generate a token into `secrets.local.json` without printing it: `python3 -c 'import json,secrets,pathlib; p=pathlib.Path.home()/".config/agents/secrets.local.json"; d=json.loads(p.read_text()); d["CLIPROXY_FUNNEL_TOKEN"]=secrets.token_hex(32); p.write_text(json.dumps(d, indent=2)+"\n")'`.
2. Read it from your own terminal and paste it into the client's provider settings: `python3 -c 'import json,pathlib; print(json.loads((pathlib.Path.home()/".config/agents/secrets.local.json").read_text())["CLIPROXY_FUNNEL_TOKEN"])'`.
3. Run `uv run --project sync sync` on the gateway host. The service restarts with the new token and the old one stops working. Any sync on that host, including the one each harness launch runs, applies the new token, so paste it promptly after step 1.

## Open the control panel

Open `<client-origin>/management.html`, where `<client-origin>` is `client.baseUrl` from `tools/cliproxyapi/deployment.json` without the trailing `/v1`. When the facade is enabled, it forwards the panel to CLIProxyAPI's private listener.

The panel uses `remote-management.secret-key` from `tools/cliproxyapi/config.yaml.tmpl`. Treat that value as a credential. Do not expose the panel through the public internet, Tailscale Funnel, or an untrusted LAN.

CLIProxyAPI bans a client IP for 30 minutes after five failed management-key attempts. Behind the facade, every panel request reaches CLIProxyAPI from the loopback address, so repeated wrong keys lock out every panel user until the ban expires or `cliproxyapi.service` restarts.

Do not make durable configuration changes in the control panel. Sync replaces the generated configuration from `tools/cliproxyapi/config.yaml.tmpl` and `secrets.local.json`.

## Rebuild the control-panel asset

The panel is upstream `main` plus local patches (`tools/cliproxyapi/panel.patch`) and the card definitions in `tools/cliproxyapi/quota-cards.ts`. The patch adds the quota-card framework and the **Quota Pool** page (`#/quota-pool`). That page combines each provider's credentials into one capacity (three Claude accounts = 300%) and shows a stacked bar per quota window with one slot per account. It shares the quota cache with Quota Management, and it fetches any credential that has no cached quota as soon as it opens. Rebuild after changing a card or adopting upstream changes:

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

OpenRouter uses this same card framework: each configured key gets its own card, quota cache entry, and refresh action. Sync registers the keys with CLIProxyAPI for management queries but gives the provider an empty chat-model list. Adding keys does not publish classifiers as chat models. Quota inspection remains available with the classification listener disabled.

The card reads the provider's [current-key endpoint](https://openrouter.ai/docs/api/api-reference/api-keys/get-current-key). It shows the key's remaining USD spending allowance and spend totals, not the account's prepaid balance. Keys without a cap show no-limit status and spend totals. Budget reset periods are labels, not invented reset timestamps. Account-wide credits need an OpenRouter management key and are outside this integration.

Quota requests identify the selected credential by its `auth_index` and use `$TOKEN$` substitution through `/v8/management/requests/api-call`; the browser does not call OpenRouter directly. The authenticated management API retains its existing access to provider configuration. Quota discovery reads the native `/v0/management/openai-compatibility` metadata because the editable v8 configuration omits per-key auth indices; provider edits keep using the v8 configuration API. After editing cards:

```bash
sh tools/cliproxyapi/panel.rebuild.sh
uv run --project sync sync
```

Sync deploys the built asset to `~/.cli-proxy-api/static/management.html` on the gateway host.

## Model IDs

The template exposes upstream model names as-is. Aliases, forked model variants, and forced payload mappings are not used. Credentials without a `prefix` field share one pool per provider and expose upstream model names.

With `force-model-prefix`, a credential or compatibility profile that carries a `prefix` exposes its models as `<prefix>/<model>`, and requests without that prefix cannot use the prefixed credential. A `prefix` belongs to the credential's generated auth file, so reauthentication removes it.

Client-side, OMP references gateway models as `cliproxy/<id>`; the prefix is mandatory because a bare first segment can collide with a bundled native provider (e.g. `opencode-zen/...` resolves to OMP's own opencode-zen, bypassing the proxy). Single-segment ids are OAuth-backed pools (antigravity, codex); multi-segment ids are `openai-compatibility` pools. Pin one route per model role — same model through two pools are distinct ids with distinct upstream caches, so alternating them cold-starts prompt caching; `routing.session-affinity` already keeps a session on one credential.

### Discovery metadata

For an exact `GET /v1/models`, the facade combines CLIProxyAPI's OpenAI list with its Codex catalog.
It adds positive context windows as `context_length` without inventing limits for omitted models.
It also adds `supported_endpoint_types`, identifying Claude models served by native Anthropic credentials.
Other pools remain on the OpenAI-compatible endpoint, even when their model name contains `claude`.
The ownership rule lives beside the implementation in `tools/cliproxyapi/gateway.py`.

A failed metadata fetch leaves context limits absent but preserves the model list.
A failed listing fetch falls back to the normal relay and preserves upstream error status.
Catalog requests with query parameters pass through unchanged.
Clients can retain their own trusted metadata and use gateway limits only as a fallback.

### Codex model catalog

The Codex provider in `harnesses/codex/config.toml` declares a command-backed `auth` block. Command auth marks the provider as catalog-fetching, so Codex requests `{base_url}/models?client_version=...` on startup and on each cache expiry. CLIProxyAPI answers that request with a native Codex model catalog (`ModelInfo` entries: slug, display name, context window, reasoning levels, instructions), which Codex merges into its bundled catalog — every gateway model then resolves real metadata instead of the generic fallback, and `model/list` exposes them all as built-ins. The merged result is cached in `~/.codex/models_cache.json` (runtime state, never tracked); bundled native entries always come from the installed binary.

The catalog's per-model metadata comes from the discovered `models[]` records described in [CLIProxyAPI jobs](sync/sync.md#cliproxyapi-jobs): `max-context-length` becomes `context_window`, `thinking.levels` becomes the reasoning-effort ladder, `display-name` becomes the display name. When models.dev reports reasoning_options effort values for the model those values are preserved verbatim as the ladder (e.g. minimal/low/medium/high/xhigh); the low/medium/high default applies only when the catalog marks reasoning without declaring options. Pool models do not advertise `apply_patch_tool_type` — upstream strips it for non-template models — so foreign models edit through shell/exec tools rather than the structured patch tool.

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
| Funnel auth gateway source | `tools/cliproxyapi/auth-gateway.py` |
| Installed auth gateway and its env file | `~/.cli-proxy-api/auth-gateway.py`, `~/.cli-proxy-api/auth-gateway.env` |
| System One facade source and upstream allowlist | `tools/cliproxyapi/gateway.py`, `tools/cliproxyapi/gateway.json` |
| Installed facade and its private configuration | `~/.cli-proxy-api/gateway.py`, `~/.cli-proxy-api/gateway.json` |

Sync verifies the selected release's SHA-256 checksum and extracts only the manifest's executable.

Sync prepares the managed binary and wrapper only on the gateway host. Client hosts remove a previously owned `cli-proxy-api` wrapper on their next sync.

## Deployment file

`tools/cliproxyapi/deployment.json` contains these fields:

| Field | Constraint | Meaning |
| --- | --- | --- |
| `server.hostname` | Local OS hostname | Host that runs the CLIProxyAPI gateway |
| `listen.host` | Specific host or interface address | Address that CLIProxyAPI binds |
| `listen.port` | Integer from 1 through 65,535 | Port that CLIProxyAPI binds |
| `client.baseUrl` | HTTP or HTTPS `/v1` URL without credentials, query, or fragment | Endpoint used by harnesses and readiness checks |

Sync rejects wildcard listeners, unspecified IPv6 addresses, unknown fields, malformed client URLs, raw query or fragment delimiters, and invalid ports. It renders the listener into `~/.cli-proxy-api/config.yaml` and replaces `${CLIPROXY_CLIENT_BASE_URL}` (the `/v1` URL) and `${CLIPROXY_CLIENT_ORIGIN}` (the same URL without `/v1`) in configured harness targets.

The optional `gateway` listener uses the same validation rules as `listen`. Omitting it leaves CLIProxyAPI as the only managed inference listener. See [Enable the facade](#enable-the-facade) for the migration procedure.

Sync compares the local OS hostname with `server.hostname` to choose the host role:

- The gateway host writes the server configuration and deploys the control-panel asset.
- A client host checks `client.baseUrl/models` without authentication.
- An unavailable client endpoint preserves existing harness endpoint files.
- A ready client endpoint lets sync update harness endpoints without replacing the local server configuration.

Endpoint publication is transactional. Publication preserves Codex-owned hook and project trust tables in `~/.codex/config.toml`. To change the gateway host or endpoint values, use [Set the deployment](#set-the-deployment).

## Local secrets

`secrets.local.json` contains these top-level fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `CLIPROXY_CREDENTIAL_POOLS` | Object of account arrays | API-key accounts grouped by provider pool |
| `CLIPROXY_FUNNEL_TOKEN` | Optional string, at least 32 characters | Bearer token the public Funnel auth gateway requires; unset disables the auth gateway. Never copy a placeholder here |

Each credential account accepts these fields:

| Field | Required | Constraint |
| --- | --- | --- |
| `apiKey` | Yes | Non-empty string, unique within its pool |
| `weight` | No | Integer from 1 through 1,000,000 |
| `proxyUrl` | No | Non-empty string passed to CLIProxyAPI as `proxy-url` |

Pool names start with a lowercase letter and contain lowercase letters, digits, or hyphens. Every pool must contain at least one account. The template must reference every pool in the secrets file.

The renderer rejects unknown account fields, duplicate keys within a pool, invalid weights, missing pools, and unreferenced pools.

The optional OpenRouter pool uses the same credential shape as the other pools. It is required when the facade listener is configured; see [System One classification](#system-one-classification). The gateway host reads the ignored secrets file at `~/.config/agents/secrets.local.json`. Runtime credentials are rendered into installed private files rather than read by harnesses.

## Generated files and credentials

Sync writes the generated configuration with mode `0600`.

The generated configuration includes the `remote-management.secret-key` value from the template. The control panel uses that value for management requests. Keep the listener on a trusted private interface.

No harness reads `secrets.local.json`. The gateway accepts requests without a client key; a provider that requires a non-empty key uses a static placeholder.

## Routing settings

`tools/cliproxyapi/config.yaml.tmpl` is the source of truth for routing, retry, cooldown, and streaming values; comments there explain the non-obvious ones. Sync passes them through to CLIProxyAPI and does not derive or override them at runtime.

### Claude subscriptions

Anthropic's prompt cache is scoped per account, so a conversation must stay on one credential:

- `session-affinity` pins each session to its first credential for `session-affinity-ttl`, which must cover the 1h cache lifetime; subagents inherit the parent's binding. `weighted-round-robin` only spreads new sessions. Fill-first would drain one account's 5h window while the others sit idle, with no cache benefit.
- For every non-Claude-Code client (OMP, Pi, OpenCode), CLIProxyAPI places the cache breakpoints (last system block and last message) and upgrades them to the 1h TTL on OAuth credentials. No client or template setting is needed. Check it by sending the same request twice: the second response reports the prefix under `prompt_tokens_details.cached_tokens` (`cache_read_input_tokens` on `/v1/messages`), and `/v1/messages` usage reports writes under `cache_creation.ephemeral_1h_input_tokens`.
- A 429 whose `anthropic-ratelimit-unified-5h/7d-status` is `rejected` cools the whole credential, and the session fails over. A model-only rejection (Fable or overage) cools only that model. Leave `claude.model-level-cooling` unset: setting it `true` downgrades shared 5h/7d rejections to model scope, so sibling models keep hitting an exhausted account.
- CLIProxyAPI does not switch accounts at a soft utilization threshold. It records the unified headers but moves only on rejection.
- `claude-sonnet-4-6` is served by both the Claude and Antigravity pools, so a new session can land on either. Pin a Claude-only model id when the route matters.

## Upstream truth

When a setting's semantics look wrong or a flag seems off, read the pinned release source — not this page. `config.example.yaml` in the upstream repository documents every accepted key, and `internal/` is authoritative for behavior. `tools/cliproxyapi/release.json` records which release is deployed.

## Control panel

Keep `remote-management.disable-auto-update-panel` enabled in the template; otherwise upstream replaces the locally built panel asset.

## Provider limits

CLIProxyAPI has no repository-configured import or login flow for Perplexity or GitHub Copilot OAuth credentials. Those credentials remain available only through harness-native providers.
