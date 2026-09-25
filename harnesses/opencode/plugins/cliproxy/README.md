# CLIProxyAPI model discovery

Populates the `cliproxy` provider's source inventory using the OpenCode v2 provider transform API.
Setup reads the `baseURL` plugin option, fetches the gateway inventory and catalog, then registers
a synchronous `editor.add` transform with the provider endpoint and model inventory. Replaying the
transform performs no network requests. The option is the endpoint's single source of truth: sync
renders it from the deployment configuration.

OpenCode 2.0.7 applies configured provider transforms **after** external plugin setup. Reading
`ctx.provider.list()` during setup therefore cannot discover this configured provider. The plugin
contributes its source first; the later configuration supplies its name, runtime package, and API key.

The plugin is referenced as a directory with options from `opencode.jsonc` and
default-exports `Plugin.define({ id, setup })`. Runtime APIs come from `@opencode/plugin` and
`@opencode/schema`, pinned in `harnesses/opencode/package.json`. Models use `Model.Info.default`, v2 capabilities, and tiered costs.

Discovery order per plugin load:

1. `GET {baseURL}/models` lists the gateway's current model ids. `baseURL` comes from the plugin
   options, so no endpoint is duplicated here.
2. `https://models.dev/api.json` supplies limits, pricing, modalities, capability flags, and
   reasoning effort options for ids it knows. Lookups try the exact id, the segment after the last `/`,
   then the same keys with a trailing thinking-level qualifier (`-minimal`, `-low`, `-medium`, `-high`,
   `-max`, `-thinking`) removed, so `gemini-3.8-flash-high` resolves to the catalog's `gemini-3.8-flash`
   row. When several catalog rows share a key, the row with the widest context window wins.
3. Unknown ids fall back to `FALLBACK_LIMIT` (200K context, 32K output). The fallback exists because
   OpenCode disables context compaction for models without a context limit.

Every model ships `variants` so `variant_cycle` (`ctrl+t`) and the variant list work through the proxy.
Effort values come from the catalog row's `reasoning_options` effort list when present (e.g. Gemini Flash
resolves to `minimal/low/medium/high`); otherwise the Responses default ladder
(`none/minimal/low/medium/high/xhigh`) applies. Each variant sets Responses-style settings
(`reasoningEffort`, `reasoningSummary: auto`, `include: reasoning.encrypted_content`), matching what
upstream generates for `@opencode/ai/providers/openai` — the rewrite target of this provider's
`aisdk:@ai-sdk/openai` package. The gateway translates `reasoningEffort` to each upstream's native
thinking control.

Display names carry the upstream pool in parentheses: multi-segment ids (`<pool>/<vendor>/<model>`)
use the id's pool segment, while single-segment OAuth-pool ids fall back to the gateway's `owned_by`
field (e.g. `GPT-6 Astra (openai)`, `Gemini 3.8 Flash (antigravity)`).

The models.dev snapshot is cached for 24 hours at `$XDG_CACHE_HOME/agents/models-dev.json`
(`~/.cache/agents/models-dev.json` by default) and is shared with the pi extension; the cache carries its
own format version and is ignored when that version changes. A failed fetch reuses the cached snapshot;
a failed gateway request leaves the provider's model map unchanged.
