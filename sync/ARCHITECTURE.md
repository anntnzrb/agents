# Sync architecture

Sync is a Bun + TypeScript + Effect v4 command-line application. It reconciles the agents SSOT
(`~/src/agents`) into harness homes, launch wrappers, and package caches.

## Layout

```
sync/src/
  main.ts            process boundary: assemble Layers and run the CLI
  cli/               command parsing, help text, and exit-code mapping
  domain/            domain values, Schemas, and pure transformations
  platform/          operating-system capability services and live Layers
  services/          application services: environment, planning, state, HTTP, output
  packages/          npm and static release preparation, refresh, pruning, and launch
  jobs/              reconciliation job handlers and dispatch
  programs/          sync, launch, update, and maintenance programs
sync/test/           bun:test suites organized by source area
```

Subpath imports (`#domain/*`, `#platform/*`, ...) are declared in `package.json`. Never use `../` across
top-level `src/` directories.

## Rules

- `domain/` is pure. Values are `Schema.Class` / `Schema.TaggedClass` / `Schema.Struct`; unions are
  `Schema.Union` of tagged members. Pure functions only.
- Every on-disk or network payload is decoded exactly once with `Schema` at the service boundary.
- Every expected failure is a `Schema.TaggedError` declared in the module that owns the capability, with
  the context needed to print the same message the user sees (`sync: <message>` on stderr).
- I/O goes through services only: `FileSystem`, `Path`, `ChildProcessSpawner` from Effect, and the sync
  platform services below. No `node:fs`, `Bun.file`, `process.env`, `console`, `Date.now()`, or
  `fetch` outside a platform Layer.
- Resources (locks, staging directories, child processes, temp files) use `Effect.acquireRelease` and a
  `Scope`. Cleanup must run on success, failure, and interruption.
- Use Effect timeouts for effectful operations and the configured deadlines at process boundaries.
- Use `Effect.fn("Module.name")` for every named effectful function.

## Platform services (`src/platform/`)

| Service              | Capability                                                                                                                                                                   |
| -------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Lock`               | non-blocking exclusive `flock` on a path via `bun:ffi`; scoped acquisition returning `Option`; pid write                                                                     |
| `Links`              | read symlink target (fails when path exists but is not a link), atomic replace via temp + rename                                                                             |
| `Exec`               | replace the process (`process.execve`) after flushing stdout/stderr and restoring default `SIGPIPE`/`SIGXFSZ` dispositions                                                   |
| `Proc`               | run a command in its own session with timeout, combined 10 MiB output cap, process-group kill, executable resolution on PATH; run an attached child that shares the terminal |
| `RunningExecutables` | real paths of executables the current user runs: `/proc/*/exe` on Linux, `lsof` on macOS, `None` when unknown; callers scan once per run                                     |
| `Host`               | platform (`darwin` / `linux`), arch, pid, uid, home, environment snapshot, clock, process liveness                                                                           |

The Posix Layer is the only implementation. Windows is out of scope; the service seam is where it would go.

## Persisted formats

Formats under `~/.local/share/agents/` and `~/.cache/npm-tools/` are part of sync's contract with
wrappers, the machine configuration, and running processes. `domain/` declares each one as a Schema.
