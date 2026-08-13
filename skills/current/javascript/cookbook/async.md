# Async, Concurrency, and the Event Loop

Read this file for Promise orchestration, event-loop order, cancellation, async iterators, queueing, and stream-friendly patterns.

## Event loop mental model

Execution order:

1. synchronous stack
2. microtasks (`Promise.then`, `queueMicrotask`)
3. macrotasks (`setTimeout`, I/O callbacks, message events)

```js
console.log("1");
setTimeout(() => console.log("2"), 0);
Promise.resolve().then(() => console.log("3"));
console.log("4");
// 1, 4, 3, 2
```

Use this model when logs look out of order or state updates happen later than expected.

## `async` / `await` for orchestration

```js
async function loadUser(id) {
  const response = await fetch(`/api/users/${id}`);
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return response.json();
}
```

### Error boundaries

Catch where you can add context or recover. Do not swallow errors just to keep the console quiet.

```js
async function loadPage(id) {
  try {
    const [user, posts] = await Promise.all([loadUser(id), loadPosts(id)]);
    return { user, posts };
  } catch (error) {
    throw new Error(
      `loadPage failed: ${error instanceof Error ? error.message : String(error)}`,
    );
  }
}
```

## Promise combinators

Use the combinator that matches the failure policy.

```js
await Promise.all(tasks); // all must succeed
await Promise.allSettled(tasks); // collect every outcome
await Promise.race(tasks); // first settle wins
await Promise.any(tasks); // first success wins
```

### Avoid accidental serialization

```js
// serial
for (const id of ids) {
  await syncUser(id);
}

// parallel
await Promise.all(ids.map((id) => syncUser(id)));
```

If concurrency must be bounded, use a queue.

## Cancellation with `AbortController`

Cancellation should be explicit for user-driven, long-lived, or retrying work.

```js
async function fetchJSON(url, { signal, timeoutMs = 5000 } = {}) {
  const timeout = AbortSignal.timeout(timeoutMs);
  const composite = signal ? AbortSignal.any([signal, timeout]) : timeout;

  const response = await fetch(url, { signal: composite });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}
```

If `AbortSignal.any()` is unavailable in the target runtime, wire multiple controllers manually.

## Async iterators

Use async generators when values arrive over time and buffering is wasteful.

```js
async function* paginate(fetchPage) {
  let cursor;
  for (;;) {
    const page = await fetchPage(cursor);
    for (const item of page.items) {
      yield item;
    }
    if (!page.nextCursor) return;
    cursor = page.nextCursor;
  }
}

for await (const item of paginate(loadPage)) {
  console.log(item);
}
```

## Queueing with bounded concurrency

```js
async function mapConcurrent(items, limit, worker) {
  const results = new Array(items.length);
  let nextIndex = 0;

  async function run() {
    for (;;) {
      const current = nextIndex;
      if (current >= items.length) return;
      nextIndex += 1;
      results[current] = await worker(items[current], current);
    }
  }

  await Promise.all(
    Array.from({ length: Math.min(limit, items.length) }, () => run()),
  );

  return results;
}
```

Reach for this pattern when `Promise.all()` would overwhelm a service, disk, or browser tab.

## Streams and backpressure

Prefer streaming over buffering for large files, uploads, and pipelines.

```js
import { pipeline } from "node:stream/promises";
import { createReadStream, createWriteStream } from "node:fs";
import { createGzip } from "node:zlib";

await pipeline(
  createReadStream("input.txt"),
  createGzip(),
  createWriteStream("output.txt.gz"),
);
```

Use `pipeline()` instead of manual `.pipe()` chains when you want proper error propagation.

## Failure patterns to hunt fast

- missing `await` returns a floating Promise and shifts failures elsewhere
- `Promise.all()` rejects on first failure and discards the rest unless handled
- `Array.prototype.forEach(async () => {})` does not await the inner work
- retry loops without cancellation or jitter become denial-of-service machines
- timers, open sockets, and event listeners keep Node alive after “done"

## Good defaults

- model cancellation early
- keep async call chains shallow and named
- attach timeouts to network and queue work
- prefer bounded concurrency over fire-and-forget bursts
- surface context on errors; keep original cause visible when possible

