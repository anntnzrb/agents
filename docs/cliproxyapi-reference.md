# CLIProxyAPI reference

CLIProxyAPI provides the OpenAI-compatible endpoint for harnesses configured to use it. `assets/cliproxyapi.deployment.json` is the only deployment-specific source. It selects the gateway host, server listener, and client endpoint. Remote management and the control panel are available to clients that can reach the private listener and authenticate with the management key.

## Artifacts

| Artifact | Path |
| --- | --- |
| Portable configuration template | `assets/cliproxyapi.yaml.tmpl` |
| Deployment endpoints | `assets/cliproxyapi.deployment.json` |
| Release manifest and checksums | `assets/cliproxyapi.release.json` |
| Local secrets | `secrets.local.json` |
| Generated configuration | `~/.cli-proxy-api/config.yaml` |
| OAuth files | `~/.cli-proxy-api/*.json` |
| Runtime client key | `~/.local/share/agents/cliproxyapi/client-api-key` |
| Runtime model catalog | `~/.local/share/agents/model-catalog/catalog.json` |
| Managed command | `~/.local/bin/cli-proxy-api` |

The current release manifest contains an official macOS ARM64 archive and an official Linux x86_64 archive. Sync verifies the selected SHA-256 checksum and extracts only the manifest's executable.

Sync prepares the managed binary and the `~/.local/bin/cli-proxy-api` wrapper only on the gateway host. Client hosts do not prepare managed tools and reconcile away a previously owned `cli-proxy-api` wrapper on their next sync.

## Deployment endpoints

`assets/cliproxyapi.deployment.json` is the source of truth for gateway placement:

| Field | Constraint | Meaning |
| --- | --- | --- |
| `server.hostname` | Local OS hostname | Host that runs the CLIProxyAPI gateway |
| `listen.host` | Specific host or interface address | Address that CLIProxyAPI binds |
| `listen.port` | Integer from 1 through 65,535 | Port that CLIProxyAPI binds |
| `client.baseUrl` | HTTP or HTTPS `/v1` URL without credentials, query, or fragment | Endpoint used by harnesses, catalog discovery, and health checks |

Sync rejects wildcard listeners, unspecified IPv6 spellings, unknown fields, malformed client URLs, raw query or fragment delimiters, and invalid ports. It renders the listener into `~/.cli-proxy-api/config.yaml` and replaces `${CLIPROXY_CLIENT_BASE_URL}` in each configured harness target.

Sync compares the local OS hostname with `server.hostname` to select the host role:

- On the gateway host, sync writes the server configuration before it checks the client endpoint.
- On another host, sync checks `client.baseUrl/models` with the candidate client key. If local secrets are absent, sync uses the installed runtime client key.
- Only the gateway host prepares the managed CLIProxyAPI binary and wrapper; client hosts reconcile away a previously owned wrapper.
- An unavailable endpoint preserves the existing server configuration, client key, model catalog, and harness endpoints.
- A ready endpoint updates the client key, model catalog, and harness endpoints while leaving the local server configuration unchanged.

Endpoint publication is transactional. Publication preserves Codex-owned hook and project trust tables in `~/.codex/config.toml`.

To move the gateway, change the host and endpoint fields in `assets/cliproxyapi.deployment.json`, deploy the repository and secrets to the new gateway host, start CLIProxyAPI there, and run sync on clients. Clients keep their current endpoint until the new `/models` endpoint returns a non-empty `data` array. Update harness sources or documentation only when the configuration schema changes.

## Local secrets

`secrets.local.json` contains three top-level fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `CLIPROXY_MANAGEMENT_KEY` | Non-empty string | Local management API and control-panel credential |
| `CLIPROXY_CLIENT_API_KEYS` | Non-empty array of unique strings | Bearer keys accepted from gateway clients |
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

Sync writes the generated configuration, the first client key, and the shared model catalog with mode `0600`.

The generated configuration contains a bcrypt hash of `CLIPROXY_MANAGEMENT_KEY`. Sync reuses the existing hash when the plaintext key still matches, which keeps an unchanged sync idempotent.

No harness reads `secrets.local.json`. Harnesses read the generated client-key file.

## Model sources

`x-model-sources` in `assets/cliproxyapi.yaml.tmpl` defines API-key providers without committing model IDs.

| Source ID | models.dev provider | Credential pool | Public prefix | Base URL |
| --- | --- | --- | --- | --- |
| `opencode-go` | `opencode-go` | `opencode-go` | `go` | `https://opencode.ai/zen/go/v1` |
| `deepseek` | `deepseek` | `deepseek` | `deepseek` | `https://api.deepseek.com/v1` |
| `openrouter` | `openrouter` | `openrouter` | `openrouter` | `https://openrouter.ai/api/v1` |
| `opencode-zen` | `opencode` | `opencode-zen` | `zen` | `https://opencode.ai/zen/v1` |

The `x-model-sources` marker does not appear in the generated configuration.

## Discovery inputs

Sync combines three catalog sources:

1. Each provider's authenticated `/models` response determines API-key model availability.
2. [models.dev](https://models.dev/) supplies protocol hints, names, capabilities, modalities, token limits, and published costs.
3. The live CLIProxyAPI `/v1/models` response adds gateway models from OAuth accounts.

The normalized output is `~/.local/share/agents/model-catalog/catalog.json`. Model records are sorted by ID, and duplicate IDs fail publication.

## Protocol selection

Provider metadata selects the generated CLIProxyAPI profile:

| Provider metadata | Catalog protocol | Generated section |
| --- | --- | --- |
| `shape: responses`, `@ai-sdk/openai`, or `@ai-sdk/azure` | OpenAI Responses | `codex-api-key` |
| `@ai-sdk/anthropic` | Anthropic Messages | `claude-api-key` |
| `shape: completions`, `@ai-sdk/openai-compatible`, or `@openrouter/ai-sdk-provider` | OpenAI Chat Completions | `openai-compatibility` |

An unsupported provider package excludes the model from the generated profiles. A forced refresh reports the count and package names for excluded transports.

## Catalog filters

Sync excludes known image-only, video-only, and review-only model IDs. Sync also excludes a model when metadata explicitly disables tool calls or text output.

For upstream catalogs without a `supported_parameters` list, sync accepts the model. When the list exists, the model must include `tools`.

The generated model ID is `<prefix>/<upstream-id>` for an `x-model-sources` entry. Other model IDs from CLIProxyAPI remain unchanged unless they conflict with a richer API-key record.

## Catalog caches

| Input | Freshness window | Stale fallback during normal sync |
| --- | --- | --- |
| models.dev | 1 hour | Yes |
| Provider `/models` | 6 hours | Yes |
| CLIProxyAPI `/v1/models` | 1 hour | Yes |

`sync --refresh-models` bypasses every freshness window and disables stale fallback. Cached responses use mode `0600` and store the payload, fetch time, and optional ETag.

## Routing settings

The committed template sets these CLIProxyAPI values:

| Setting | Value |
| --- | --- |
| `routing.strategy` | `weighted-round-robin` |
| `routing.session-affinity` | `true` |
| `routing.session-affinity-ttl` | `1h` |
| `request-retry` | `1` |
| `max-retry-credentials` | `0` |
| `disable-cooling` | `false` |
| `save-cooldown-status` | `true` |

The repository has no quota-monitoring service and does not generate quota dashboards.

## Control panel

The control panel is available at `http://<listen-host>:<listen-port>/management.html`. The current deployment uses `http://munich.trex-gamut.ts.net:8317/management.html`. The page itself is public on the private listener. Its management API uses `CLIPROXY_MANAGEMENT_KEY` for authentication.

Remote management is enabled on the private Tailscale listener. The template also sets `remote-management.disable-auto-update-panel` to `true`.

## Provider limits

CLIProxyAPI has no repository-configured import or login flow for Perplexity or GitHub Copilot OAuth credentials. Perplexity and GitHub Copilot credentials remain available only through harness-native providers.

The catalog generator omits provider transports that it cannot map to a CLIProxyAPI profile. The current implementation has no model-specific transport exceptions.
