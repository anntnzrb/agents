# CLIProxyAPI model discovery

Populates the `cliproxy` provider's source inventory using the OpenCode v2 provider transform API.
It is an Effect plugin (`@opencode/plugin/effect`): the plugin scope owns the transform registration
and the refresh fiber, so unloading or reloading the plugin releases both.
Setup reads the `baseURL` plugin option (a non-empty string; otherwise the plugin logs a warning and
stays inactive), fetches the gateway inventory, and registers a synchronous
`editor.add` transform with the provider endpoint and model inventory. Replaying the transform
performs no network requests. The option is the endpoint's single source of truth: sync renders it
from the deployment configuration.

Configured provider transforms run **after** plugin setup, so `ctx.provider.list()` during setup
cannot discover this configured provider. The plugin contributes its source first; the later
configuration supplies its name, runtime package, and API key.

Discovery:

1. `GET {baseURL}/models` lists the gateway's current model ids at setup and every five minutes.
   Each request, including its body, is bounded at five seconds; the timeout aborts it, so a hung
   gateway delays plugin setup by at most that long. The response envelope is decoded with `Schema`;
   entries without a non-empty string `id` are dropped individually. A failed or empty response keeps
   the last inventory and logs a warning through the Effect logger into the OpenCode server log; a
   changed inventory calls `ctx.provider.reload()`. A gateway that is down at startup therefore gains
   its models on the first successful refresh without a restart.
2. Metadata comes from OpenCode's own models.dev plugin, which adds every catalog provider to the
   provider editor before this transform runs and reloads providers when its snapshot refreshes.
   Deprecated and non-text catalog models are absent. Lookups try the exact id, the segment after the
   last `/`, then the same keys with a trailing thinking-level qualifier (`-minimal`, `-low`, `-medium`,
   `-high`, `-xhigh`, `-max`, `-thinking`) removed, so `gemini-3.8-flash-high` resolves to the
   catalog's `gemini-3.8-flash` row. When several rows share a key, the widest context window wins.
   Matched models copy name, release date, tool support, input modalities, limits, and tiered cost.
3. Unknown ids keep the `Model.Info.default` limits and no cost.

Every model ships `variants` so `variant_cycle` (`ctrl+t`) and the variant list work through the proxy.
Catalog variants are spelled for each source package and mix effort levels with thinking toggles and
token budgets. Effort ids (`none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`) whose settings
name the id carry over; otherwise the Responses default ladder (`none/minimal/low/medium/high/xhigh`)
applies. Each variant sets Responses-style settings (`reasoningEffort`, `reasoningSummary: auto`,
`include: reasoning.encrypted_content`) for `@opencode/ai/providers/openai`, this provider's package.
The gateway translates `reasoningEffort` to each upstream's native thinking control.

Display names carry the upstream pool in parentheses: multi-segment ids (`<pool>/<vendor>/<model>`)
use the id's pool segment, while single-segment OAuth-pool ids fall back to the gateway's `owned_by`
field (e.g. `GPT-6 Astra (openai)`, `Gemini 3.8 Flash (antigravity)`).
