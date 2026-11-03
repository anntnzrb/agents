# Sync reference

Sync reconciles the repository at `~/src/agents` with harness homes and installed runtime state on macOS and Linux. The source entrypoint is `sync/src/main.ts`, run with Bun.

## Command syntax

| Invocation | Behavior |
| --- | --- |
| `bun run --cwd sync sync` | Runs a normal reconciliation from source |
| `bun run --cwd sync sync sync` | Runs the same normal reconciliation |
| `~/.local/share/agents/sync-current/sync launch <name> -- <arguments>` | Executes the valid cached package immediately; syncs and installs only when no valid cache exists |
| `~/.local/share/agents/sync-current/sync update` | Fast-forwards the repository and reconciles a new commit; see [Background updates](#background-updates) |
| `~/.local/share/agents/sync-current/sync job refresh-packages` | Refreshes harness and tool packages; see [Maintenance jobs](#maintenance-jobs) |
| `~/.local/share/agents/sync-current/sync job npm-cache-clean` | Runs the scheduled npm cache cleanup; see [Maintenance jobs](#maintenance-jobs) |

Unknown commands and invalid arguments exit with status `2`. A manual sync exits with status `1` after a fatal reconciliation error.

## Reconciliation stages

A manual sync runs these stages in order:

1. Build and validate the sync plan and managed cleanup plan before any bootstrap effects. Malformed input fails without managed writes. Adapter-declared bootstraps run only when their adapter is enabled.
2. Remove stale top-level harness entries that earlier sync runs owned.
3. Install the sync runtime and reconcile source files, managed JSON configuration, shared assets, skills, and generated configuration.
4. Reconcile harness and tool launch wrappers.
5. Record managed harness entries.
6. Run extension-dependency hooks.

The process lock is `~/.local/share/agents/sync-managed/sync.lock`. A second manual sync prints `sync: another sync is already running; skipping` and exits with status `0` without changing targets; `sync update` skips the round silently. A manual sync requests cancellation after 15 minutes and exits with status `124` on timeout. Cancellation gives scoped cleanup (process-group kills, stage removal) 30 seconds; when cleanup outlasts that window, the process still exits `124`. Pre-launch sync runs only without a valid package cache and uses the same budget; a timeout warns and continues to package preparation. The launched harness session is never killed by an expired sync timer.

## File reconciliation

Sync compares a managed file with its source before replacing it. Every copy stamps the source modification time onto the destination, so a destination with the source's size, permission bits, and modification time (to the millisecond) is that copy and is left alone. Any other destination, including one edited in place, is compared by content and replaced when it differs. An unchanged run leaves matching files in place (inode and mtime preserved). Secrets and new state files use mode `0600`; existing state files keep their regular-file mode; executable wrappers use `0755`. Subprocess stdout/stderr share a 10 MiB retained-byte limit; overflow terminates the process group and fails explicitly without parsing partial stdout.

Directory jobs use one of two scopes:

- A tree job makes the destination tree match its source.
- A children job reconciles managed top-level entries inside an existing harness home, preserving unrelated top-level entries while making each managed subdirectory match its source.

Managed JSON configuration jobs copy the source file over the generated file and re-inject only the adapter-declared dot-paths from the previous file. See the [Harness adapter reference](harnesses.md#preserved-json-keys).

Recorded ownership limits cleanup to safe top-level names. Sync preserves unmanaged wrapper conflicts and reports each conflict.

## Missing sources and errors

Most missing source files and directories produce diagnostics but do not fail the run. Invalid committed configuration and hook failures are fatal.

Cold-launch sync treats reconciliation failures as warnings and continues to package preparation. A first launch without a valid package cache fails if preparation cannot install the package.

## Shared settings and gateway endpoints

`agents.toml` holds settings that several harnesses and tools read. Sync validates it before reconciliation and copies it to `~/.local/share/agents/agents.toml` for tools, such as the `autommit` skill, that run outside a sync launch. Unknown keys fail validation.

The readiness job checks `gateway.base_url` + `/models` without authentication. The response must contain a non-empty `data` array. When the endpoint is unavailable, sync preserves the existing harness endpoint files.

Endpoint publication replaces the `${CLIPROXY_CLIENT_BASE_URL}` and `${CLIPROXY_CLIENT_ORIGIN}` placeholders in every configured harness target as one transaction. Each adapter's `cliproxyPreserveTopLevels` names the TOML tables publication keeps from the existing target, such as tables the harness itself owns. A write failure restores every target's previous content and mode.

## Installed runtime

Sync stages `sync/src/`, `sync/package.json`, and `sync/bun.lock` under `~/.local/share/agents/sync-releases/`. It runs `bun install --frozen-lockfile --production`, then `bun build --compile src/main.ts --outfile sync`, and smoke-checks the executable with `--help`. The compiled executable embeds its sources and dependencies, so sync then removes the build inputs. A complete release at `~/.local/share/agents/sync-releases/<releaseId>/` contains only the `sync` executable and the `.release-complete` marker. Sync atomically points `~/.local/share/agents/sync-current` at the release; generated wrappers execute `sync-current/sync`.

The `<releaseId>` is a SHA-256 digest computed over the runtime sources:

- Traverses `sync/src/` recursively, ordering directory entries in deterministic Unicode code-point order.
- Uses forward slashes (`/`) for all relative paths.
- Subdirectories are hashed as `dir:<relativePath>\n` before recursive descent.
- Regular files and symlinks pointing to regular files are hashed as `file:<relativePath>\n` followed by the file content bytes and a trailing `\n`. Directory symlinks are rejected.
- Appends the file contents of `sync/package.json` and `sync/bun.lock` in sequence. The tree traversal skips names listed in `sync/src/domain/EntryNames.ts`.

Releases are staged in `~/.local/share/agents/sync-releases/.stage-<pid>-<nonce>` before publication. Scoped cleanup removes a failed or interrupted stage, leaving active releases intact. Pruning removes unreferenced releases and stale recognized stages without deleting unrecognized user directories or the active release.

## Runtime handoff

Every sync entrypoint except the first install runs from an installed runtime, so a run whose own sync code changed executes every job with the previous code. Manual sync, `sync update`, and cold-launch sync detect when their run published a different `sync-current` release, release the process lock, and reconcile again with the new runtime:

- Manual sync reruns `sync`; its exit status becomes the command's exit status.
- `sync update` reruns `update`, which records the commit once the new runtime reconciles it.
- A cold launch reruns `sync`, then continues to the harness; a failed rerun warns and still launches.

The rerun logs `sync runtime changed; reconciling again with the new runtime` and carries `AGENTS_SYNC_HANDOFF=1` in its environment. A process started with that variable never hands off again, so one change costs at most one extra reconcile. When `sync update` itself runs as a handoff and the runtime changes again, it logs `update: sync runtime changed; reconciling again on the next run` and leaves the commit unrecorded for the next round.

The release fingerprint skips the names listed in `sync/src/domain/EntryNames.ts`; see `sync/src/jobs/RuntimeRelease.ts` for the exact traversal.

## Extension hook state

Extension dependency hooks fingerprint their source tree to skip redundant installation when inputs have not changed. `sync/src/services/HookState.ts` walks the tree and `sync/src/domain/Fingerprint.ts` hashes it. This fingerprint is separate from the runtime release id:

- Produces a SHA-256 digest over the directory tree. A missing root hashes the UTF-8 bytes of `missing`.
- Traverses directory entries in deterministic Unicode code-point order.
- Uses forward slashes (`/`) for all relative paths.
- Subdirectories are hashed as `dir:<relativePath>\n` before recursive descent.
- Regular files and symlinks to regular files are hashed as `file:<relativePath>\n` followed by file content bytes and a trailing `\n`.
- Broken symlinks are hashed as `broken:<relativePath>\n`. Symlinks pointing to directories are rejected with a diagnostic error.
- Skips hidden entries and names ignored by `isIgnoredSyncEntry`, including `node_modules` and bytecode files. Unreadable files have a distinct `file:<relativePath>\nbroken:<relativePath>\n` encoding.

## Launch behavior

Harness and tool wrappers execute a valid `current` cache immediately. Cached launches do not reconcile the SSOT, resolve npm versions, fetch static release manifests, install packages, prune caches, or acquire package locks. An installer holding the package lock does not delay them.

Local SSOT edits to managed configuration, skills, and instructions take effect after an explicit `bun run --cwd sync sync` from the repository or a scheduled `sync update` reconciliation, rather than on the next cached launch. `sync update` reconciles new commits; uncommitted local edits require manual sync. Host-local `.env` defaults are still read at launch. Package updates run through `sync job refresh-packages`.

When no valid cache exists, launch runs best-effort sync if the SSOT is available, then resolves and installs the package synchronously under its cache lock. A failed sync, a busy sync lock, or an unavailable repository does not prevent package preparation. If preparation cannot produce a valid executable, launch fails.

After preparing the harness, the wrapper process is replaced by the harness executable (`execve`). The harness keeps the wrapper's PID, session, process group, and controlling terminal, so terminal resizes, `^C`, job control, and a service manager's `SIGTERM` reach the harness directly, and its exit status is the wrapper's exit status. The Bun runtime ignores `SIGPIPE` and `SIGXFSZ`, and an ignored disposition survives `execve`, so sync restores both to their defaults first; a harness piped into `head` then exits on the closed pipe like any process started from a shell. Captured subprocesses that sync runs itself (npm installs, smoke checks, hooks) still run in their own session so timeouts can kill the whole process group.

Cold launches and package refreshes resolve npm's `latest` tag and install the resolved version into a versioned cache. The cache keeps the current and previous known-good versions, plus any older version whose executable a running process still uses: a long-lived process such as the Amp runner keeps running the version it started from until it restarts, so an update never deletes it underneath that process. Running executables come from `/proc` on Linux and `lsof` on macOS; when they cannot be determined, pruning is skipped for that preparation. Each install stages into `versions/.stage-<pid>-<token>` and removes it on exit; a stage survives only when its installer was killed, and the next prune removes it once that PID is no longer alive. Failed resolution, installation, or smoke checks leave the current known-good cache available.

Cold launches and package refreshes for static releases resolve the adapter's manifest, verify the archive SHA-256, and install the version under the adapter's home-relative install root. The cache keeps the current and previous versions, plus any older version a running process still executes, under the same running-executable rule as npm packages. An installed version is reused without re-downloading. Failed preparation leaves the current cached install available.

## Maintenance jobs

The machine configuration schedules jobs and owns every long-running service, including the update logic of services that run sync-managed wrappers. Run jobs with the installed `~/.local/share/agents/sync-current/sync` executable:

- `sync job refresh-packages`: refreshes npm and static release packages for host-supported harnesses enabled in the SSOT or represented by installed managed wrappers, plus every registered tool launcher. It resolves npm packages from `latest`, verifies and smoke-checks npm installs, verifies static archive checksums and executables, rotates `current`/`previous`, and prunes using the same preparation functions as cold launch. Each package holds its own cache lock across resolution and installation; a busy lock logs a skip without waiting or making a network request. Per-package failures log and continue, keeping the cached version available. The job exits `0` for a successful or skipped round, including no work and partial failures; it exits nonzero only when every package fails or the job itself breaks.

  Per run, the job reads the npm registry configuration once (`npm config get`, so npmrc files, `npm_config_*` variables, and `@scope:registry` overrides apply) and scans running executables once. It refreshes up to four packages concurrently. Each npm package resolves `latest` from the registry's `<registry>/<package>/latest` document, a few kilobytes. On any registry failure, such as authentication, a proxy, or an outage, it falls back to `npm view`, which applies the complete npm configuration. Cold launches resolve with `npm view`. Installation always uses `npm install`.
- `sync job npm-cache-clean`: cleans npm cache (`npm cache clean --force`) while holding exclusive locks on every `<cache>/npm-tools/*/lock` (`<cache>` is `$XDG_CACHE_HOME` or `~/.cache`); skips when busy or if npm is not installed. It exits `0` when there is nothing to do. Static releases lock `<install root>/lock` under their home-relative install root instead.

## Background updates

Every machine converges on `origin/main`: commit and push from any machine, and the others pick the change up on their own. Pushing stays manual; pulling and reconciling are automatic. The git hooks stay pure quality gates, so only commits that passed the `pre-push` tests reach `origin/main`.

The machine configuration schedules `sync update` on each host; this repository installs no updater of its own and assumes nothing about the interval. Each run:

1. Skips the round if another sync holds the process lock; it never waits.
2. Fast-forwards only a clean checkout on `main`. Uncommitted tracked changes, another branch, or local commits missing from `origin/main` mean someone is working there: the checkout is left as is and nothing is merged, stashed, or reset. A failed fetch (offline) keeps the local checkout. Each of these cases logs a `sync: warning: update: …` line naming the blocker (the changed files, the branch, or the local and upstream commit counts), so a host that stops converging shows why in its updater log; an up-to-date run logs nothing. An up-to-date checkout costs one fetch and one `rev-parse`; merge checks run only when `origin/main` moved.
3. Reconciles only when the checked-out commit differs from the last one it reconciled successfully (`sync-managed/update.json`). A failed reconcile is retried on the next run.

The updater runs from the installed runtime, so a pulled change to sync's own code is reconciled first by the previous runtime, which cannot know about anything the new code adds or removes, such as a new harness adapter. When that reconcile installs a new runtime, the updater does not record the commit and reruns `update` with the new runtime in the same round; see [Runtime handoff](#runtime-handoff).

The schedule needs no credentials because `origin` is public over HTTPS.

Inspect or trigger it through the machine configuration's scheduler; see its source-checkout documentation for unit names and logs.

A host stuck behind `origin/main` repeats the same warning on every run. Commit and push the local work, or discard it, and the next run fast-forwards.

## Tool launchers

`TOOL_LAUNCHERS` in `sync/src/domain/ToolLaunchers.ts` lists npm tools that sync launches like harnesses: a wrapper under `~/.local/bin/`, a versioned package cache, and immediate cached launch with best-effort sync only on a cold launch. Tools have no harness home, instruction file, or skills.

`configJobs` in `sync/src/services/Planner.ts` declares the tool configuration files sync publishes and which of them receive the endpoint placeholders.
