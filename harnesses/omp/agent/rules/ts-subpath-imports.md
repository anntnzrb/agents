---
description: Enforce Node/Bun package subpath imports (#*) and prohibit relative directory traversal (../) in TypeScript
condition:
  - "(?:\\bfrom\\s*[\"'](?:\\.\\./)+|\\bimport\\s*\\([\"'](?:\\.\\./)+)"
scope:
  - tool:edit(*.ts)
  - tool:edit(**/*.ts)
  - tool:write(*.ts)
  - tool:write(**/*.ts)
---

Prohibit upward relative directory traversal (`../` or `../../`) in TypeScript imports. Organize internal modules using Node and Bun package subpath imports (`#*`).

## Rules

- NEVER use `../` or `../../` to climb directory trees in TypeScript imports.
- Declare subpath aliases under the `"imports"` field in `package.json` (for runtime resolution) and matching `"paths"` in `tsconfig.json` (for type checking and editor tooling).
- Use `#<module>` or `#<subpath>` specifiers for all internal cross-directory imports (e.g. `#models`, `#registry`, `#scoring`, `#adapters`, `#engine`).
- Sibling imports within the same immediate directory (`./sibling.ts`) are allowed, but cross-directory imports MUST use `#*` subpath aliases.

## Why

- Upward relative traversals tightly couple internal directory hierarchy to file import statements.
- Moving or refactoring a nested file breaks all `../../` paths.
- Package subpath imports (`#*`) are an official ECMAScript, Node.js, and Bun standard supported natively without custom bundler hacks.

## Example

```typescript
// BAD — Brittle relative directory traversal
import type { RawMarketListing } from "../models.ts";
import { registerAdapter } from "../../registry.ts";
import { scoreListing } from "../scoring.ts";

// GOOD — Encapsulated package subpath imports
import type { RawMarketListing } from "#models";
import { registerAdapter } from "#registry";
import { scoreListing } from "#scoring";
```
