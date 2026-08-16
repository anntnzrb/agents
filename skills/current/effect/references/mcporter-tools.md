# Effect MCPorter tool snapshot

Live schema/resources authoritative when inspected. Use this dated snapshot only for broad package coverage or targeted live-schema failure. The focused skill already provides the two ordinary call recipes. Discard snapshot conflicts when live discovery recovers.

Snapshot: captured `2026-07-16` (`America/Guayaquil`); MCPorter `0.12.3`; server `effect` (`Effect MCP`); observed transport STDIO via `bun x @niklaserik/effect-mcp`; server package resolution observed during capture `@niklaserik/effect-mcp@1.0.7` (config unpinned, so this resolution may drift independently of the snapshot); 2 tools.

Refresh when drift matters:

```text
mcporter --version
mcporter --config <agent-config-root>/assets/mcporter.jsonc list effect.effect-documentation --schema
mcporter --config <agent-config-root>/assets/mcporter.jsonc list effect.effect-doc-links --schema
mcporter --config <agent-config-root>/assets/mcporter.jsonc resource effect
```

If `mcporter` is unavailable on PATH, replace its leading command with `nix run github:numtide/llm-agents.nix#mcporter --`.

Both tools require exactly one top-level `libraries` string array. Schemas declare no enum, minimum item count, uniqueness, or package validation; no output schema is exposed. NEVER invent response fields; MUST inspect the actual MCPorter result.

## Tools

### `effect-documentation`
Fetches and concatenates latest docs for specified Effect libraries.

Signature: `effect-documentation(libraries: string[])`

Exact input schema:

```json
{
  "type": "object",
  "properties": {
    "libraries": {
      "type": "array",
      "items": {
        "type": "string"
      },
      "description": "List of Effect libraries. E.g. effect, @effect/platform, @effect/sql, @effect/vitest"
    }
  },
  "required": [
    "libraries"
  ],
  "additionalProperties": false,
  "$schema": "http://json-schema.org/draft-07/schema#"
}
```

Example:

```text
mcporter --config <agent-config-root>/assets/mcporter.jsonc call 'effect.effect-documentation(libraries: ["effect", "@effect/rpc"])'
```

### `effect-doc-links`
Returns resource links for specified libraries, allowing the client to load only what it needs.

Signature: `effect-doc-links(libraries: string[])`

Exact input schema:

```json
{
  "type": "object",
  "properties": {
    "libraries": {
      "type": "array",
      "items": {
        "type": "string"
      },
      "description": "Effect libraries to reference. E.g. effect, @effect/platform, @effect/sql, @effect/vitest"
    }
  },
  "required": [
    "libraries"
  ],
  "additionalProperties": false,
  "$schema": "http://json-schema.org/draft-07/schema#"
}
```

Example:

```text
mcporter --config <agent-config-root>/assets/mcporter.jsonc call 'effect.effect-doc-links(libraries: ["effect", "@effect/rpc"])'
```

Observed `effect-doc-links` output contained `effect-docs://...` text, but this is not a guaranteed response schema. Read a returned URI with:

```text
mcporter --config <agent-config-root>/assets/mcporter.jsonc resource effect 'effect-docs://@effect-rpc'
```

## Advertised package coverage

At capture time, live resources advertised these mappings (advertised coverage, not proof of resource health; dynamic/static entries duplicated each mapping):

|Library input|Resource URI|
|---|---|
|`effect`|`effect-docs://effect`|
|`@effect/platform`|`effect-docs://@effect-platform`|
|`@effect/sql`|`effect-docs://@effect-sql`|
|`@effect/vitest`|`effect-docs://@effect-vitest`|
|`@effect/ai`|`effect-docs://@effect-ai`|
|`@effect/cli`|`effect-docs://@effect-cli`|
|`@effect/cluster`|`effect-docs://@effect-cluster`|
|`@effect/rpc`|`effect-docs://@effect-rpc`|
|`@effect/typeclass`|`effect-docs://@effect-typeclass`|

Snapshot probes:
- `effect-doc-links` emitted a plausible URI for an invented package.
- `effect-documentation` returned embedded fetch-error text for that package.
- Covered `@effect/platform` returned embedded HTTP `404` text on the capture date.

MUST validate package coverage against live resources when available; MUST inspect content even when MCPorter exits `0`; MUST fall back to `context7`, `gh`, or `research` for missing, stale, or broken resources; NEVER silently substitute adjacent Effect docs. If discovery fails, use only the two recorded tools with exact arguments; NEVER invent fields.
