# Background Bash

Overrides `bash` using Pi's own definition and result formatter so the main agent is never blocked
by a long command. A command still running after the threshold (default five seconds) moves to the
background with its process group intact; fast commands return the ordinary Bash result. No
widgets, dependencies, persistent PID adoption, or polling loop are involved.

The short threshold is deliberate. A command that runs long is often the wrong approach (a per-line
shell loop, a scan of a binary); handing control back after five seconds lets the agent judge it
and replace it instead of blocking on it.

## Use

Let Bash run normally, or add `background: true` to start immediately. A backgrounded call returns
Bash's normal result shape: the output so far, the session-local job ID, the full log path, and
the output size, with an instruction to judge the command and stop it if a faster approach exists.
Its exit code describes the acknowledgement, not the still-running command.

When a job exits, its report is sent as a `bg-result` steering message: it reaches a working agent
at its next turn boundary and starts a new turn when the agent is idle. Reports that settle together
are coalesced. A report carries the actual exit code, duration, and head/tail output with exact
omitted byte and newline counts; it reads only both ends of the log, never the whole file. Process
output is fenced as untrusted data, with terminal escape sequences and control bytes removed.

`jobs` accepts `action: "list" | "output" | "kill" | "wait"` and an optional `id`:

- `list`: running and settled jobs with their runtime, output size, command, and log path.
- `output`: requires an ID; optional byte `offset` starts a bounded read. The result's
  `details.offset` and text report the next byte offset. Advance it to read only new bytes.
- `kill`: requires an ID; sends SIGTERM to the process group and SIGKILL after three seconds.
- `wait`: blocks without inference until the named job, or any unconsumed job, settles. Optional
  `timeout` is in seconds, default 30, at most 120; on timeout it returns each job's runtime and
  output size so the agent can re-judge it. It returns early when a user message is queued
  (steering or follow-up); the jobs keep running. Cancellation does not consume a result.

Each result reaches the agent once: a result returned by `wait`, or a job stopped with `kill`, is
not also delivered automatically, and `wait` on an already delivered job returns a short notice
instead of the report.

Foreground commands beginning with `sleep` of five seconds or longer are rejected: use `jobs wait`
when blocked, or do other work while the result is pending.

## Settings and lifetime

Pi's merged settings supply optional `bg.thresholdMs` (how long a command runs in the foreground
before it moves to the background) and `bg.maxJobMs` (hard limit per job). The defaults live in
[`index.ts`](index.ts). Set only values that differ from the defaults; a project
`.pi/settings.json` can override them in trusted projects. Each call reads the merged settings, so a
change applies after sync and `/reload`. This extension never writes settings. Pi's shell path and
command prefix remain respected.

Commands are captured from launch into private temporary logs. Eight live managed commands fill
capacity; further calls use Pi's ordinary foreground executor. Print/JSON/no-UI sessions also use
the ordinary executor, and reject explicit background requests because those sessions may exit
before completion delivery (upstream #10029). Nested calls, such as Bash run from a codemode
script, stay in the foreground because the caller needs the command's own result. Background
execution requires POSIX process groups and an interactive or RPC context with UI support.

Output is written to the log with backpressure, so a fast producer waits on the disk instead of
growing Pi's memory. The hard maximum kills the process group. Session shutdown, including Pi's
SIGTERM and SIGHUP handling, kills active groups, waits for them, and removes the log directory.
SIGKILL of Pi leaves jobs running because no handler can run. Logs and IDs are session-local;
reload/resume never adopts old PIDs. Normal shell exit also cleans up residual descendants in its
group. Commands that deliberately detach into a different process group are outside this ownership
boundary: they keep running, but a job whose shell exited settles once its pipes go quiet even if
such a descendant still holds them.
After publishing, `/reload` or restart Pi to load changes; reload stops existing managed jobs.

## Validate

Run the Pi harness tests from the repository root:

```sh
uv run --script .github/scripts/ci.py harness pi
```

For a live check, drive the installed Pi CLI in RPC mode (`--mode rpc --no-session`) with this
extension loaded via `-e <absolute path to index.ts>` and keep stdin open until the background
completion has been delivered. Check three scenarios in the JSONL events:

1. A wasteful command, such as a per-line `grep` loop over a multi-million-line file, returns after
   five seconds; the agent stops it with `jobs kill` and runs a faster command.
2. A legitimately slow command keeps running while the agent completes other calls.
3. A `background: true` command whose agent ended its turn produces one `bg-result` message that
   starts a new turn.

Afterwards confirm with `pgrep` that no job processes remain.
