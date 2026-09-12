# CLIProxyAPI model discovery

Populates the `cliproxy` provider's model map at load time through the plugin `config` hook, which runs
before OpenCode reads `provider` from the merged configuration. The `provider` hook cannot serve this
provider because it only augments providers that already exist in the bundled models.dev catalog.

The plugin is referenced as a directory from `opencode.jsonc` (`"plugin": ["./plugins/cliproxy"]`) and
default-exports `{ id, server }`. Types come from the installed `@opencode-ai/plugin` package (`Hooks`,
`PluginInput`, `Config`); the provider and model shapes are derived from `Config`, and the file passes
`tsc --strict` with type-only imports.

Discovery order per plugin load:

1. `GET {baseURL}/models` lists the gateway's current model ids. `baseURL` comes from the provider
   options, so no endpoint is duplicated here.
2. `https://models.dev/api.json` supplies limits, pricing, modalities, and capability flags for ids it
   knows. Lookups try the exact id, the segment after the last `/`, then the same keys with a trailing
   thinking-level qualifier (`-minimal`, `-low`, `-medium`, `-high`, `-max`, `-thinking`) removed, so
   `gemini-3.8-flash-high` resolves to the catalog's `gemini-3.8-flash` row. When several catalog rows
   share a key, the row with the widest context window wins.
3. Unknown ids fall back to `FALLBACK_LIMIT` (200K context, 32K output). The fallback exists because
   OpenCode disables context compaction for models without a context limit.

Display names carry the upstream pool in parentheses: multi-segment ids (`<pool>/<vendor>/<model>`)
use the id's pool segment, while single-segment OAuth-pool ids fall back to the gateway's `owned_by`
field (e.g. `GPT-6 Astra (openai)`, `Gemini 3.8 Flash (antigravity)`).

The models.dev snapshot is cached for 24 hours at `$XDG_CACHE_HOME/agents/models-dev.json`
(`~/.cache/agents/models-dev.json` by default) and is shared with the pi extension; the cache carries its
own format version and is ignored when that version changes. A failed fetch reuses the cached snapshot;
a failed gateway request leaves the provider's model map unchanged.
