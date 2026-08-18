---
name: effect
description: "Use when Effect, effect-ts, Effect v4, @effect/*, Effect Schema, Layers, fibers, services, or runtimes appear."
license: AGPL-3.0-or-later
metadata:
  author: anntnzrb

---

# Effect

Use matching project code, vendored source, installed declarations, and live documentation. Never invent version-sensitive Effect APIs.

## Required reads before editing

For implementation, refactoring, or review, loading this file alone is incomplete. Follow the matching route before the first edit.

- TypeScript implementation, refactoring, or review involving Effect: if the TypeScript skill is not already loaded, load `../typescript/SKILL.md` before editing.
- For Effect code written in TypeScript, the TypeScript skill owns host contracts and language boundaries. This skill owns Effect programs and lifecycle.
- New or materially changed user-owned Effect code: read `references/application-engineering.md` and `references/code-quality.md` before editing.
- Effect code review or refactoring: read `references/code-quality.md` before editing. Inspect matching project and vendored source before prescribing patterns.
- Focused Effect API question without implementation: inspect project versions and vendored source, then use the live documentation workflow below.
- Existing Effect repository: honor its pinned major version. Do not migrate or mix Effect majors without approval.

## Inspect real source

1. Inspect project manifests, lockfiles, imports, installed exports, and declarations.
2. Inspect `~/src/vendored/github.com/Effect-TS/effect` for implementation, tests, examples, `LLMS.md`, and `MIGRATION.md`.
3. If the checkout is absent or stale, follow the global vendored-source policy to create or fast-forward its lightweight clone.
4. If the checkout revision differs from the project version, state the mismatch. Inspect the matching tag or installed package. Never treat current `main` as proof for a pinned release.

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
- Existing v3 applications receive matching v3 maintenance guidance. Do not silently apply v4 APIs or initiate migration.
- State every material version or source mismatch. Never guess.

## Engineering checks

- Before editing, classify changed control flow as pure TypeScript, an Effect program, or a host adapter. Assign sequencing, failure, interruption, and cleanup to one owner.
- Keep one control-flow owner. An Effect-returning function is not `async`. Never use JavaScript `try/catch` around `yield*` or round-trip through Effect runners and Promises.
- Use `Effect.fn("name")` for named Effect functions and `Effect.gen` for local sequential composition. Use `return yield*` for terminal Effects.
- Wrap foreign throws, rejections, and callbacks once with the matching Effect constructor. Preserve cancellation at the boundary.
- Use `Schema.TaggedError` for expected errors in new v4 code. Translate once, recover by tag when possible, and never catch merely to log and rethrow.
- Decode untrusted input once at the edge with the project's schema boundary. Keep domain values typed thereafter.
- Keep pure logic pure. Add Layers, services, state primitives, dependencies, or abstractions only for a concrete capability, lifecycle, concurrency, or replacement need.
- Compose and run at application or host boundaries. Never leave Effects or fibers floating.
- Make resource ownership, interruption, timeout, retry, and cleanup explicit with scoped Effect patterns.
- Run TypeScript and `@effect/tsgo` diagnostics separately. Fix Effect diagnostic findings instead of suppressing them without source-backed justification.
- Treat diagnostics as hazard detection, not proof of idiomatic design. Complete the manual review gate in `references/code-quality.md` before claiming that the code is green or idiomatic.
- Test observable success, typed failure, interruption, and cleanup deterministically. Prefer real or in-memory edges before mocks.

## Required follow-up reads

|Need|Read|When|
|---|---|---|
|TypeScript host contracts and Promise boundaries|`../typescript/SKILL.md`|Implementing, refactoring, or reviewing Effect in TypeScript|
|Bun, TypeScript 7, and Effect v4 application policy|`references/application-engineering.md`|Creating or materially changing user-owned Effect code|
|Effect composition, errors, services, resources, and structural review|`references/code-quality.md`|Creating, materially changing, refactoring, or reviewing Effect code|
|Dated tool/package snapshot|`references/mcporter-tools.md`|Broad package coverage or targeted live-schema failure. Do not read it for a known recipe|
