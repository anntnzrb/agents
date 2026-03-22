# Effect MCP Reference

## Server

- MC Porter server name: `effect`
- Launcher: `bun x @niklaserik/effect-mcp`
- Upstream package: `@niklaserik/effect-mcp`

## Version channel notes

- Observed npm channels during research:
  - `effect@latest` -> `3.21.0`
  - `effect@beta` -> `4.0.0-beta.36`
  - `@effect/platform@latest` -> `0.96.0`
  - `@effect/platform@latest` peers on `effect ^3.21.0`
- Additional repo-shape checks:
  - `@effect/platform-node@latest` -> `0.106.0`
  - `@effect/platform-node@latest` peers on `effect ^3.21.0`
  - `@effect/platform-node@4.0.0-beta.35` peers on `effect ^4.0.0-beta.35`
- The beta core package points at `Effect-TS/effect-smol`, described upstream as "Core libraries and experimental work for Effect v4".
- Treat Effect v4 guidance as beta/opt-in unless the user's repo or request clearly targets it.

## Tool catalog

### `effect-documentation`

Fetch and concatenate current docs for the selected Effect libraries.

- Required argument: `libraries: string[]`
- Example:

```bash
mcporter call 'effect.effect-documentation(libraries: ["effect"])'
mcporter call 'effect.effect-documentation(libraries: ["effect", "@effect/platform"])'
```

### `effect-doc-links`

Return Effect MCP resource URIs for the selected libraries without embedding the full docs text.

- Required argument: `libraries: string[]`
- Example:

```bash
mcporter call 'effect.effect-doc-links(libraries: ["effect", "@effect/platform"])' --output json
```

## Supported libraries

- `effect`
- `@effect/platform`
- `@effect/sql`
- `@effect/vitest`
- `@effect/ai`
- `@effect/cli`
- `@effect/cluster`
- `@effect/rpc`
- `@effect/typeclass`

## Unsupported library safety gate

Do not pass unsupported libraries to the MCP tools.

- The upstream server accepts arbitrary strings.
- For unknown libraries, it can still emit plausible resource URIs.
- Worse: `effect-documentation` can silently fall back to full core `effect` docs for unsupported libraries.

Known unsupported examples encountered during validation:

- `@effect/platform-node`
- `@effect/platform-bun`
- `@effect/platform-browser`
- `@effect/opentelemetry`
- `@effect/experimental`

Safe rule:

- First check whether the requested package is in the supported library list above.
- If not, do not call `effect.effect-doc-links(...)` or `effect.effect-documentation(...)` with that package name.
- Fall back to `context7`, `gh`, or `research`.
- If useful, fetch nearby supported docs like `effect` or `@effect/platform`, but label them as adjacent context only.

## Resource URIs

The upstream server also exposes resources.

- Template: `effect-docs://{libId}`
- Examples:
  - `effect-docs://effect`
  - `effect-docs://@effect-platform`
  - `effect-docs://@effect-sql`

For this skill, prefer tool calls through MC Porter. Keep resource URIs as reference-only unless you specifically need them.

## Upstream doc source behavior

- Core `effect` docs come from `https://effect.website/llms-full.txt`
- `@effect/platform`, `@effect/sql`, `@effect/vitest`, `@effect/ai`, `@effect/cli`, and `@effect/cluster` come from README files on `Effect-TS/effect` `main`
- `@effect/typeclass` comes from `Effect-TS/typeclass` `main`
- This means MCP output can reflect current or beta-adjacent upstream state rather than the user's installed stable versions
- It also means unsupported names can return misleading core docs instead of a hard error

## Notes

- Run `mcporter list effect --schema` to inspect the live server and current schemas.
- If a requested package is not in the supported library list, use `context7`, `gh`, or `research`.
- If the docs answer is incomplete, corroborate with `context7`, `gh`, or `research` instead of extrapolating.
- For production users who did not opt into beta, bias to stable-channel guidance and call out any suspected v4-only API surface.
