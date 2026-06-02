---
name: effect
description: Effect TypeScript docs via Effect MCP through MCPorter. Use whenever the user mentions effect, effect-ts, @effect/* packages, fibers, layers, runtime, schema, platform, sql, cli, ai, rpc, typeclass, or asks how to use Effect APIs or ecosystem modules. Load the mcporter skill to execute this skill's MCP calls.
license: GPL-3.0-or-later
metadata:
  author: anntnzrb
allowed-tools: ""
---

# Effect MCP

Current docs for `effect` and supported `@effect/*` packages.

## Dependency

Load `mcporter` first. Use its `mcporter` helper.

## Use for

- Questions about `effect` or `effect-ts`
- Questions about imported `@effect/*` packages
- API lookup, examples, setup, migrations, and package selection in the Effect ecosystem
- Terms like fibers, layers, runtime, schema, platform, sql, cli, ai, rpc, vitest, and typeclass

## Flow

1. Confirm the server is live and inspect the tool schemas.

```bash
mcporter list effect --schema
```

2. Inspect local version signals before trusting doc output.

- Check `package.json`, lockfiles, and imports for `effect` / `@effect/*`.
- Default assumption: if the user did not explicitly opt into beta, they want stable guidance.
- Treat `effect@latest` and `effect@beta` as different channels, not interchangeable advice.

3. Normalize requested libraries before any MCP call.

- Intersect requested/imported libraries with the supported list in `reference.md`.
- Never pass unsupported package names to `effect-doc-links` or `effect-documentation`.
- Common unsupported-but-real packages include `@effect/platform-node`, `@effect/platform-bun`, `@effect/platform-browser`, `@effect/opentelemetry`, and `@effect/experimental`.
- If the user's package is unsupported, say so explicitly and fall back. Only fetch adjacent supported docs when they provide useful background, and label them as adjacent context, not direct package docs.

4. Use `effect-doc-links` for light package-to-resource mapping. No full docs.

```bash
mcporter call 'effect.effect-doc-links(libraries: ["effect", "@effect/platform"])' --output json
```

5. Use `effect-documentation` for the actual answer path.

```bash
mcporter call 'effect.effect-documentation(libraries: ["effect"])'
mcporter call 'effect.effect-documentation(libraries: ["effect", "@effect/sql"])'
```

6. Answer from returned docs. Keep package names explicit so core `effect` and ecosystem guidance stay separate.

## Library pick

- Start with `effect` for core APIs, runtime, fibers, layers, and standard library pieces.
- Add `@effect/platform` for platform/runtime integration questions.
- Add one ecosystem package at a time instead of pulling the whole catalog.
- See `reference.md` for the full upstream-supported library list and the exact tool catalog.

## Version policy

- `effect-mcp` returns current docs, not guaranteed stable-channel docs.
- For core `effect`, upstream MCP reads `https://effect.website/llms-full.txt`.
- For several ecosystem packages, upstream MCP reads README files from `Effect-TS/effect` `main`.
- Those sources can include beta, unstable, or ahead-of-latest material.
- Unknown or unsupported libraries can silently degrade to core `effect` docs if you pass them through anyway.
- If the docs and the user's installed versions disagree, trust the user's installed versions.
- If guidance appears to require Effect v4 beta, say so explicitly.
- If the repo already pins `effect@4.0.0-beta.*` or matching beta ecosystem packages, you may discuss v4 APIs, but keep calling them beta and non-default for production.
- Do not recommend v4 beta APIs for production work unless the user explicitly opted into beta or the repo already depends on beta versions.

## Fallback

- If the package or topic is outside upstream coverage, fall back to `context7`, `gh`, or `research`.
- If the MCP response is too thin for the question, corroborate with `context7`, `gh`, or `research`.
- If version/channel ambiguity remains, use npm metadata or repo manifests before giving migration advice.
- For unsupported packages, prefer direct docs or repo manifests over MCP, because MCP may return misleading core `effect` material.
- Do not guess or invent unsupported `@effect/*` APIs.
