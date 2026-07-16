---
name: effect
description: "Use Effect TypeScript APIs and docs: effect-ts, @effect/*, fibers, layers, schemas, and RPC."
license: GPL-3.0-or-later
metadata:
  author: anntnzrb
allowed-tools: ""
---

# Effect

Use live Effect documentation for questions about `effect` and imported `@effect/*` packages.

If `mcporter` is not on PATH, replace the leading `mcporter` in each command below with `nix run github:numtide/llm-agents.nix#mcporter --`.
## Workflow

1. Confirm the server and discover its current tools:

```text
mcporter list effect --brief
```

2. Inspect only the tool needed for an unfamiliar or constraint-sensitive request:

```text
mcporter list effect.<tool> --schema
```

3. For a requested library, use `effect-doc-links` to find focused resources. Use
`effect-documentation` only when the answer needs the documentation content:

```text
mcporter call 'effect.effect-doc-links(libraries: ["effect"])'
mcporter call 'effect.effect-documentation(libraries: ["effect"])'
```

Use the literal server and tool names above. Do not maintain or rely on a static package or tool
catalog; the live schema is authoritative.

Do not pass package names through blindly: if the live response does not cover the requested package,
use `context7`, `gh`, or `research` instead of presenting adjacent docs as direct coverage.
Inspect returned content, not just the exit status; if MCP reports an error or broken resource despite exit 0, use `context7`, `gh`, or `research` and disclose the failure.

## Version safety

Check the project's manifest, lockfile, and imports before recommending version-sensitive APIs. Treat
returned documentation as current upstream material; when it conflicts with the installed version,
follow the project and state the mismatch rather than guessing.
