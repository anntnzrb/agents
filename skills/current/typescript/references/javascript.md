# JavaScript Runtime Mechanics and Interop

Reference for plain JavaScript semantics, runtime APIs (Node.js and browser), event-loop concurrency, and ESM/CJS packaging.

## Table of Contents

1. [Language Semantics and Debugging](#language-semantics-and-debugging)
2. [Concurrency and Event Loop](#concurrency-and-event-loop)
3. [Node.js Runtime Mechanics](#nodejs-runtime-mechanics)
4. [Browser and DOM Runtime Mechanics](#browser-and-dom-runtime-mechanics)
5. [ESM and CJS Packaging and Interop](#esm-and-cjs-packaging-and-interop)
6. [Testing Patterns](#testing-patterns)

---

## Language Semantics and Debugging

### Coercion and Equality

- Use `===` by default. Use `Object.is()` when distinguishing `NaN` from `NaN` or `-0` from `+0`:
  ```js
  Object.is(NaN, NaN); // true (NaN === NaN is false)
  Object.is(-0, +0);   // false (-0 === +0 is true)
  ```
- Falsy values: `false`, `0`, `-0`, `0n`, `""`, `null`, `undefined`, `NaN`.
- Nullish coalescing (`??`) defaults only on `null` and `undefined`. Logical OR (`||`) replaces `0`, `""`, and `false` as well:
  ```js
  const port = config.port ?? 3000;    // preserves 0
  const name = input.name || "guest";  // replaces "" with "guest"
  ```
- Reliable type checks:
  ```js
  typeof value === "string";
  Array.isArray(value);
  value instanceof URL;
  Object.prototype.toString.call(value); // "[object Date]", "[object RegExp]", etc.
  ```

### Scope, Closures, Hoisting, and TDZ

- `var` is function-scoped and hoisted with an initial value of `undefined`.
- `let` and `const` are block-scoped and hoisted into a Temporal Dead Zone (TDZ); accessing them before declaration throws `ReferenceError`.
- Closures capture lexical bindings by reference, not snapshots of their values at creation:
  ```js
  // Bug: loop captures shared var binding
  for (var i = 0; i < 3; i++) {
    setTimeout(() => console.log(i), 0); // logs 3, 3, 3
  }

  // Fix: block-scoped let creates a fresh binding per iteration
  for (let i = 0; i < 3; i++) {
    setTimeout(() => console.log(i), 0); // logs 0, 1, 2
  }
  ```

### `this` Binding and Call Sites

- In standard functions, `this` is determined by how a function is called, not where it is defined:
  - Method call `obj.method()`: `this === obj`.
  - Unbound call `const fn = obj.method; fn()`: `this === undefined` in strict mode or ESM (`globalThis` in sloppy CJS).
  - Explicit binding: `fn.call(ctx, arg1)`, `fn.apply(ctx, [args])`, `fn.bind(ctx)`.
- Arrow functions do not define their own `this`, `arguments`, or `prototype`; they capture the enclosing lexical `this`.
- Common failure: passing an object method directly as a callback (e.g. `emitter.on("event", obj.handler)` or `items.map(obj.transform)`). Fix with an arrow wrapper `(x) => obj.transform(x)` or `.bind(obj)`.

### Prototypes, Classes, and Inheritance

- JavaScript inheritance uses prototype delegation. Property access searches the object instance, then walks its prototype chain (`__proto__` / `Object.getPrototypeOf`) until finding the property or reaching `null`.
- Classes are syntactic sugar over prototype delegation. Methods defined in class bodies live on `Class.prototype`, while class fields (`field = value`) are initialized on each instance.
- Distinguish own properties from prototype properties:
  ```js
  Object.hasOwn(obj, "prop"); // true only if directly on instance
  ```
- Subclassing: `class Child extends Parent`: `super()` must execute in the constructor before accessing `this`.

---

## Concurrency and Event Loop

### Event Loop Execution Order

Execution proceeds in strict phase priority:
1. Synchronous call stack runs to completion.
2. Microtask queue drains completely: `Promise.then`, `queueMicrotask`, `process.nextTick` (Node.js).
3. Macrotask queue executes one task: `setTimeout`, `setInterval`, `setImmediate` (Node.js), I/O callbacks, message events.
4. Microtasks drain again after each macrotask.

```js
console.log("1");
setTimeout(() => console.log("2"), 0);
Promise.resolve().then(() => console.log("3"));
console.log("4");
// Output: 1, 4, 3, 2
```
Microtasks scheduled by other microtasks execute before any macrotask runs.

### Promise Combinators and Loop Serialization

- `Promise.all(tasks)`: rejects immediately on first failure; cancels nothing automatically.
- `Promise.allSettled(tasks)`: collects every outcome (`{ status: "fulfilled", value }` or `{ status: "rejected", reason }`).
- `Promise.race(tasks)`: resolves or rejects as soon as the first promise settles.
- `Promise.any(tasks)`: resolves on first fulfillment; rejects with `AggregateError` if all reject.

Avoid accidental serialization in loops:
```js
// Serial (slow): halts each step on network latency
for (const id of ids) {
  await fetchItem(id);
}

// Concurrent (fast when unbounded concurrency is acceptable):
await Promise.all(ids.map((id) => fetchItem(id)));
```

### Bounded Concurrency Queue

When `Promise.all` risks exhausting file descriptors, sockets, or memory:
```js
async function mapConcurrent(items, limit, worker) {
  const results = new Array(items.length);
  let nextIndex = 0;

  async function run() {
    while (nextIndex < items.length) {
      const idx = nextIndex++;
      results[idx] = await worker(items[idx], idx);
    }
  }

  const poolSize = Math.min(limit, items.length);
  await Promise.all(Array.from({ length: poolSize }, () => run()));
  return results;
}
```

### Cancellation with `AbortController`

Always expose cancellation on long-lived or asynchronous I/O:
```js
async function fetchWithTimeout(url, { signal, timeoutMs = 5000, ...init } = {}) {
  const timeoutSignal = AbortSignal.timeout(timeoutMs);
  const compositeSignal = signal ? AbortSignal.any([signal, timeoutSignal]) : timeoutSignal;

  const response = await fetch(url, { ...init, signal: compositeSignal });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
  }
  return response.json();
}
```

### Async Iterators and Generators

Use async generators when processing streams, pagination, or large datasets without accumulating all entries in memory:
```js
async function* paginate(fetchPage) {
  let cursor;
  do {
    const page = await fetchPage(cursor);
    for (const item of page.items) {
      yield item;
    }
    cursor = page.nextCursor;
  } while (cursor);
}

for await (const record of paginate(loadPage)) {
  processRecord(record);
}
```

---

## Node.js Runtime Mechanics

### Filesystem (`node:fs/promises`)

Prefer async filesystem operations. Use sync operations only in tiny bootstrap scripts or CLI startup where blocking is harmless:
```js
import { mkdir, readFile, writeFile } from "node:fs/promises";

await mkdir("./storage", { recursive: true });
await writeFile("./storage/data.json", JSON.stringify(payload, null, 2), "utf8");
const content = JSON.parse(await readFile("./storage/data.json", "utf8"));
```

### Paths, URLs, and ESM `__dirname`

- Never concatenate file paths with raw `/`. Always use `node:path`.
- In Node ESM, `__dirname` and `__filename` do not exist globally. Derive them from `import.meta.url`:
  ```js
  import { dirname, join } from "node:path";
  import { fileURLToPath } from "node:url";

  const __filename = fileURLToPath(import.meta.url);
  const __dirname = dirname(__filename);
  const configPath = join(__dirname, "config.json");
  ```

### Streams and Pipelines

Buffer sizes must stay bounded. For large files, network transfers, or transformations, use `pipeline` from `node:stream/promises` for backpressure and error propagation:
```js
import { pipeline } from "node:stream/promises";
import { createReadStream, createWriteStream } from "node:fs";
import { createGzip } from "node:zlib";

await pipeline(
  createReadStream("input.tar"),
  createGzip(),
  createWriteStream("input.tar.gz"),
);
```
Avoid manual `.pipe()` chains because they do not forward errors or destroy upstream streams on failure.

### `EventEmitter` Lifecycle

`EventEmitter` retains listener references until removed. In long-lived processes, failing to unregister listeners causes memory leaks and unhandled rejections:
```js
import { EventEmitter } from "node:events";

const bus = new EventEmitter();
const onData = (payload) => handle(payload);

bus.on("data", onData);
// When finished or tearing down:
bus.off("data", onData);
```

### Worker Threads vs Child Processes

- `node:worker_threads`: CPU-bound JavaScript work inside the same OS process with shared memory (`SharedArrayBuffer`) and lower overhead:
  ```js
  import { Worker } from "node:worker_threads";
  const worker = new Worker(new URL("./worker.js", import.meta.url), {
    workerData: { chunk },
  });
  ```
- `node:child_process`: separate OS processes or external binaries. Prefer `spawn` with streaming stdio; avoid `exec` when output can exceed default buffer limits.

### Graceful Shutdown

Clean up connections, sockets, and timers before exit. Avoid calling `process.exit()` deep in library or business logic:
```js
process.on("SIGINT", async () => {
  await server.close();
  await dbPool.end();
  process.exit(0);
});
```

---

## Browser and DOM Runtime Mechanics

### Fetch Error Handling

`fetch()` rejects only on network failures or request aborts. It does not reject on HTTP 4xx or 5xx responses:
```js
const res = await fetch("/api/items");
if (!res.ok) {
  throw new Error(`Request failed with status ${res.status}`);
}
const data = await res.json();
```

### Web Workers

Move heavy CPU computation off the main browser thread to prevent UI freezing:
```js
// main.js
const worker = new Worker(new URL("./worker.js", import.meta.url), { type: "module" });
worker.postMessage({ items });
worker.onmessage = (event) => render(event.data);

// worker.js
self.onmessage = (event) => {
  const result = compute(event.data.items);
  self.postMessage(result);
};
```
Keep message payloads compact to minimize structured clone overhead.

### Storage Choice

| Storage | Access | Capacity | Use Case |
|---|---|---|---|
| `localStorage` | Synchronous, blocks main thread | ~5MB | Small key/value user preferences only |
| `sessionStorage` | Synchronous, blocks main thread | ~5MB | Transient single-tab state |
| `IndexedDB` | Asynchronous, event/Promise based | Hundreds of MBs | Structured offline data, caches, blobs |

Never access `localStorage` in hot render loops.

### DOM Observers

- `IntersectionObserver`: lazy loading images, infinite scroll, visibility tracking.
- `MutationObserver`: observe DOM tree mutations outside caller control.
- Always disconnect observers when DOM components unmount:
  ```js
  const observer = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (entry.isIntersecting) {
        loadImage(entry.target);
        observer.unobserve(entry.target);
      }
    }
  });
  observer.observe(element);
  // On cleanup:
  observer.disconnect();
  ```

### Frame Budget and Scheduling

- Visual animation and DOM sync: `requestAnimationFrame(callback)`.
- Low-priority background work: `requestIdleCallback(callback)`.
- Performance profiling: `performance.mark("start")`, `performance.measure("total", "start", "end")`.

---

## ESM and CJS Packaging and Interop

### File Extensions and Module Mode

- Package module mode is controlled by `package.json` `"type"`:
  - `"type": "module"`: `.js` files are ESM. CommonJS files must use `.cjs`.
  - Without `"type": "module"` (or `"type": "commonjs"`): `.js` files are CommonJS in Node. ESM files must use `.mjs`.

### `package.json` Fields

- `"exports"`: specifies public entrypoints and encapsulates internal files against unauthorized subpath imports:
  ```json
  {
    "exports": {
      ".": "./dist/index.js",
      "./helpers": "./dist/helpers.js"
    }
  }
  ```
- `"imports"`: internal subpath aliases within Node ESM, prefixed with `#`:
  ```json
  {
    "imports": {
      "#utils/*": "./src/utils/*.js"
    }
  }
  ```
- `"sideEffects"`: set to `false` or list of files with side effects to permit bundler dead-code elimination.

### Interop Patterns

- Loading CommonJS from ESM:
  - Default import: `import pkg from "cjs-pkg";` (Node generates a synthetic default export).
  - When named imports from CJS fail, import default and destructure: `import pkg from "cjs-pkg"; const { item } = pkg;`.
  - At dynamic edges where CJS `require` is unavoidable in ESM:
    ```js
    import { createRequire } from "node:module";
    const require = createRequire(import.meta.url);
    const legacy = require("legacy-pkg");
    ```
- Explicit file extensions: Node ESM requires explicit relative file extensions: `import { helper } from "./helper.js";` (never extensionless `./helper`).

### Circular Dependencies

Circular imports fail at module evaluation time. Common symptoms:
- An imported binding is `undefined` at top-level execution.
- Base class is `undefined` when running `class Sub extends Base`.
Fix by extracting shared dependencies into a separate module or inverting control with parameters.

---

## Testing Patterns

### Fake Timers

Use fake timers only when behavior depends strictly on elapsed time:
```js
// Vitest:
vi.useFakeTimers();
debouncedFn();
vi.advanceTimersByTime(200);
expect(fn).toHaveBeenCalledTimes(1);
vi.useRealTimers();

// Jest:
jest.useFakeTimers();
debouncedFn();
jest.advanceTimersByTime(200);
expect(fn).toHaveBeenCalledTimes(1);
jest.useRealTimers();
```

### Testing Library Semantic Query Hierarchy

When testing UI components, query in order of accessibility and user observability:
1. `getByRole` (e.g. `getByRole("button", { name: /submit/i })`)
2. `getByLabelText` (form inputs)
3. `getByText` (non-interactive content)
4. `getByPlaceholderText`
5. `getByTestId` (fallback only when semantic queries are unavailable)
