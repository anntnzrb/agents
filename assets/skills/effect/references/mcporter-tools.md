# Effect MCPorter tool snapshot

- Live schema and resources are authoritative.
- ONLY load this dated snapshot for broad tool comparison, package coverage, or live discovery
  failure.
- NEVER load it before a targeted live schema.
- MUST discard snapshot conflicts when live discovery recovers.

## Snapshot metadata

- Captured: 2026-07-16 (America/Guayaquil)
- MCPorter: `0.12.3`
- Server: `effect` (`Effect MCP`)
- Transport observed: STDIO via `bun x @niklaserik/effect-mcp`
- Server package resolution observed during capture: `@niklaserik/effect-mcp@1.0.7`; the config is
  unpinned, so this may drift independently of this snapshot.
- Inventory: 2 tools

Refresh when drift matters:

```text
mcporter --version
mcporter --config <agent-config-root>/assets/mcporter.jsonc list effect --schema
mcporter --config <agent-config-root>/assets/mcporter.jsonc resource effect
```

If `mcporter` is unavailable on PATH, replace the leading `mcporter` with
`nix run github:numtide/llm-agents.nix#mcporter --`.

- Both tools require one top-level `libraries` string array.
- Input schemas declare no enum, minimum item count, uniqueness, or package validation.
- The declarations expose no output schema.
- NEVER invent response fields. MUST inspect the actual MCPorter result.

## Complete tool inventory

### `effect-documentation`

Live description:

> Fetches and concatenates the latest docs for the specified Effect libraries.

Live signature:

```text
effect-documentation(libraries: string[])
```

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

Live description:

> Returns resource links for the specified libraries so the client can load only what's needed.

Live signature:

```text
effect-doc-links(libraries: string[])
```

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

Observed output contained `effect-docs://...` text. This is not a guaranteed response schema. Read a
returned URI with:

```text
mcporter --config <agent-config-root>/assets/mcporter.jsonc resource effect 'effect-docs://@effect-rpc'
```

## Advertised package coverage

The live resource listing advertised these nine package identifiers at capture time:

| Library input | Resource URI |
| --- | --- |
| `effect` | `effect-docs://effect` |
| `@effect/platform` | `effect-docs://@effect-platform` |
| `@effect/sql` | `effect-docs://@effect-sql` |
| `@effect/vitest` | `effect-docs://@effect-vitest` |
| `@effect/ai` | `effect-docs://@effect-ai` |
| `@effect/cli` | `effect-docs://@effect-cli` |
| `@effect/cluster` | `effect-docs://@effect-cluster` |
| `@effect/rpc` | `effect-docs://@effect-rpc` |
| `@effect/typeclass` | `effect-docs://@effect-typeclass` |

This is advertised coverage, not proof of resource health. The listing duplicated dynamic/static
entries for the same nine libraries.

Snapshot probes found:

- `effect-doc-links` emitted a plausible URI for an invented package.
- `effect-documentation` returned embedded fetch-error text for that package.
- Covered `@effect/platform` returned embedded HTTP `404` text on the capture date.

- MUST validate package coverage against live resources when available.
- MUST inspect content even when MCPorter exits `0`.
- MUST fall back to `context7`, `gh`, or `research` for missing, stale, or broken resources.
- NEVER silently substitute adjacent Effect docs.
- If discovery fails, MUST use only the two recorded tools and exact arguments. NEVER invent fields.
