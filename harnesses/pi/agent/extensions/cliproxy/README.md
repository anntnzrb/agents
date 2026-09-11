# CLIProxyAPI provider

Registers the `cliproxy` provider through `pi.registerProvider` and refreshes its catalog through the
`refreshModels` primitive. `sync` replaces `${CLIPROXY_CLIENT_BASE_URL}` with the deployment endpoint.
Types come from the installed `@earendil-works/pi-coding-agent` package (`ExtensionAPI`,
`ProviderModelConfig`); the file has no local type declarations and passes `tsc --strict` with type-only
imports.

Discovery order per refresh:

1. `GET {baseUrl}/models` lists the gateway's current model ids.
2. `https://models.dev/api.json` supplies limits, pricing, modalities, and reasoning flags for ids it
   knows. Lookups try the exact id, the segment after the last `/`, then the same keys with a trailing
   thinking-level qualifier (`-minimal`, `-low`, `-medium`, `-high`, `-max`, `-thinking`) removed, so
   `gemini-3.8-flash-high` resolves to the catalog's `gemini-3.8-flash` row. When several catalog rows
   share a key, the row with the widest context window wins.
3. Unknown ids fall back to `FALLBACK_CONTEXT_WINDOW` (128K) and `FALLBACK_MAX_TOKENS` (16.4K), which
   are pi defaults for metadata-free models.

The models.dev snapshot is cached for 24 hours at `$XDG_CACHE_HOME/agents/models-dev.json`
(`~/.cache/agents/models-dev.json` by default) and is shared with the OpenCode plugin; the cache carries
its own format version and is ignored when that version changes. A failed fetch reuses the cached
snapshot, and a failed gateway request keeps the last catalog discovered in the running process.
`PI_OFFLINE=1` disables discovery.
