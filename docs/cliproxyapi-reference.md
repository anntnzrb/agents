# CLIProxyAPI reference

CLIProxyAPI provides the local OpenAI-compatible endpoint used by Codex, OpenCode, Pi, and OMP. The generated configuration binds to `127.0.0.1:8317`, disables remote management, and keeps the local control panel enabled.

## Artifacts

| Artifact | Path |
| --- | --- |
| Portable configuration template | `assets/cliproxyapi.yaml.tmpl` |
| Release manifest and checksums | `assets/cliproxyapi.release.json` |
| Local secrets | `secrets.local.json` |
| Generated configuration | `~/.cli-proxy-api/config.yaml` |
| OAuth files | `~/.cli-proxy-api/*.json` |
| Runtime client key | `~/.local/share/agents/cliproxyapi/client-api-key` |
| Runtime model catalog | `~/.local/share/agents/model-catalog/catalog.json` |
| Managed command | `~/.local/bin/cli-proxy-api` |

The current release manifest contains an official macOS ARM64 archive and an official Linux x86_64 archive. Sync verifies the selected SHA-256 checksum and extracts only the manifest's executable.

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

The local control panel is `http://127.0.0.1:8317/management.html`. The control panel uses `CLIPROXY_MANAGEMENT_KEY` for authentication.

Remote management is disabled. The template also sets `remote-management.disable-auto-update-panel` to `true`.

## Provider limits

CLIProxyAPI has no repository-configured import or login flow for Perplexity or GitHub Copilot OAuth credentials. Perplexity and GitHub Copilot credentials remain available only through harness-native providers.

The catalog generator omits provider transports that it cannot map to a CLIProxyAPI profile. The current implementation has no model-specific transport exceptions.
