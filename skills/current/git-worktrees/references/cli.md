# Raw-Git Worktrees CLI v1

Read this before invoking the raw-Git CLI or consuming its JSON. It is a local, same-host/current-user controller; it does not discover harness-native managers.

## Invocation and protocol

```text
uv run --script <skill-dir>/scripts/cli.py <command> [arguments]
```

The root is fixed at `${XDG_DATA_HOME:-~/.local/share}/agents/worktrees`; `XDG_DATA_HOME` selects the standard data-home base, but there is no CLI root, destination, or config override. Normal commands write exactly one JSON object plus newline to stdout. They never write Git/setup output or tracebacks there. `--help` may print argparse help instead.

Success envelope:

```json
{"schema":"git-worktrees/v1","type":"response","ok":true,"command":"...","result":{},"warnings":[]}
```

Expected-error envelope:

```json
{"schema":"git-worktrees/v1","type":"error","ok":false,"command":"...","error":{"code":"snake_case","message":"...","details":{}},"warnings":[]}
```

`schema` is always `git-worktrees/v1`. Treat `ok`, `type`, and exit code as authoritative; parse `result` only when `ok:true`. `error.code` is a stable snake-case classifier, `message` is explanatory text, and `details` is command-specific evidence. Preserve the full response when reporting a failure, but redact capability tokens.

| Exit | Meaning |
| ---: | --- |
| 0 | Success |
| 2 | Usage, input, or controller error |
| 3 | Safe refusal, conflict, or unmet precondition |
| 4 | Git, setup, or runtime error |
| 127 | Git executable unavailable |

## Commands

### `schema`

```text
schema
```

No arguments. `result` publishes the protocol version, fixed root, supported verbs, exit codes, and concise argument/result shapes. Use it for machine-readable discovery; it performs no lifecycle mutation.

### `inspect`

```text
inspect --repo PATH
```

`--repo` is required. This command is read-only: it creates neither controller state nor allocation directories.

`result` reports:

- canonical repository identity and primary worktree path;
- the full `git worktree list --porcelain -z` snapshot: path, HEAD, ref or detached state, and lock/prunable annotations;
- visible allocation-parent safety;
- durable controller-managed leases for the repository; and
- findings

A non-Git, bare, or otherwise unusable repository is a typed successful finding when identity can be determined; otherwise it is an error response. Inspect does not grant lifecycle authority over a discovered worktree.

### `acquire`

```text
acquire --repo PATH --owner ID --session-actor ID --task TEXT --name SLUG \
  --mode new-branch|existing-branch|detached-ephemeral \
  [--base REV] [--branch BRANCH] \
  [--setup-argv JSON_ARRAY]... [--setup-timeout-seconds N]
```

Required arguments:

| Argument | Meaning |
| --- | --- |
| `--repo PATH` | Source non-bare repository. |
| `--owner ID` | Lifecycle owner identity. |
| `--session-actor ID` | Acquiring session/actor identity. |
| `--task TEXT` | Requested task. |
| `--name SLUG` | Lowercase ASCII `^[a-z0-9][a-z0-9-]{0,63}$`. |
| `--mode MODE` | One of the three modes below. |

Mode requirements:

| Mode | Required | Forbidden | Behavior |
| --- | --- | --- | --- |
| `new-branch` | `--base REV` | `--branch` | Creates derived branch `work/<allocated-name>`. |
| `existing-branch` | `--branch BRANCH` | `--base` | Attaches an existing unattached branch. |
| `detached-ephemeral` | `--base REV` | `--branch` | Creates a detached worktree at the base. |

The controller chooses a visible path below `${XDG_DATA_HOME:-~/.local/share}/agents/worktrees/<repo-slug>/`. It allocates `name`, then `name-2`, and so on; a candidate must have no path collision and no attached-branch collision. The caller cannot supply a destination. Repository-slug collisions are disambiguated with a stable six-character SHA-256 prefix.

`--setup-argv` is repeatable. Each value is a JSON nonempty array of nonempty strings, for example `["uv","sync"]`. Arrays run sequentially in the new worktree with no shell. The default `--setup-timeout-seconds` is `600`. Output capture is capped at 64 KiB per stream for each setup command. No setup command runs unless explicitly supplied.

Successful `result` contains a ready lease and returns `capabilities.owner_token` exactly once. Retain that opaque token securely: only its hash is durable, and later responses cannot recover it. A lease becomes ready only after Git re-enumeration and all requested setup succeeds.

Before Git mutation, the controller records a non-ready reservation. Failed creation preserves a `create_failed` lease; failed setup preserves a `setup_failed` lease and actual worktree state. Neither failure triggers automatic retry or cleanup.

### `status`

```text
status --lease-id ID
```

`--lease-id` is required. Read-only. `result` contains the durable lease and fresh observations of path, Git registration, primary status, HEAD, ref, dirtiness, identity match, blockers, and `safe_to_release`. Use this to resolve uncertainty before any requested release.

### `handoff`

```text
handoff --lease-id ID --owner-token TOKEN --actor ID --session-actor ID
```

All arguments are required. The owner capability authorizes creation of one active worker handoff. Successful `result` returns the opaque handoff token exactly once; only its hash is stored. A handoff grants task access, never lifecycle ownership.

### `complete-handoff`

```text
complete-handoff --lease-id ID --handoff-token TOKEN --quiescent
```

All arguments shown are required. `--quiescent` attests that the handoff holder stopped or reaped every task process it started. The controller cannot prove arbitrary external-process quiescence. Successful completion closes the active handoff.

### `release`

```text
release --lease-id ID --owner-token TOKEN --quiescent
```

All arguments shown are required. Release is explicit cleanup, never an automatic finalizer. It requires the owner capability, caller quiescence attestation, and no active handoff.

Before removal, the controller revalidates repository identity, provenance, target path, registration as a linked non-primary worktree, expected ref/mode, and clean status. It removes only with `git worktree remove <path>`; never force; then re-enumerates to confirm absence. Successful release retains a released lease tombstone.

## Safety boundary

The controller serializes its own lifecycle work with a bounded 30-second per-canonical-common-Git lock and durable lease state. It mutates only worktrees it created with `provenance=created-by-lease`.

It refuses rather than repairs when ownership, identity, registration, ref/mode, cleanliness, handoffs, or state are uncertain. In particular, it never adopts, reuses, or removes a consumer, foreign, or pre-existing worktree.

It never force-removes, directly deletes directories, breaks locks, resets, cleans, stashes, prunes, deletes branches, commits, pushes, or performs automatic repair. A dirty target remains intact.

## Recovery

1. Read `ok`, `error`, and exit code; a nonzero result is not permission to repair
2. Preserve the response, worktree, lease, and durable state; redact owner and handoff tokens
3. Use `inspect` for repository-wide read-only discovery or `status` for a known lease
4. Resolve the reported blocker with the original lifecycle authority
5. Native-manager state remains native-managed; never fall back to this CLI after native failure
6. Missing ownership, identity, quiescence, or authority means no lifecycle mutation
