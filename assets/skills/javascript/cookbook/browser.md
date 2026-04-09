# Browser Runtime Patterns

Read this file for `fetch`, workers, storage, observers, and browser performance APIs.

## Fetch with timeouts and cancellation

```js
export async function fetchJSON(url, { signal, timeoutMs = 5000, ...init } = {}) {
  const timeout = AbortSignal.timeout(timeoutMs);
  const composite = signal ? AbortSignal.any([signal, timeout]) : timeout;

  const response = await fetch(url, {
    ...init,
    headers: {
      "content-type": "application/json",
      ...init.headers,
    },
    signal: composite,
  });

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }

  return response.json();
}
```

Attach cancellation and timeouts at the boundary. Do not leave user-driven browser work hanging forever.

## Web Workers

Use workers for real CPU-heavy work or large parsing jobs that would block the main thread.

```js
// main.js
const worker = new Worker(new URL("./worker.js", import.meta.url), {
  type: "module",
});

worker.postMessage({ items });
worker.onmessage = (event) => {
  render(event.data);
};
```

```js
// worker.js
self.onmessage = (event) => {
  const result = expensiveTransform(event.data.items);
  self.postMessage(result);
};
```

Keep messages structured and small when possible. Copying giant payloads can erase the win.

## Service workers

Reach for service workers only when offline, cache control, or background sync is part of the task. They are infrastructure, not default browser glue.

## Storage choice

| Need | Use |
| --- | --- |
| tiny sync key/value settings | `localStorage` |
| async structured data, larger datasets | `IndexedDB` |
| transient per-tab state | in-memory state / `sessionStorage` |

`localStorage` is synchronous. Do not use it in hot paths or as a fake database.

## Observers

### Intersection Observer

Good for lazy loading and visibility-based work.

```js
const observer = new IntersectionObserver((entries) => {
  for (const entry of entries) {
    if (entry.isIntersecting) {
      loadImage(entry.target);
      observer.unobserve(entry.target);
    }
  }
});
```

### Mutation Observer

Use it when the DOM truly changes outside your control. If your own app already owns the state, prefer explicit updates.

```js
const observer = new MutationObserver((mutations) => {
  console.log(mutations.length);
});

observer.observe(container, { childList: true, subtree: true });
```

Disconnect observers when the owning view goes away.

## Performance APIs

### Frame-friendly work

- visual updates -> `requestAnimationFrame`
- background-ish idle work -> `requestIdleCallback` only if supported and appropriate
- long CPU tasks -> split work or move to a worker

### Measure before guessing

```js
performance.mark("start");
doWork();
performance.mark("end");
performance.measure("work", "start", "end");
```

Use the Performance panel, allocation timeline, and network tools before rewriting logic blindly.

## Common browser failure patterns

- attaching duplicate event listeners on rerender / remount
- leaving observers, intervals, or workers alive after navigation
- parsing giant JSON on the main thread when a worker or stream was needed
- assuming `fetch` rejects on HTTP 500; it rejects on network failure, not status codes
- relying on `localStorage` for data that needs indexing, transactions, or large size
