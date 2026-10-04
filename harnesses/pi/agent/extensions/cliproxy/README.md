# CLIProxyAPI provider

Registers the `cliproxy` provider through `pi.registerProvider` and refreshes its catalog through the
`refreshModels` primitive. `sync` replaces `${CLIPROXY_CLIENT_BASE_URL}` with the deployment endpoint.
Types come from the installed `@earendil-works/pi-coding-agent` package (`ExtensionAPI`,
`ProviderModelConfig`); the runtime catalog reads come from `@earendil-works/pi-ai/providers/all`, which
Pi resolves for hosted extensions. The file has no local type declarations and passes `tsc --strict`.

The asynchronous extension factory reads the last discovered catalog before registering the provider.
Pi waits for the factory, so RPC clients see cached models on their first catalog request. A first run
without a cache still needs a network refresh before the full catalog is available.

Discovery order during a network-enabled refresh:

1. `GET {baseUrl}/models` lists the gateway's current model ids.
2. `https://models.dev/api.json` supplies limits, pricing, modalities, and reasoning flags for ids it
   knows. Lookups try the exact id, the segment after the last `/`, then the same keys with a trailing
   thinking-level qualifier (`-minimal`, `-low`, `-medium`, `-high`, `-xhigh`, `-max`, `-thinking`) removed, so
   `gemini-3.8-flash-high` resolves to the catalog's `gemini-3.8-flash` row. When several catalog rows
   share a key, the row with the widest context window wins.
3. Known gateway models absent from models.dev (such as `devin/swe-2`) resolve from static catalog
   overrides before falling back to metadata-free defaults.
4. Gateway `context_length` fills a context limit absent from the metadata catalogs or reported as
   nonpositive. Nonpositive output limits also use the defaults in `index.ts`. Image-model catalog
   entries often carry zero token limits; those values must not invalidate the entire startup cache.

## System One classifiers

The gateway's optional System One facade serves classification at `POST {baseUrl}/systemone`; see
[CLIProxyAPI](../../../../../docs/cliproxyapi.md#system-one-classification).
During a network-enabled refresh, the extension reads `GET {baseUrl}/systemone/models` and registers
the returned allowlisted models as `cliproxy` classifiers with the `typesafe-system-one` API and
Pi's shipped TypeSafe transport. The gateway owns availability in
[gateway.json](../../../../../tools/cliproxyapi/gateway.json). Price, context window, and display
name come from Pi's catalog entry for the facade's upstream provider, OpenRouter, so classifier usage
counts toward session cost.

Classifiers stay out of the chat `/models` list. Discovery runs independently of chat discovery and
honors the same timeout, cancellation, and offline controls. Successful listings, including empty
ones, replace classifier availability. Failed requests retain the last listing. The endpoint-bound,
versioned listing is cached atomically at `$XDG_CACHE_HOME/agents/cliproxy-classifiers-pi.json` and
expires according to `MODELS_CACHE_TTL_MS` in `index.ts`. Startup and cache-only refreshes use that
cache without network access. A first run needs a network refresh to discover classifiers.
A model the installed Pi catalog does not know is skipped. Configure `find.classifier` with the
`cliproxy/` prefix followed by a discovered classifier id.

A request reaches the facade only when the gateway host deploys it; otherwise the gateway answers `404`.

Display names carry the upstream pool in parentheses: multi-segment ids (`<pool>/<vendor>/<model>`)
use the id's pool segment, while single-segment OAuth-pool ids fall back to the gateway's `owned_by`
field (e.g. `GPT-6 Astra (openai)`, `Gemini 3.8 Flash (antigravity)`).

## Per-model request metadata

One provider fronts many upstreams, so a model's request dialect cannot come from the provider or
base URL. Each discovered model instead carries `compat` and `thinkingLevelMap` resolved from pi's
shipped catalog, which already authors them per model:

- The catalog is indexed once per process by model id and by `provider/modelId`. A gateway id resolves
  through progressively shorter `/`-joined suffixes, so `command-code/meta/muse-spark-1.3-contributor`
  reaches the catalog's `meta/muse-spark-1.3-contributor`.
- When several shipped providers publish the same suffix, the provider named as a segment of the
  gateway id wins, so `opencode-go/deepseek-v4-pro` keeps the `opencode-go` dialect.
- Only `openai-completions` models contribute compatibility metadata for Chat Completions requests.
  Models advertised with an Anthropic endpoint use `anthropic-messages` at the gateway origin instead,
  without Chat Completions compatibility flags. This preserves Claude thinking blocks and signatures.
- Models newer than the shipped catalog keep the generic dialect, and their thinking levels come from
  the models.dev `reasoning_options` effort list, which is also why `:max` reaches the wire for them
  instead of clamping to a supported level.

Without this resolution a reasoning request carries `reasoning_effort` only. Models whose upstream
dialect requires a `thinking` field never enable extended thinking, and levels the model does support
are absent from `thinkingLevelMap`, so pi clamps the selected level to the highest mapped one.

The Pi-owned models.dev snapshot is cached at `$XDG_CACHE_HOME/agents/models-dev-pi.json`
(`~/.cache/agents/models-dev-pi.json` by default) and published by atomic replacement. The cache carries
its own format version and is ignored when that version changes. A failed fetch reuses the cached
snapshot. The discovered model catalog is stored separately at
`$XDG_CACHE_HOME/agents/cliproxy-models.json`. It is endpoint-bound, validated and expires according to
the constants in `index.ts`; writes use atomic replacement so simultaneous Pi sessions cannot expose
a partially written file. A failed gateway request retains the cached catalog. Models briefly absent
from successful nonempty listings remain available until the missing-listing threshold is reached,
including across process restarts. Empty listings do not count as removals.

Cache-only refreshes never contact the network. `PI_OFFLINE=1` also disables network discovery.
For the first launch without a cache, use RPC or interactive mode to populate it; print/list modes
may only expose the static fallback catalog until a network refresh has completed.

If a discovered gateway model has no catalog context limit, discovery bypasses the cache TTL and
fetches models.dev again before assigning fallback metadata. Missing-model retries are limited to
one catalog fetch per hour in each running process (including failed fetches); a normal TTL refresh
also counts as an attempt. Known models keep using the cached snapshot. Catalog requests honor the
discovery abort signal. This is demand-driven during provider refresh, not a background timer.

If the selected model still needs a fallback context limit, the extension warns once per model per
extension load in UI sessions, on startup, model selection, or before the next agent run. `/reload`
loads changed extension code; a fresh Pi process also picks it up.

## Transient stream failures

The `message_end` handler normalizes the specific gateway stream-drop errors in `retry.ts` to wording
Pi recognizes as retryable. It only changes failed `cliproxy` assistant messages and leaves already
retryable errors, authentication failures, other providers and successful turns unchanged. Pi owns
retry scheduling and attempt limits; the extension does not start a separate retry loop.

## Validate

Pi's host packages are installed only in the synced home. Run the tests from a copy that links them:

```sh
T=$(mktemp -d); cp -R harnesses/pi/agent/extensions/cliproxy "$T/cliproxy"
ln -s ~/.pi/agent/extensions/node_modules "$T/node_modules"
(cd "$T" && bun test cliproxy/)
git diff --check
```

For runtime checks, invoke the installed Pi binary directly with a separate `PI_CODING_AGENT_DIR`,
not the sync-managed `pi` wrapper. Never pass a temporary `XDG_CACHE_HOME` to a sync-managed launcher:
reconciliation can rewrite shared tool launchers to paths inside that temporary cache.
