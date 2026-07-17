---
name: effect
description: "Use Effect TypeScript APIs and docs: effect-ts, @effect/*, fibers, layers, schemas, and RPC."
license: GPL-3.0-or-later
metadata:
  author: anntnzrb
allowed-tools: ""
---

# Effect

Effect API questions MUST use live Effect documentation.

Missing `mcporter`: MUST use this Nix prefix:

```text
nix run github:numtide/llm-agents.nix#mcporter --
```

## Workflow

1. MUST discover live inventory first:

```text
mcporter --config <agent-config-root>/assets/mcporter.jsonc list effect --brief
```

2. Unfamiliar or constrained arguments: MUST inspect targeted live schema:

```text
mcporter --config <agent-config-root>/assets/mcporter.jsonc list effect.<tool> --schema
```

3. Package coverage: MUST inspect live resources first:

```text
mcporter --config <agent-config-root>/assets/mcporter.jsonc resource effect
```

- MCP-resource client: SHOULD use `effect-doc-links`.
- Direct documentation text: MUST use `effect-documentation`.

```text
mcporter --config <agent-config-root>/assets/mcporter.jsonc call 'effect.effect-doc-links(libraries: ["effect"])'
mcporter --config <agent-config-root>/assets/mcporter.jsonc call 'effect.effect-documentation(libraries: ["effect"])'
```

- Live schema and resources MUST remain authoritative.
- NEVER treat generated links as coverage or health evidence.
- MUST inspect content despite MCPorter exit `0`.
- MUST disclose embedded errors or broken resources.
- Absent/unhealthy coverage: MUST use `context7`, `gh`, or `research`.

## Required follow-up reads

| Need | Read | When |
| --- | --- | --- |
| Dated broad tool/package inventory or exact-schema fallback | `references/mcporter-tools.md` | ONLY for broad comparison/package coverage, or when live discovery fails; NEVER before a targeted live schema |

## Version safety

- Version-sensitive guidance: MUST inspect manifests, lockfiles, imports.
- Project version MUST override conflicting upstream documentation.
- MUST state mismatches. NEVER guess.
