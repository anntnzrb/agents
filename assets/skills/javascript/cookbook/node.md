# Node.js Runtime Patterns

Scope: filesystem, streams, processes, worker threads, practical Node runtime behavior.

## Filesystem with `fs/promises`

```js
import { mkdir, readFile, writeFile } from "node:fs/promises";

await mkdir("./data", { recursive: true });
await writeFile("./data/config.json", JSON.stringify({ ok: true }, null, 2));
const raw = await readFile("./data/config.json", "utf8");
const config = JSON.parse(raw);
```

Prefer async filesystem APIs. Sync variants only in tiny startup paths, scripts, or tests where blocking is irrelevant.

### JSON helpers

```js
import { readFile, writeFile } from "node:fs/promises";

export async function readJSON(path) {
  return JSON.parse(await readFile(path, "utf8"));
}

export async function writeJSON(path, value) {
  await writeFile(path, `${JSON.stringify(value, null, 2)}\n`);
}
```

## Paths and URLs

Prefer `node:path` for filesystem paths and `node:url` for module URLs.

```js
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const file = join(process.cwd(), "data", "users.json");
const here = fileURLToPath(import.meta.url);
```

NEVER manually concatenate file paths with `/` when portability matters.

## Streams and pipeline

Unknown or large payloads → streams.

```js
import { pipeline } from "node:stream/promises";
import { createReadStream, createWriteStream } from "node:fs";

await pipeline(createReadStream("input.log"), createWriteStream("copy.log"));
```

Use `pipeline()` for composed streams: sane backpressure and error behavior.

## EventEmitter

Useful for local event fan-out; not for pretending everything is reactive architecture.

```js
import { EventEmitter } from "node:events";

const bus = new EventEmitter();
bus.on("done", (value) => console.log(value));
bus.emit("done", 42);
```

Long-lived objects: remove listeners when lifetimes end.

## Worker threads vs child processes

`worker_threads`: CPU-bound JS parallelism; shared process memory; lower overhead.
`child_process`: separate process, shell command, or isolation; higher overhead; separate runtime.

### Worker thread example

```js
import { Worker } from "node:worker_threads";

const worker = new Worker(new URL("./worker.js", import.meta.url), {
  workerData: { input: 42 },
});
```

Use workers for real CPU work. Do not move trivial tasks to a worker because “parallelism sounds nice.”

### Child process example

```js
import { spawn } from "node:child_process";

const child = spawn("git", ["status"], { stdio: "inherit" });
```

Prefer `spawn()` for streaming output. Use `exec()` only when output is small and shell parsing is intentional.

## Process, env, and shutdown

```js
process.on("SIGINT", async () => {
  await shutdown();
  process.exit(0);
});
```

Defaults:
- Validate required env vars at startup.
- Set timeouts on outbound I/O.
- Close servers, queues, and DB pools on shutdown.
- Avoid calling `process.exit()` from deep app logic.

## HTTP basics

Use built-in `fetch` in modern Node. Native `http` / `https` only for low-level control.

For servers, prefer the repo's existing framework. Raw Node:

```js
import http from "node:http";

const server = http.createServer((req, res) => {
  res.writeHead(200, { "content-type": "application/json" });
  res.end(JSON.stringify({ ok: true }));
});

server.listen(3000);
```

## Common Node failure patterns

- Open handles → tests or CLIs do not exit.
- `exec()` buffers excessive output → memory explosion.
- Giant `readFile()` on logs or blobs → stream instead.
- Unhandled rejections → late crash far from source.
- ESM path helpers missing → code assumed `__dirname`.
