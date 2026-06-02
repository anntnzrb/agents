# Modules and Packaging

Read this file for ESM vs CJS decisions, `package.json` fields, dynamic import, conditional exports, and interop debugging.

## Pick one module story per package

Do not mix ESM and CJS casually. The module system is part of the runtime contract.

### ESM

```js
// math.js
export const add = (a, b) => a + b;
export default class Calculator {}

// consumer.js
import Calculator, { add } from "./math.js";
```

### CJS

```js
// math.cjs
const add = (a, b) => a + b;
module.exports = { add };

// consumer.cjs
const { add } = require("./math.cjs");
```

## `package.json` fields that matter

### `type`

```json
{
  "type": "module"
}
```

In that package:

- `.js` -> ESM
- `.cjs` -> CJS escape hatch

Without `type: module`:

- `.js` -> CJS by default in Node
- `.mjs` -> ESM escape hatch

### `exports`

```json
{
  "exports": {
    ".": "./dist/index.js",
    "./cli": "./dist/cli.js"
  }
}
```

Use `exports` to control public entry points. It also blocks undeclared deep imports, which is usually good.

### `imports`

```json
{
  "imports": {
    "#internal/*": "./src/*.js"
  }
}
```

Useful for internal aliases in Node ESM without pretending they are public package paths.

### `sideEffects`

```json
{
  "sideEffects": false
}
```

Only set this when modules are truly side-effect-free at import time. Otherwise tree shaking will eat required behavior.

## Dynamic import

Use `import()` for optional, environment-specific, or heavy modules.

```js
if (process.env.NODE_ENV !== "production") {
  const { inspect } = await import("node:util");
  console.log(inspect(payload, { depth: 5 }));
}
```

Do not use dynamic import to paper over confused boundaries.

## Interop patterns

### Import CJS from ESM

```js
import legacyPkg from "legacy-pkg";
```

Node synthesizes a default export for many CJS packages. Named imports from CJS are often where pain starts.

### Use `createRequire()` from ESM

```js
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const pkg = require("legacy-pkg");
```

Keep this at edges, not everywhere.

### `__dirname` and `__filename` in ESM

```js
import { fileURLToPath } from "node:url";
import { dirname } from "node:path";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
```

## Resolution rules that bite people

- ESM wants explicit relative file extensions in Node: `./thing.js`, not `./thing`
- `exports` changes what consumers can import
- bundlers may resolve extensionless imports that raw Node will reject
- test runners may emulate ESM imperfectly; respect repo conventions before changing format

## Circular dependencies

Circular imports usually fail at **execution time**.

Symptoms:

- imported binding is `undefined`
- module partially initializes
- class extends `undefined`

Fixes:

- move shared primitives to a third module
- invert the dependency with callbacks / interfaces
- delay one edge with dynamic import only if the dependency is truly optional

## Shipping packages

Start simple:

- one entry point
- one module mode
- explicit exports
- minimal public surface

Reach for dual ESM+CJS only when:

- consumers actually need both
- tooling cannot tolerate one mode
- you are willing to test both paths continuously

## Quick heuristics

- **App code** -> preserve repo convention
- **Greenfield Node** -> ESM by default
- **Interop with old tooling** -> isolate CJS edges
- **Package distribution** -> define exports intentionally and avoid deep-import roulette
- **Optional or heavy dependency** -> dynamic import
