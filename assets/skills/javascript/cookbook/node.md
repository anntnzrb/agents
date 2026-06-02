# Node.js Runtime Patterns

Read this file for filesystem work, streams, processes, worker threads, and practical Node runtime behavior.

## Filesystem with `fs/promises`

```js
import { mkdir, readFile, writeFile } from "node:fs/promises";

await mkdir("./data", { recursive: true });
await writeFile("./data/config.json", JSON.stringify({ ok: true }, null, 2));
const raw = await readFile("./data/config.json", "utf8");
const config = JSON.parse(raw);
```

Prefer async filesystem APIs. Use sync variants only in tiny startup paths, scripts, or tests where blocking is irrelevant.

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

Do not manually concat file paths with `/` when portability matters.

## Streams and pipeline

Use streams when payload size is unknown or large.

```js
import { pipeline } from "node:stream/promises";
import { createReadStream, createWriteStream } from "node:fs";

await pipeline(createReadStream("input.log"), createWriteStream("copy.log"));
```

Use `pipeline()` for composed streams so backpressure and errors behave sanely.

## EventEmitter

Useful for local event fan-out, not for pretending everything is reactive architecture.

```js
import { EventEmitter } from "node:events";

const bus = new EventEmitter();
bus.on("done", (value) => console.log(value));
bus.emit("done", 42);
```

Remember to remove listeners on long-lived objects when lifetimes end.

## Worker threads vs child processes

| Tool             | Use when                                             | Notes                                 |
| ---------------- | ---------------------------------------------------- | ------------------------------------- |
| `worker_threads` | CPU-bound JS work needs parallelism                  | Shares process memory, lower overhead |
| `child_process`  | Need a separate process, shell command, or isolation | Higher overhead, separate runtime     |

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

Prefer `spawn()` for streaming output. Use `exec()` only when the output is small and shell parsing is intentional.

## Process, env, and shutdown

```js
process.on("SIGINT", async () => {
  await shutdown();
  process.exit(0);
});
```

Good defaults:

- validate required env vars at startup
- set timeouts on outbound I/O
- close servers, queues, and DB pools on shutdown
- avoid calling `process.exit()` from deep app logic

## HTTP basics

Use the built-in `fetch` client in modern Node. Reach for native `http` / `https` only when you need low-level control.

For servers, prefer the repo's existing framework. If writing raw Node:

```js
import http from "node:http";

const server = http.createServer((req, res) => {
  res.writeHead(200, { "content-type": "application/json" });
  res.end(JSON.stringify({ ok: true }));
});

server.listen(3000);
```

## Common Node failure patterns

- open handles keep tests or CLIs from exiting
- `exec()` buffers too much output and explodes memory
- giant `readFile()` on logs or blobs when streaming was needed
- unhandled rejections crash late and far from the source
- ESM path helpers are missing because code assumed `__dirname`
