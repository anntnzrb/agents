# CLIProxyAPI reference

CLIProxyAPI provides the OpenAI-compatible endpoint for harnesses configured to use it. `assets/cliproxyapi/deployment.json` is the only deployment-specific source. It selects the gateway host, server listener, and client endpoint. The management API and control panel use the static token committed in the template; the tailnet is the access boundary.

## Artifacts

| Artifact | Path |
| --- | --- |
| Portable configuration template | `assets/cliproxyapi/config.yaml.tmpl` |
| Deployment endpoints | `assets/cliproxyapi/deployment.json` |
| Release manifest and checksums | `assets/cliproxyapi/release.json` |
| Control panel asset | `assets/cliproxyapi/panel.html` |
| Control panel patch source | `assets/cliproxyapi/panel.patch` |
| Control panel rebuild script | `assets/cliproxyapi/panel.rebuild.sh` |
| Local secrets | `secrets.local.json` |
| Generated configuration | `~/.cli-proxy-api/config.yaml` |
| Deployed control panel | `~/.cli-proxy-api/static/management.html` |
| OAuth files | `~/.cli-proxy-api/*.json` |
| Runtime model catalog | `~/.local/share/agents/model-catalog/catalog.json` |
| Managed command | `~/.local/bin/cli-proxy-api` |

The current release manifest contains an official macOS ARM64 archive and an official Linux x86_64 archive. Sync verifies the selected SHA-256 checksum and extracts only the manifest's executable.

Sync prepares the managed binary and the `~/.local/bin/cli-proxy-api` wrapper only on the gateway host. Client hosts do not prepare managed tools and reconcile away a previously owned `cli-proxy-api` wrapper on their next sync.

## Deployment endpoints

`assets/cliproxyapi/deployment.json` is the source of truth for gateway placement:

| Field | Constraint | Meaning |
| --- | --- | --- |
| `server.hostname` | Local OS hostname | Host that runs the CLIProxyAPI gateway |
| `listen.host` | Specific host or interface address | Address that CLIProxyAPI binds |
| `listen.port` | Integer from 1 through 65,535 | Port that CLIProxyAPI binds |
| `client.baseUrl` | HTTP or HTTPS `/v1` URL without credentials, query, or fragment | Endpoint used by harnesses, catalog discovery, and health checks |

Sync rejects wildcard listeners, unspecified IPv6 spellings, unknown fields, malformed client URLs, raw query or fragment delimiters, and invalid ports. It renders the listener into `~/.cli-proxy-api/config.yaml` and replaces `${CLIPROXY_CLIENT_BASE_URL}` in each configured harness target.

Sync compares the local OS hostname with `server.hostname` to select the host role:

- On the gateway host, sync writes the server configuration before it checks the client endpoint.
- On another host, sync checks `client.baseUrl/models` without authentication.
- A client host without local secrets refreshes the model catalog from the gateway `/models` response and public models.dev metadata; it never writes the server configuration.
- Only the gateway host prepares the managed CLIProxyAPI binary and wrapper; client hosts reconcile away a previously owned wrapper.
- Only the gateway host deploys the pinned control panel asset to `~/.cli-proxy-api/static/management.html`.
- An unavailable endpoint preserves the existing server configuration, model catalog, and harness endpoints.
- A ready endpoint updates the model catalog and harness endpoints while leaving the local server configuration unchanged.

Endpoint publication is transactional. Publication preserves Codex-owned hook and project trust tables in `~/.codex/config.toml`.

To move the gateway, change the host and endpoint fields in `assets/cliproxyapi/deployment.json`, deploy the repository and secrets to the new gateway host, start CLIProxyAPI there, and run sync on clients. Clients keep their current endpoint until the new `/models` endpoint returns a non-empty `data` array. Update harness sources or documentation only when the configuration schema changes.

## Local secrets

`secrets.local.json` contains one top-level field:

| Field | Type | Meaning |
| --- | --- | --- |
| `CLIPROXY_CREDENTIAL_POOLS` | Non-empty object of account arrays | API-key accounts grouped by provider source |

Each credential account accepts these fields:

| Field | Required | Constraint |
| --- | --- | --- |
| `apiKey` | Yes | Non-empty string, unique within its pool |
| `weight` | No | Integer from 1 through 1,000,000 |
| `proxyUrl` | No | Non-empty string passed to CLIProxyAPI as `proxy-url` |

Pool names start with a lowercase letter and contain lowercase letters, digits, or hyphens. Every pool must contain at least one account. The template must reference every pool in the secrets file.

The renderer rejects unknown account fields, duplicate keys within a pool, invalid weights, missing pools, and unreferenced pools.

## Generated secrets

Sync writes the generated configuration and the shared model catalog with mode `0600`.

The generated configuration carries the static management token committed in the template. The gateway hashes the plaintext value at startup; the token is not a credential because the tailnet is the access boundary.

No harness reads `secrets.local.json`. The gateway accepts client requests without client keys; harness providers send a static placeholder key because their SDKs require a non-empty value.

## Model sources

`x-model-sources` in `assets/cliproxyapi/config.yaml.tmpl` defines API-key providers without committing model IDs.

| Source ID | models.dev provider | Credential pool | Public prefix | Base URL | Model catalog |
| --- | --- | --- | --- | --- | --- |
| `opencode-go` | `opencode-go` | `opencode-go` | `go` | `https://opencode.ai/zen/go/v1` | `<base-url>/models`, field `data` |
| `deepseek` | `deepseek` | `deepseek` | `deepseek` | `https://api.deepseek.com/v1` | `<base-url>/models`, field `data` |
| `opencode-zen` | `opencode` | `opencode-zen` | `zen` | `https://opencode.ai/zen/v1` | `<base-url>/models`, field `data` |
| `cline-pass` | `cline-pass` | `cline-pass` | `cline-pass` | `https://api.cline.bot/api/v1` | `https://api.cline.bot/api/v1/ai/cline/recommended-models`, field `clinePass` |

Each source accepts these fields:

| Field | Required | Meaning |
| --- | --- | --- |
| `id` | Yes | Unique source and cache ID |
| `models-dev-provider` | Yes | Provider key in the models.dev catalog |
| `credential-pool` | Yes | Pool in `CLIPROXY_CREDENTIAL_POOLS` |
| `prefix` | Yes | Public model prefix and CLIProxyAPI profile prefix |
| `base-url` | Yes | Upstream inference endpoint |
| `models-url` | No | Catalog endpoint; defaults to `<base-url>/models` |
| `models-field` | No | Top-level array in the catalog response; defaults to `data` |

The renderer sends the first credential in the selected pool as a Bearer token when it fetches the model catalog. It rejects a configured `models-field` when the response does not contain that array. The `x-model-sources` marker and its catalog-only fields do not appear in the generated configuration.

## Model prefixes

Every served model ID starts with the prefix of its origin:

| Prefix | Origin | Prefix source |
| --- | --- | --- |
| `go` | OpenCode Go subscription | `x-model-sources` template entry |
| `zen` | OpenCode Zen | `x-model-sources` template entry |
| `deepseek` | DeepSeek API | `x-model-sources` template entry |
| `cline-pass` | ClinePass subscription | `x-model-sources` template entry |
| `chatgpt` | ChatGPT OAuth accounts | `prefix` field in `~/.cli-proxy-api/codex-*.json` |
| `antigravity` | Google Antigravity OAuth accounts | `prefix` field in `~/.cli-proxy-api/antigravity-*.json` |
| `grok` | XAI Grok OAuth accounts | `prefix` field in `~/.cli-proxy-api/xai-*.json` |

Prefixes are single path segments. `force-model-prefix: true` drops the unprefixed ID of every account that carries a prefix, so identical upstream names from different origins never collide: `gpt-5.6-sol` exists only as `chatgpt/gpt-5.6-sol` and `zen/gpt-5.6-sol`.

OAuth prefixes live in the generated auth files, not in the repository. Re-authentication recreates those files and drops the prefix; re-apply it as described in the [operations guide](cliproxyapi.md#scope-models-by-origin).

## Discovery inputs

Sync combines four catalog sources:

1. Each API-key source's authenticated model catalog determines availability. Sources use `<base-url>/models` and the `data` field unless the template overrides `models-url` or `models-field`.
2. The live CLIProxyAPI `/v1/models` response determines gateway model availability and origin.
3. The live CLIProxyAPI `/v1/models?client_version=0.144.1` response supplies the gateway's reasoning levels, names, modalities, and context limits.
4. [models.dev](https://models.dev/) supplies protocol hints, compatibility fields, output limits, and published costs.

The normalized output is `~/.local/share/agents/model-catalog/catalog.json`. Model records are sorted by ID, and duplicate IDs fail publication. Each reasoning model keeps the discovered effort strings in order under `reasoningEfforts`; the catalog does not restrict them to a local enum. The rich response also supplies `defaultReasoningEffort` when the gateway advertises one.

The rich gateway response overrides models.dev for live names, input modalities, context limits, reasoning efforts, and default effort. This precedence covers provider-specific IDs that models.dev does not list, including Antigravity models. The catalog keeps models.dev metadata for fields that the gateway does not return.

## Protocol selection

Provider metadata selects the generated CLIProxyAPI profile:

| Provider metadata | Catalog protocol | Generated section |
| --- | --- | --- |
| `shape: responses`, `@ai-sdk/openai`, or `@ai-sdk/azure` | OpenAI Responses | `codex-api-key` |
| `@ai-sdk/anthropic` | Anthropic Messages | `claude-api-key` |
| `shape: completions` or `@ai-sdk/openai-compatible` | OpenAI Chat Completions | `openai-compatibility` |

An unsupported provider package excludes the model from the generated profiles. A forced refresh reports the count and package names for excluded transports.

## Catalog filters

Sync excludes known image-only, video-only, and review-only model IDs. Sync also excludes a model when metadata explicitly disables tool calls or text output.

For upstream catalogs without a `supported_parameters` list, sync accepts the model. When the list exists, the model must include `tools`.

The generated model ID is `<prefix>/<upstream-id>` for an `x-model-sources` entry. Other model IDs from CLIProxyAPI remain unchanged unless they conflict with a richer API-key record.

## Catalog caches

| Input | Freshness window | Stale fallback during normal sync |
| --- | --- | --- |
| models.dev | 1 hour | Yes |
| Provider model catalog | 6 hours | Yes |
| CLIProxyAPI `/v1/models` | 1 hour | Yes |
| CLIProxyAPI rich `/v1/models` | 1 hour | Yes |

`sync --refresh-models` bypasses every freshness window and disables stale fallback. Cached responses use mode `0600` and store the payload, fetch time, and optional ETag.

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

`weighted-round-robin` rotates new sessions across matching credentials according to their weights. An omitted weight is `1`. Credentials with equal weights receive equal shares.

Session affinity binds a provider, session identifier, and model to one credential. Each request refreshes the one-hour binding. CLIProxyAPI prefers explicit client session headers, then request fields such as `prompt_cache_key` and a Responses conversation ID, before it derives a fallback identity. Requests without a session identifier use weighted round-robin directly. Keeping one conversation on one credential can preserve provider-side prompt-cache locality. Cache behavior and billing remain provider-controlled.

If the bound credential becomes unavailable, session affinity selects another available credential and replaces the binding. `max-retry-credentials: 0` leaves the number of credentials uncapped, so one failed request can try every matching credential. Request-invalid errors stop instead of rotating.

After the available credentials are exhausted or cooling down, `request-retry: 3` permits another attempt when a credential can recover within `max-retry-interval: 30`. Cooling remains enabled, and persisted cooldown state prevents a restart from immediately selecting a credential that is still unavailable. `streaming.bootstrap-retries: 1` permits one restart when a stream fails before CLIProxyAPI sends a deliverable payload to the client.

Retrying improves availability but cannot guarantee zero duplicate upstream work. An upstream might accept work before CLIProxyAPI receives an error or before a stream produces its first deliverable payload.

The repository does not enable `quota-exceeded.antigravity-credits`, because that fallback can consume paid credits. It also has no quota-monitoring service and does not generate quota dashboards.

## Control panel

The control panel is available at `http://<listen-host>:<listen-port>/management.html`. The current deployment uses `http://munich.trex-gamut.ts.net:8317/management.html`. The panel accepts the static management token committed in the template; it is not a credential because the tailnet is the access boundary.

The template keeps `remote-management.disable-auto-update-panel` at `true`.

The deployed panel is a pinned patched build from `assets/cliproxyapi/panel.html`. The pinned upstream revision includes OpenCode Go quota. The local patch adds ClinePass quota with 5-hour, weekly, and monthly windows. The panel fetches `https://opencode.ai/zen/go/v1/usage` and `https://api.cline.bot/api/v1/users/me/plan/usage-limits` through the gateway's `/v0/management/api-call` proxy. The gateway substitutes the selected credential server-side, so API keys never reach the browser. The gateway never replaces the pinned asset while `disable-auto-update-panel` is `true`. Rebuild the asset with `assets/cliproxyapi/panel.rebuild.sh` after adopting a new upstream revision.

## Provider limits

CLIProxyAPI has no repository-configured import or login flow for Perplexity or GitHub Copilot OAuth credentials. Perplexity and GitHub Copilot credentials remain available only through harness-native providers.

The catalog generator omits provider transports that it cannot map to a CLIProxyAPI profile. The current implementation has no model-specific transport exceptions.
