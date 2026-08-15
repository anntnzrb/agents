# Harness reference

Sync has adapters for Codex, DeepSeek Harness, OpenCode, Pi, and OMP. A matching source directory enables an adapter on macOS, Linux, and Windows.

The current CLIProxyAPI release manifest supports only macOS ARM64 and Linux x86_64. On Windows, managed-tool preparation fails before wrapper reconciliation because the manifest has no Windows asset.

## Adapter paths

| Harness | Source | Generated target | npm package |
| --- | --- | --- | --- |
| Codex | `harnesses/codex/` | `~/.codex/` | `@openai/codex` |
| DeepSeek Harness | `harnesses/deepseek/` | `~/.dsh/` | `@deepseek-ai/dsh` |
| OpenCode | `harnesses/opencode/` | `~/.config/opencode/` | `opencode-ai` |
| Pi | `harnesses/pi/agent/` | `~/.pi/agent/` | `@earendil-works/pi-coding-agent` |
| OMP | `harnesses/omp/agent/` | `~/.omp/agent/` | `@oh-my-pi/pi-coding-agent` |

`sync/src/core/harness-adapters.ts` owns launcher packages, target homes, runtime subdirectories, compatibility cleanup entries, and hooks.

## Shared configuration

Sync publishes `assets/AGENTS.md` and `skills/current/` to every enabled harness. Asset directories under `assets/` are also published to each harness. An adapter can rename an asset at the destination.

Pi has two additional hooks:

- `PackageBootstrap` prepares packages declared by its source manifest and updates runtime settings.
- `ExtensionDeps` installs dependencies for generated extensions when the hook inputs change.

## CLIProxyAPI integration

Codex, OpenCode, Pi, and OMP define one provider named `cliproxy`. The provider reads the first client key from `~/.local/share/agents/cliproxyapi/client-api-key` and sends requests to `http://127.0.0.1:8317/v1`.

| Harness | Catalog source | Request protocol |
| --- | --- | --- |
| Codex | Native remote model refresh | OpenAI Responses |
| OMP | Native `openai-models-list` discovery | OpenAI Responses |
| OpenCode | Shared runtime catalog through `harnesses/opencode/plugins/cliproxy.ts` | OpenAI Responses |
| Pi | Shared runtime catalog through `harnesses/pi/agent/extensions/cliproxy/index.ts` | OpenAI Responses |

The OpenCode plugin and the Pi extension read `~/.local/share/agents/model-catalog/catalog.json` through the installed runtime client. Neither adapter contains a static list of CLIProxyAPI model IDs.

API-key model IDs use the prefix declared by `x-model-sources`. The committed prefixes are `go`, `deepseek`, `openrouter`, and `zen`. ChatGPT OAuth models remain unprefixed.

OpenCode, Pi, and OMP selectors include the harness provider name, such as `cliproxy/openrouter/auto`. Codex stores `model_provider = "cliproxy"` separately, so its `model` value contains only the CLIProxyAPI model ID.

DeepSeek Harness keeps its upstream model and credential configuration. Configure models through its Web UI or `~/.dsh/settings.yaml`; its managed credentials live in `~/.dsh/.credentials.yaml`. Sync does not copy the CLIProxyAPI client key into that credential store.

## Launch wrappers

Sync writes Unix wrappers under `~/.local/bin/`. On Windows, sync writes `.cmd` wrappers under `%LOCALAPPDATA%/Programs/Agents/bin/` and adds that directory to the user `PATH` once.

Each wrapper calls the installed sync runtime with the `launch` command. The launch path attempts reconciliation, prepares the cached npm package, forwards all arguments, and returns the harness exit status.

Wrapper commands use the package executable name. DeepSeek Harness therefore uses `dsh`, while its adapter and source directory use `deepseek`.

Wrapper state lives at `~/.local/share/agents/sync-managed/wrappers.json`. Sync removes stale wrappers only when they contain its ownership marker and remain in an allowed wrapper directory. Unmanaged conflicts are preserved and reported.

## Package cache

Each harness has a versioned npm cache under `<cache-home>/npm-tools/`. `<cache-home>` is `XDG_CACHE_HOME` or `~/.cache`.

The cache keeps the current and previous known-good package versions. The launcher checks the package identity, executable, and adapter smoke command before promoting a version.
