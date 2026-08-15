# Harnesses

Sync supports Codex, OpenCode, Pi, and OMP. A matching source directory under `harnesses/` opts into the harness.

| Harness | Source | Generated target |
|---|---|---|
| Codex | `harnesses/codex/` | `~/.codex/` |
| OpenCode | `harnesses/opencode/` | `~/.config/opencode/` |
| Pi | `harnesses/pi/agent/` | `~/.pi/agent/` |
| OMP | `harnesses/omp/agent/` | `~/.omp/agent/` |

## Change harness configuration

1. Edit the matching path under `harnesses/`.
2. Run `bun ./sync/src/cli.ts`.
3. Inspect the generated target.
4. Run the harness-specific smoke test.

Do not edit generated tool homes. A later sync replaces managed files.

## Use CLIProxyAPI models

Sync writes the first `CLIPROXY_CLIENT_API_KEYS` entry to the private runtime file `~/.local/share/agents/cliproxyapi/client-api-key`. Each harness uses one `cliproxy` provider:

| Harness | Catalog mechanism | Request protocol |
|---|---|---|
| Codex | Native remote model refresh | OpenAI Responses |
| OMP | Native `openai-models-list` discovery and cache | OpenAI Responses |
| OpenCode | Minimal config plugin backed by the shared sync catalog | OpenAI Responses |
| Pi | Minimal provider extension backed by the shared sync catalog | OpenAI Responses |

The OpenCode plugin and Pi extension read `~/.local/share/agents/model-catalog/catalog.json` through the installed runtime catalog client. They contain no model IDs and do not fetch provider catalogs themselves. Sync owns discovery, metadata enrichment, caching, and stale recovery.

CLIProxy model IDs identify the upstream credential pool:

| Model ID | Upstream |
|---|---|
| `gpt-5.6-luna` | Unprefixed ChatGPT/Codex OAuth credentials |
| `antigravity/gemini-3.7-flash-high` | Prefixed Antigravity OAuth credentials |
| `go/gpt-5.6-luna` | OpenCode Go credential pool |
| `zen/gpt-5.6-luna` | OpenCode Zen credential pool |
| `openrouter/openai/gpt-5.6-luna` | OpenRouter credential pool |

OpenCode, Pi, and OMP selectors prepend the harness provider, such as `cliproxy/antigravity/gemini-3.7-flash-high`. Codex sets `model_provider = "cliproxy"` separately, so its model value is only the CLIProxy model ID.

## Launch wrappers

Sync writes harness commands to `~/.local/bin` on macOS and Linux. On Windows, it writes commands under `%LOCALAPPDATA%/Programs/Agents/bin` and adds that directory to the user path once.

Each wrapper runs sync before it resolves and launches the cached npm package. The cache keeps the current and previous known-good package versions.

## Add a harness

Add an adapter to `sync/src/core/harness-adapters.ts`, create its source directory under `harnesses/`, and add wrapper and integration tests. Keep launcher metadata in the adapter instead of repeating it in user configuration.
