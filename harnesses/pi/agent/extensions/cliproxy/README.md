# CLIProxyAPI provider

Registers the `cliproxy` provider through `pi.registerProvider` and refreshes its catalog through the
`refreshModels` primitive. `sync` replaces `${CLIPROXY_CLIENT_BASE_URL}` with the deployment endpoint.
Types come from the installed `@earendil-works/pi-coding-agent` package (`ExtensionAPI`,
`ProviderModelConfig`); the runtime catalog reads come from `@earendil-works/pi-ai/providers/all`, which
Pi resolves for hosted extensions. The file has no local type declarations and passes `tsc --strict`.

Discovery order per refresh:

1. `GET {baseUrl}/models` lists the gateway's current model ids.
2. `https://models.dev/api.json` supplies limits, pricing, modalities, and reasoning flags for ids it
   knows. Lookups try the exact id, the segment after the last `/`, then the same keys with a trailing
   thinking-level qualifier (`-minimal`, `-low`, `-medium`, `-high`, `-max`, `-thinking`) removed, so
   `gemini-3.8-flash-high` resolves to the catalog's `gemini-3.8-flash` row. When several catalog rows
   share a key, the row with the widest context window wins.
3. Unknown ids fall back to `FALLBACK_CONTEXT_WINDOW` (128K) and `FALLBACK_MAX_TOKENS` (16.4K), which
   are pi defaults for metadata-free models.

## Per-model request metadata

One provider fronts many upstreams, so a model's request dialect cannot come from the provider or
base URL. Each discovered model instead carries `compat` and `thinkingLevelMap` resolved from pi's
shipped catalog, which already authors them per model:

- The catalog is indexed once per process by model id and by `provider/modelId`. A gateway id resolves
  by its exact id, then by the segment after the last `/`.
- When several shipped providers publish the same model id, the provider named as a segment of the
  gateway id wins, so `opencode-go/deepseek-v4-pro` keeps the `opencode-go` dialect.
- Only `openai-completions` models are indexed. This provider speaks that protocol to the gateway, so
  metadata authored for another protocol describes a request shape it never sends.
- Models newer than the shipped catalog keep the generic dialect, and their thinking levels come from
  the models.dev `reasoning_options` effort list, which is also why `:max` reaches the wire for them
  instead of clamping to a supported level.

Without this resolution a reasoning request carries `reasoning_effort` only. Models whose upstream
dialect requires a `thinking` field never enable extended thinking, and levels the model does support
are absent from `thinkingLevelMap`, so pi clamps the selected level to the highest mapped one.

The models.dev snapshot is cached for 24 hours at `$XDG_CACHE_HOME/agents/models-dev.json`
(`~/.cache/agents/models-dev.json` by default) and is shared with the OpenCode plugin; the cache carries
its own format version and is ignored when that version changes. A failed fetch reuses the cached
snapshot, and a failed gateway request keeps the last catalog discovered in the running process.
`PI_OFFLINE=1` disables discovery.
