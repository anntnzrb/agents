---
name: effect
description: "Use Effect TypeScript APIs and docs: effect-ts, @effect/*, fibers, layers, schemas, and RPC."
license: AGPL-3.0-or-later
metadata:
  author: anntnzrb

---

# Effect

Effect API questions MUST use live Effect documentation.

Missing `mcporter`: MUST use this Nix prefix:

```text
nix run github:numtide/llm-agents.nix#mcporter --
```

## Workflow

1. Choose the known `effect-doc-links` or `effect-documentation` recipe below and call it directly.

2. Unfamiliar, optional, or rejected arguments: MUST inspect targeted live schema, then retry once:

```text
mcporter --config <agent-config-root>/assets/mcporter.jsonc list effect.<tool> --schema
```

3. Package coverage: MUST inspect live resources first:

```text
mcporter --config <agent-config-root>/assets/mcporter.jsonc resource effect
```

- MCP-resource client: SHOULD use `effect-doc-links`
- Direct documentation text: MUST use `effect-documentation`

```text
mcporter --config <agent-config-root>/assets/mcporter.jsonc call 'effect.effect-doc-links(libraries: ["effect"])'
mcporter --config <agent-config-root>/assets/mcporter.jsonc call 'effect.effect-documentation(libraries: ["effect"])'
```

- Live schema and resources MUST remain authoritative when inspected
- NEVER treat generated links as coverage or health evidence
- MUST inspect content despite MCPorter exit `0`
- MUST disclose embedded errors or broken resources
- Absent/unhealthy coverage: MUST use `context7`, `gh`, or `research`

## Required follow-up reads

|Need|Read|When|
|---|---|---|
|Dated tool/package snapshot|`references/mcporter-tools.md`|Broad package coverage or targeted live-schema failure; not for a known recipe|

## Version safety

- Version-sensitive guidance: MUST inspect manifests, lockfiles, imports
- Project version MUST override conflicting upstream documentation
- MUST state mismatches. NEVER guess

## Engineering checks

- Decode untrusted input once at the edge with the project’s schema boundary; keep domain values typed thereafter
- Model expected failures in the Effect error channel with actionable context; do not hide them in defects or broad catches
- Make resource ownership, interruption, timeout, and cleanup explicit with the project’s scoped patterns
- Test observable success, failure, and interruption behavior deterministically; prefer real or in-memory edges before mocks
- Add layers, services, dependencies, or abstractions only for a concrete boundary or reuse need
