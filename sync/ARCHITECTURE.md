# Sync architecture

Sync is a Bun + TypeScript + Effect v4 command-line application. It reconciles the agents SSOT
(`~/src/agents`) into harness homes, launch wrappers, and package caches.

## Layout

```
sync/src/
  main.ts            process boundary: BunRuntime.runMain(cli)
  cli/               effect/cli Command tree; help text; exit-code mapping
  domain/            pure TypeScript + Schema. No services, no I/O.
  platform/          Context.Service per OS capability; one Posix Layer each
  services/          app capabilities built on platform: SyncEnv, Http, Registry, Output
  packages/          PackageSource = Npm | StaticRelease: prepare, refresh, prune, launch
  jobs/              one handler per Job tag; exhaustive dispatch
  programs/          runSync, launch, update, job refresh-packages, job npm-cache-clean
sync/test/           bun:test; mirrors src/ layout; support/ holds fixtures and test Layers
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
- Timeouts use `Effect.timeout*`; deadlines are `Duration`s from `domain/Constants.ts`.
- Use `Effect.fn("Module.name")` for every named effectful function.

## Platform services (`src/platform/`)

| Service              | Capability                                                                                                                   |
| -------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| `Lock`               | non-blocking exclusive `flock` on a path via `bun:ffi`; scoped acquisition returning `Option`; pid write                     |
| `Links`              | read symlink target (fails when path exists but is not a link), atomic replace via temp + rename                             |
| `Exec`               | replace the process (`process.execve`) after flushing stdout/stderr                                                          |
| `Proc`               | run a command in its own session with timeout, combined 10 MiB output cap, process-group kill, executable resolution on PATH |
| `RunningExecutables` | real paths of executables the current user runs: `/proc/*/exe` on Linux, `lsof` on macOS, `None` when unknown                |
| `Host`               | platform (`darwin` / `linux`), arch, pid, uid, home, environment snapshot, clock                                             |

The Posix Layer is the only implementation. Windows is out of scope; the service seam is where it would go.

## Persisted formats

Formats under `~/.local/share/agents/` and `~/.cache/npm-tools/` are part of sync's contract with
wrappers, the machine configuration, and running processes. `domain/` declares each one as a Schema.
