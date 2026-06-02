# Documentation Lookup Cookbook

Use this for efficient Context7 lookup strategy. Keep examples illustrative; do not turn this into framework-specific docs.

## Spend the three-command budget

Default budget per user question:

1. Resolve: `bun x ctx7@latest library <name> "<task-shaped query>" --json`
2. Fetch: `bun x ctx7@latest docs <selectedId> "<same task-shaped query>"`
3. Optional retry/follow-up: only if the first ID or query is clearly off.

Skip step 1 when the user gives an exact Context7 ID:

```text
bun x ctx7@latest docs /fastapi/fastapi "dependency overrides lifespan testing"
```

Spend the retry on a better name, not random fishing:

```text
bun x ctx7@latest library "Next.js" "app router middleware redirect unauthenticated users" --json
bun x ctx7@latest library "@opentelemetry/sdk-trace-base" "span processor exporter resource attributes" --json
```

## Shape the query

Good queries include three things:

- **API surface**: function/type/module/config name.
- **Task/failure mode**: what the user is trying to do or fix.
- **Context discriminator**: language, version, package, runtime, or framework.

Examples:

| Strong                                             | Weak           |
| -------------------------------------------------- | -------------- |
| `"extractor state rejection custom response"`      | `"extractors"` |
| `"v2 TypeAdapter field validator model validator"` | `"validation"` |
| `"reconcile owner references predicates cache"`    | `"controller"` |
| `"allocator comptime error unions build system"`   | `"zig basics"` |
| `"span processor exporter resource attributes"`    | `"telemetry"`  |

Do not send secrets, credentials, personal data, proprietary code, or large source snippets.

## Choose among results

Selection is not “first row wins.” Use the result fields together:

1. **Exact project/package match** beats generic ecosystem hits.
2. **Description relevance** beats raw popularity.
3. **Official docs/manual mirrors** often beat source repos for API surface because they have more snippets and higher benchmark scores.
4. **Repo IDs** can be better for implementation-specific behavior, changelog-ish details, or project internals.
5. **Version-specific IDs** only matter when returned by `library` and relevant to the user’s version.
6. **Zero benchmark** does not make a niche result bad if it is the exact project and alternatives are irrelevant.

Observed ambiguity patterns:

```text
# Same display name, different ecosystems: Go zap, Zig zap, OWASP ZAP.
bun x ctx7@latest library zap "sampling logger cores fields" --json
bun x ctx7@latest library zap "zig http server routes websocket" --json

# Website/manual mirrors can outrank repo IDs for API docs.
bun x ctx7@latest library tokio "select cancellation pinning timeout" --json
bun x ctx7@latest library axum "extractor state rejection custom response" --json
```

If two plausible IDs remain after one retry, ask a targeted clarification instead of guessing.

## Use direct IDs and versions

Use direct IDs when another skill/reference already knows the correct package:

```text
bun x ctx7@latest docs /gin-gonic/gin "middleware chaining context abort"
bun x ctx7@latest docs /haskell-servant/servant "type-level API handlers hoist server"
bun x ctx7@latest docs /kubernetes-sigs/controller-runtime "reconcile owner references predicates cache"
```

For versions:

1. Run `library --json`.
2. Inspect `versions`.
3. Use `/org/project/version` only if Context7 returned that version.
4. If exact version is absent, use the closest relevant ID and say the exact version was not indexed.

## Handle sparse or niche docs

Sparse/niche docs are normal. Do not launder thin evidence into certainty.

Good behavior:

- Retry once with the upstream repo/package name or exact module name.
- Prefer exact niche project over broad ecosystem docs when the user asks about that project.
- If docs are thin, say Context7 coverage is thin and route to repo docs/code search.
- If results are cross-language, add the language/runtime to the query.

Examples:

```text
bun x ctx7@latest library polysemy "haskell interpreters effects final tagless" --json
bun x ctx7@latest library opentelemetry "python span processor exporter resource attributes" --json
bun x ctx7@latest library opentelemetry "dotnet span processor exporter resource attributes" --json
```

## Use JSON vs text deliberately

Use `library --json` when selecting IDs because it exposes ranking fields:

```text
bun x ctx7@latest library pydantic "v2 TypeAdapter field validator model validator" --json
```

Use `docs --json` when you need:

- snippet provenance (`codeId`, `pageId`)
- code vs prose split (`codeSnippets`, `infoSnippets`)
- exact language labels
- enough structure to compare multiple snippets

Use plain `docs` when the next step is simply to answer the user in prose.

## Read result quality signals

Docs output may mix:

- generated APIDOC blocks from Context7
- source docs snippets from GitHub/docs sites
- prose `infoSnippets` with breadcrumbs

Treat generated APIDOC as useful but verify against source snippets when precision matters. Prefer snippets with clear provenance and matching language over generic examples.

## Fast templates

```text
# Resolve then fetch
bun x ctx7@latest library <library> "<api surface> <task/failure> <version/runtime>" --json
bun x ctx7@latest docs <selectedId> "<api surface> <task/failure> <version/runtime>"

# Known ID
bun x ctx7@latest docs /org/project "<api surface> <task/failure> <version/runtime>"

# Structured docs inspection
bun x ctx7@latest docs /org/project "<api surface> <task/failure>" --json
```
