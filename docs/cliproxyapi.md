# CLIProxyAPI

CLIProxyAPI provides one local API for ChatGPT subscription access, OpenCode Go, DeepSeek, OpenRouter, and OpenCode Zen.

## Managed artifacts

| Artifact | Path |
|---|---|
| Portable config template | `assets/cliproxyapi.yaml.tmpl` |
| Release pin and checksums | `assets/cliproxyapi.release.json` |
| Local secrets | `secrets.local.json` |
| Generated config | `~/.cli-proxy-api/config.yaml` |
| OAuth runtime files | `~/.cli-proxy-api/*.json` |
| Managed command | `~/.local/bin/cli-proxy-api` |

Sync supports the official macOS ARM64 and Linux x86_64 release assets pinned in the manifest. It downloads from GitHub, verifies SHA-256, extracts only `cli-proxy-api`, and caches the result.

## Configure secrets

Copy the example and set the management key, client keys, and provider credential pools:

```bash
cp secrets.local.example.json secrets.local.json
chmod 600 secrets.local.json
$EDITOR secrets.local.json
bun ./sync/src/cli.ts
```

The `CLIPROXY_MANAGEMENT_KEY` authenticates the local management API and control panel. `CLIPROXY_CLIENT_API_KEYS` is an array of keys accepted from clients. The initial configuration uses one shared client key.

`CLIPROXY_CREDENTIAL_POOLS` maps a provider name to one or more accounts:

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

Add an account by appending another object. Supported per-account fields are `apiKey`, `weight`, and `proxyUrl`. Equal accounts use weight `1`; weights must be integers from 1 through 1,000,000.

Provider API keys stay in the ignored `secrets.local.json`. The committed template owns base URLs, prefixes, credential-pool references, and models.dev provider identities. Model IDs are discovered rather than committed. Sync expands each pool into CLIProxyAPI's native credential entries, bcrypt-hashes the management key before rendering, and writes the generated config atomically with mode `0600`.

Sync rejects empty pools, duplicate keys within a pool, unknown account fields, invalid weights, missing template pools, and pools that the template does not reference. Never commit `secrets.local.json` or OAuth files.

## Model discovery

Run a normal cached reconciliation:

```bash
bun ./sync/src/cli.ts
```

Force authenticated upstream discovery and gateway refresh:

```bash
bun ./sync/src/cli.ts sync --refresh-models
```

Sync treats each upstream `/models` response as the availability boundary and enriches matching IDs from [models.dev](https://models.dev/). Provider-level and per-model `npm` and `shape` metadata select the upstream protocol:

| Metadata | Generated CLIProxyAPI route |
|---|---|
| `@ai-sdk/openai` or `shape: responses` | Responses through `codex-api-key` |
| `@ai-sdk/anthropic` | Messages through `claude-api-key` |
| `@ai-sdk/openai-compatible`, `@openrouter/ai-sdk-provider`, or `shape: completions` | Chat Completions through `openai-compatibility` |

Models without tool support or text output are omitted from the agent catalog. Unsupported transports are reported during forced refresh. For example, CLIProxyAPI's native Gemini executor fixes the Google API path to `/v1beta`; it cannot safely represent OpenCode Zen's custom Google path, so those models remain excluded until the gateway can express that transport.

The source catalog uses stable protocol mappings rather than model-specific exceptions. Adding or removing an upstream model does not require editing `assets/cliproxyapi.yaml.tmpl`.

## Authenticate ChatGPT

Use browser OAuth on macOS:

```bash
cli-proxy-api --codex-login
```

Use device login on a headless Linux host:

```bash
cli-proxy-api --codex-device-login
```

Do not copy one active refresh token between two running gateways. Stop the old gateway before transferring OAuth state, or authenticate again on the new host.

## Run the gateway

```bash
cli-proxy-api
```

The wrapper supplies the generated config path. CLIProxyAPI listens on `127.0.0.1:8317`. Sync does not install a service. Use launchd, systemd, tmux, or another process manager when you need background operation.

The local control panel is available at:

```text
http://127.0.0.1:8317/management.html
```

It requires `CLIPROXY_MANAGEMENT_KEY`. Remote management remains disabled, and sync overwrites panel changes on the next run. Put persistent API-key providers in `assets/cliproxyapi.yaml.tmpl` and their values in `secrets.local.json`.

The control panel lists OAuth files and configured API-key providers separately. The **Auth Files** count does not include `codex-api-key` or `openai-compatibility` entries.

## Account routing

The generated configuration uses equal weighted round-robin routing. Every account currently has weight `1`.

Session affinity keeps each active provider, model, and conversation tuple on one account. The one-hour TTL is sliding: activity refreshes it. If the bound account becomes unavailable or enters cooldown, CLIProxyAPI automatically selects another account.

Cross-credential retries are unlimited within the eligible pool. Cooldown scheduling remains enabled, and cooldown state persists next to the OAuth files so a gateway restart does not immediately retry an exhausted account.

CLIProxyAPI scheduling is reactive. It distributes new sessions, records upstream quota failures, and skips cooled credentials. It does not proactively schedule from every account's remaining five-hour or weekly quota. Persistent quota dashboards require a separately reviewed monitoring service.

Perplexity and GitHub Copilot OAuth credentials cannot use this path because CLIProxyAPI has no compatible import or login flow for those providers. They remain available only through harnesses that support those providers directly.

A manual sync prints this warning when the endpoint is unavailable:

```text
sync: warning: CLIProxyAPI is installed but not running; start it with: cli-proxy-api
```

## Verify the gateway

```bash
KEY=$(jq -r '.CLIPROXY_CLIENT_API_KEYS[0]' secrets.local.json)
curl -fsS http://127.0.0.1:8317/v1/models \
  -H "Authorization: Bearer $KEY" |
  jq -r '.data[].id'
```

Expected model names include `gpt-5.6-luna`, `go/gpt-5.6-luna`, `openrouter/auto`, `deepseek/deepseek-v4-flash`, and `zen/minimax-m3`.

## Future home-server deployment

Keep the API tailnet-only. Bind CLIProxyAPI to the server's Tailscale address, keep remote management disabled, and reach management through a Tailscale SSH port forward. Do not expose the gateway through the ordinary LAN, Tailscale Funnel, or the public internet.

Use one shared client key initially to minimize host configuration. If per-host revocation becomes necessary, add client keys without changing provider pools.

Back up `secrets.local.json` through an encrypted channel. Reauthenticate OAuth accounts after disaster recovery instead of backing up active refresh tokens. A single home server is the initial availability boundary.
