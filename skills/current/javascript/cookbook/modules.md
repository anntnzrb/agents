# Modules and Packaging

Scope: ESM/CJS choice, `package.json` `type`/`exports`/`imports`/`sideEffects`, dynamic import, interop, resolution, cycles, and package shipping.

## One module story/package
Do not mix ESM and CJS casually; module system is runtime contract.

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

## Relevant `package.json` fields

### `type`

```json
{
  "type": "module"
}
```

With `type: module`: `.js` → ESM; `.cjs` → CJS escape hatch. Without it: `.js` → CJS by default in Node; `.mjs` → ESM escape hatch.

### `exports`

```json
{
  "exports": {
    ".": "./dist/index.js",
    "./cli": "./dist/cli.js"
  }
}
```

`exports`: control public entry points; block undeclared deep imports (usually good).

### `imports`

```json
{
  "imports": {
    "#internal/*": "./src/*.js"
  }
}
```

`imports`: internal aliases in Node ESM, not public package paths.

### `sideEffects`

```json
{
  "sideEffects": false
}
```

Set `sideEffects: false` only when modules are truly side-effect-free at import time; otherwise tree shaking removes required behavior.

## Dynamic import
Use `import()` for optional, environment-specific, or heavy modules:

```js
if (process.env.NODE_ENV !== "production") {
  const { inspect } = await import("node:util");
  console.log(inspect(payload, { depth: 5 }));
}
```

Do not use dynamic import to paper over confused boundaries.

## Interop

### CJS from ESM

```js
import legacyPkg from "legacy-pkg";
```

Node synthesizes a default export for many CJS packages; named imports from CJS are often where pain starts.

### `createRequire()` from ESM

```js
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const pkg = require("legacy-pkg");
```

Keep `createRequire()` at edges, not everywhere.

### ESM `__dirname` and `__filename`

```js
import { fileURLToPath } from "node:url";
import { dirname } from "node:path";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
```

## Resolution hazards
- Node ESM requires explicit relative file extensions: `./thing.js`, not `./thing`.
- `exports` changes what consumers can import.
- Bundlers may resolve extensionless imports that raw Node rejects.
- Test runners may emulate ESM imperfectly; respect repo conventions before changing format.

## Circular dependencies
Circular imports usually fail at **execution time**.
Symptoms: imported binding `undefined`; partially initialized module; class extends `undefined`.
Fixes:
- Move shared primitives to a third module.
- Invert the dependency with callbacks / interfaces.
- Delay one edge with dynamic import only when the dependency is truly optional.

## Shipping packages
Start simple: one entry point; one module mode; explicit exports; minimal public surface.

Use dual ESM+CJS only when consumers actually need both, tooling cannot tolerate one mode, and you will test both paths continuously.

## Heuristics
- App code → preserve repo convention.
- Greenfield Node → ESM by default.
- Old-tooling interop → isolate CJS edges.
- Package distribution → define exports intentionally; avoid deep-import roulette.
- Optional/heavy dependency → dynamic import.
