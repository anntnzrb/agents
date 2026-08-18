---
name: effect
description: "Use when Effect, effect-ts, Effect v4, @effect/*, Effect Schema, Layers, fibers, services, or runtimes appear."
license: AGPL-3.0-or-later
metadata:
  author: anntnzrb

---

# Effect

Use matching project code, vendored source, installed declarations, and live documentation. Never invent version-sensitive Effect APIs.

## Route the task

- New or materially changed user-owned Effect code: read `references/application-engineering.md`; also load the TypeScript skill when project or toolchain decisions are in scope.
- Focused Effect API question without implementation: inspect project versions and vendored source, then use the live documentation workflow below.
- Existing Effect repository: honor its pinned major version. Do not migrate or mix Effect majors without approval.

## Inspect real source

1. Inspect project manifests, lockfiles, imports, installed exports, and declarations.
2. Inspect `~/src/vendored/github.com/Effect-TS/effect` for implementation, tests, examples, `LLMS.md`, and `MIGRATION.md`.
3. If the checkout is absent or stale, follow the global vendored-source policy to create or fast-forward its lightweight clone.
4. If the checkout revision differs from the project version, state the mismatch and inspect the matching tag or installed package. Never treat current `main` as proof for a pinned release.

Treat vendored repositories as read-only references. Never import from them or edit them as application code.

## Use live Effect documentation

Effect API questions MUST also use live Effect documentation.

Missing `mcporter`: MUST use this Nix prefix:

```text
nix run github:numtide/llm-agents.nix#mcporter --
```

For known core-package requests, call the focused recipe directly:

```text
mcporter --config <agent-config-root>/assets/mcporter.jsonc call 'effect.effect-doc-links(libraries: ["effect"])'
mcporter --config <agent-config-root>/assets/mcporter.jsonc call 'effect.effect-documentation(libraries: ["effect"])'
```

- MCP-resource clients SHOULD use `effect-doc-links`.
- Requests that need documentation text MUST use `effect-documentation`.
- Select only the packages relevant to the question.

Before requesting unfamiliar ecosystem packages, inspect live resources:

```text
mcporter --config <agent-config-root>/assets/mcporter.jsonc resource effect
```

For unfamiliar, optional, or rejected tool arguments, inspect the targeted live schema and retry once:

```text
mcporter --config <agent-config-root>/assets/mcporter.jsonc list effect.<tool> --schema
```

- Live schema and resources MUST remain authoritative when inspected.
- NEVER treat generated links as coverage or health evidence.
- MUST inspect returned content despite MCPorter exit `0`.
- MUST disclose embedded errors or broken resources.
- Missing or unhealthy coverage: MUST use matching vendored source, `context7`, `gh`, or `research`.

## Version safety

- Version-sensitive guidance MUST inspect manifests, lockfiles, imports, exports, and declarations.
- The project version MUST override conflicting vendored `main` or upstream documentation.
- New applications use the current matching v4 channel in `references/application-engineering.md`: RC now, stable v4 after release.
- Existing v3 applications receive matching v3 maintenance guidance; do not silently apply v4 APIs or initiate migration.
- State every material version or source mismatch. Never guess.

## Engineering checks

- Use `Effect.fn("name")` for named Effect functions and `Effect.gen` for local sequential composition.
- Use `Schema.TaggedError` for expected errors in new v4 code.
- Decode untrusted input once at the edge with the project's schema boundary; keep domain values typed thereafter.
- Model expected failures in the Effect error channel with actionable context; do not hide them in defects or broad catches.
- Make resource ownership, interruption, timeout, and cleanup explicit with scoped patterns.
- Test observable success, failure, and interruption deterministically; prefer real or in-memory edges before mocks.
- Add Layers, services, dependencies, or abstractions only for a concrete boundary or reuse need.

## Required follow-up reads

|Need|Read|When|
|---|---|---|
|Bun, TypeScript 7, and Effect v4 application policy|`references/application-engineering.md`|Creating or materially changing user-owned Effect code|
|Dated tool/package snapshot|`references/mcporter-tools.md`|Broad package coverage or targeted live-schema failure; not for a known recipe|
