# Background Bash

Overrides `bash` using Pi's own definition and result formatter. Long commands return a job notice
while their process group continues running; fast commands return the ordinary Bash result.
Completions arrive as coalesced `bg-result` follow-ups, never steering messages.
No widgets, dependencies, persistent PID adoption, or polling loop are involved.

## Use

Let Bash run normally, or add `background: true` to start immediately. The result includes the
session-local job ID and full log path. A background acknowledgement has Bash's normal result
shape; its exit code describes the acknowledgement, not the still-running command.
The completion reports the actual exit code, duration, and head/tail output with exact omitted
byte and newline counts. Process output is fenced as untrusted data.

`jobs` accepts `action: "list" | "output" | "kill" | "wait"` and an optional `id`:

- `list`: running and settled jobs in this extension runtime.
- `output`: requires an ID; optional byte `offset` starts a bounded read. The result's
  `details.offset` and text report the next byte offset. Advance it to read only new bytes.
- `kill`: requires an ID; sends SIGTERM to the process group and SIGKILL after three seconds.
- `wait`: blocks without inference until the named job, or any unconsumed job, settles. It returns
  early when a user message is queued (steering or follow-up), so waiting never holds the user off;
  the jobs keep running.
  Optional `timeout` is in seconds, bounded to ten minutes. Cancellation does not consume a result.
  A result returned by wait, or a job stopped with `kill`, is not also delivered automatically.

Automatic delivery happens only between runs: completions that land while the agent is working are
held until Pi reports `agent_settled`, then sent as one follow-up that starts a new turn. A follow-up
queued mid-run cannot be withdrawn, so delivering earlier would duplicate a result that `wait`
reads in the same run.

Foreground commands beginning with `sleep` of five seconds or longer are rejected: use `jobs wait`
when blocked, or do other work while automatic delivery is pending.

## Settings and lifetime

Pi's merged settings supply optional `bg.thresholdMs` (how long a command runs in the foreground
before it moves to the background) and `bg.maxJobMs` (hard limit per job). The defaults live in
[`index.ts`](index.ts); this repository overrides the threshold in
[`../../settings.json`](../../settings.json). Set only values that differ from the defaults; a
project `.pi/settings.json` can override them in trusted projects. Each call reads the merged
settings, so a change applies after sync and `/reload`. This extension never writes settings. Pi's shell path and command prefix remain respected.

Commands are captured from launch into private temporary logs. Eight live managed commands fill
capacity; further calls use Pi's ordinary foreground executor. Print/JSON/no-UI sessions also
use the ordinary executor, and reject explicit background requests because those sessions may
exit before completion delivery (upstream #10029). Background execution requires POSIX process
groups and an interactive or RPC context with UI support.

The hard maximum kills the process group. Session shutdown kills active groups, waits for process
closure, and removes the log directory. Logs and IDs are session-local; reload/resume never adopts
old PIDs. Normal shell exit also cleans up residual descendants in its group. Commands that
deliberately detach into a different process group are outside this ownership boundary.
After publishing, `/reload` or restart Pi to load changes; reload stops existing managed jobs.

## Validate

From the repository root, use installed host packages without modifying the synced home:

```sh
T=$(mktemp -d)
cp -R harnesses/pi/agent/extensions/bg "$T/bg"
ln -s ~/.pi/agent/extensions/node_modules "$T/node_modules"
(cd "$T" && bun test bg/)
git diff --check
```

For a live check, invoke the installed Pi CLI directly (not a sync-managed launch wrapper), with
a separate `PI_CODING_AGENT_DIR` containing the provider configuration. Load the absolute path to
`index.ts` using `--no-extensions -e`, `--no-session --mode rpc`, and tools `bash,jobs`.
Keep stdin open: run `echo start; sleep 10; echo done`, then another short command after the
background notice. Inspect JSONL for the five-second Bash acknowledgement, intervening work,
one `bg-result`, and its triggered assistant response. Close stdin for orderly shutdown and
check the recorded PIDs with `ps` and `process.kill(pid, 0)`.
