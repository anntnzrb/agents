---
description: Prohibit duplicate schema validation libraries (zod, valibot, yup, joi, arktype) when Effect Schema is in use
condition:
  - "(?:\\bfrom\\s*[\"'](?:zod|valibot|yup|joi|arktype)[\"']|\\bimport\\s*\\([\"'](?:zod|valibot|yup|joi|arktype)[\"'])"
scope:
  - tool:edit(*.ts)
  - tool:edit(**/*.ts)
  - tool:write(*.ts)
  - tool:write(**/*.ts)
---

Do not stack secondary schema or validation libraries (`zod`, `valibot`, `yup`, `joi`, `arktype`) in codebases that use `effect`. Use `effect/Schema` (or `Schema` from `effect`) exclusively.

## Rules

- NEVER import `zod`, `valibot`, `yup`, `joi`, or `arktype` in packages or modules where `effect` is installed.
- Model all domain data structures, runtime decoders, wire contracts, and discriminated unions using `Schema.Struct`, `Schema.Literals`, `Schema.Union`, `Schema.Array`, and `Schema.TaggedError`.
- For static TypeScript types, derive them directly using dual exports (`export type X = typeof X.Type;` or `export type X = Schema.Schema.Type<typeof X>;`).
- If an external library requires a JSON Schema, convert the Effect schema to JSON Schema or pass schema objects directly rather than pulling in `zod`.

## Why

- Duplicating validation libraries bloats package bundles, creates conflicting runtime decoders, and fractures error channel handling.
- Effect Schema integrates natively with Effect pipelines, fibers, and typed error channels (`ParseResult.ParseError`), while third-party validators require awkward try/catch bridging.

## Example

```typescript
// BAD — Duplicating Zod beside Effect
import { z } from "zod";
import { Effect } from "effect";

const UserZod = z.object({ id: z.string(), score: z.number() });

// GOOD — Pure Effect Schema v4
import { Schema } from "effect";

export const User = Schema.Struct({
  id: Schema.String,
  score: Schema.Number,
});
export type User = typeof User.Type;
```
