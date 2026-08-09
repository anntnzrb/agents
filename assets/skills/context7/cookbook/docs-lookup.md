# Documentation Lookup Cookbook

Use this for efficient Context7 lookup strategy. MCPorter is the primary transport; examples use its configured `context7` server.

## Spend the three-call budget

Default retrieval budget per user question:

1. Resolve with `context7.resolve-library-id`
2. Fetch with `context7.query-docs`
3. Retry only if the first ID or query is clearly wrong

Skip resolution when the user gives an exact Context7 ID:

```text
mcporter --config <agent-config-root>/assets/mcporter.jsonc call context7.query-docs --args '{"libraryId":"/fastapi/fastapi","query":"dependency overrides lifespan testing"}'
```

Spend the retry on a better official name or discriminator, not random fishing:

```text
mcporter --config <agent-config-root>/assets/mcporter.jsonc call context7.resolve-library-id --args '{"libraryName":"Next.js","query":"app router middleware redirect unauthenticated users"}'
mcporter --config <agent-config-root>/assets/mcporter.jsonc call context7.resolve-library-id --args '{"libraryName":"@opentelemetry/sdk-trace-base","query":"span processor exporter resource attributes"}'
```

## Shape the query

Good queries include:

- **API surface**: function, type, module, or configuration name
- **Task or failure mode**: what the user is trying to do or fix
- **Context discriminator**: language, version, package, runtime, or framework

| Strong                                             | Weak           |
| -------------------------------------------------- | -------------- |
| `"extractor state rejection custom response"`      | `"extractors"` |
| `"v2 TypeAdapter field validator model validator"` | `"validation"` |
| `"reconcile owner references predicates cache"`    | `"controller"` |
| `"allocator comptime error unions build system"`   | `"zig basics"` |
| `"span processor exporter resource attributes"`    | `"telemetry"`  |

Do not send secrets, credentials, personal data, proprietary code, or large source snippets.

## Choose among results

Selection is not “first row wins”:

1. Exact project/package match beats generic ecosystem hits
2. Description relevance beats raw popularity
3. Official docs/manual mirrors often beat source repositories for API questions
4. Repository IDs can be better for implementation behavior and project internals
5. Version-specific IDs matter only when returned by resolution and relevant to the request
6. Zero benchmark score does not invalidate an exact niche result

Names can collide across ecosystems. Add language, runtime, or package qualifiers:

```text
mcporter --config <agent-config-root>/assets/mcporter.jsonc call context7.resolve-library-id --args '{"libraryName":"zap","query":"Go sampling logger cores fields"}'
mcporter --config <agent-config-root>/assets/mcporter.jsonc call context7.resolve-library-id --args '{"libraryName":"zap","query":"Zig HTTP server routes websocket"}'
```

If two materially different IDs remain plausible after one retry, ask a targeted clarification.

## Use direct IDs and versions

Use known IDs directly:

```text
mcporter --config <agent-config-root>/assets/mcporter.jsonc call context7.query-docs --args '{"libraryId":"/gin-gonic/gin","query":"middleware chaining context abort"}'
mcporter --config <agent-config-root>/assets/mcporter.jsonc call context7.query-docs --args '{"libraryId":"/haskell-servant/servant","query":"type-level API handlers hoist server"}'
mcporter --config <agent-config-root>/assets/mcporter.jsonc call context7.query-docs --args '{"libraryId":"/kubernetes-sigs/controller-runtime","query":"reconcile owner references predicates cache"}'
```

For versions:

1. Resolve the library
2. Inspect returned versions
3. Use `/org/project/version` only when Context7 returned that version
4. If the exact version is absent, use the closest relevant ID and state that the exact version was not indexed

## Handle sparse or niche docs

Do not launder thin evidence into certainty:

- Retry once with the upstream repository/package or exact module name
- Prefer an exact niche project over a broad ecosystem result
- If coverage remains thin, say so and route to repository docs or code search
- If results cross languages, add the language/runtime discriminator


## Inspect provenance deliberately

MCP output is optimized for direct synthesis and commonly includes source URLs. Treat its observed Markdown shape as data, not a stable schema.

Use source URLs, code language, and surrounding documentation context to compare snippets. Generated APIDOC blocks are useful but weaker than matching source snippets with clear provenance.

## Fast templates

```text
# Resolve
mcporter --config <agent-config-root>/assets/mcporter.jsonc call context7.resolve-library-id --args '{"libraryName":"<library>","query":"<api surface> <task/failure> <version/runtime>"}'

# Fetch
mcporter --config <agent-config-root>/assets/mcporter.jsonc call context7.query-docs --args '{"libraryId":"<selectedId>","query":"<api surface> <task/failure> <version/runtime>"}'

# Known ID
mcporter --config <agent-config-root>/assets/mcporter.jsonc call context7.query-docs --args '{"libraryId":"/org/project","query":"<api surface> <task/failure> <version/runtime>"}'
```
