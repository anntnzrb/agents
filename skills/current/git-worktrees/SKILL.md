---
name: git-worktrees
description: "Route Git worktree lifecycle safely: consume linked worktrees, select native managers, or use raw-Git leases."
license: AGPL-3.0-or-later
---

# Git Worktrees

Use for an isolated workspace, linked-worktree assignment, parallel task, PR review, experiment, or explicit worktree lifecycle.

## Required follow-up reads

|Need|Read|When|
|---|---|---|
|Exact raw CLI contract|`references/cli.md`|Before invoking this CLI, parsing its JSON, or recovering a raw-CLI lifecycle|

Do not preload the reference for consumer-only or native-manager work.

## Route before acting

Choose one role and one lifecycle authority. Preserve state on ambiguity.

### 1. Consume an existing linked worktree

- Consume the current or explicitly assigned linked worktree in place
- Treat consumer worktrees as read-only by default
- Write only with an explicit assignment binding physical path, common Git directory, and actor/session identity
- Validate that binding through read-only discovery; cwd grants no authority
- Foreign, unassigned, or pre-existing worktrees are consumer-only
- NEVER create, relocate, adopt, reuse, or remove a consumer worktree

### 2. Use a harness-native manager

- Lifecycle requested? First determine whether a harness-native manager claims it
- A native claim for create or remove owns that mutation
- Use exactly one native manager for its claimed lifecycle
- Keep its stable handle and use that manager for later cleanup
- Native-manager failure? Preserve state; NEVER fall back to raw Git or this CLI
- This raw CLI cannot discover native managers. Use harness context, assignment, and native-manager instructions before selecting it

### 3. Use this raw-Git CLI

Use it only when all are true:

- The caller explicitly requests a controller-managed lifecycle
- No native manager claims any requested lifecycle mutation
- The target is a usable non-bare Git repository
- The worktree is not foreign, pre-existing, or consumer-assigned

Read `references/cli.md` first. Invoke only through:

```text
uv run --script <skill-dir>/scripts/cli.py <command> ...
```

Every normal command returns one JSON line on stdout. Parse it; do not infer success from filesystem state.

## Raw-CLI lifecycle

1. `inspect --repo PATH` before every lifecycle decision; it is read-only
2. `acquire` with explicit owner, session actor, task, name, and mode
3. Keep the returned owner capability token secret; it is returned once
4. Use the ready worktree only after successful `acquire`
5. `handoff` before a delegated worker uses the lease; retain its one-time token
6. Workers edit only the assigned ready path; they never own lifecycle
7. `complete-handoff --quiescent` after every handoff holder stops its task processes
8. Check `status` when release eligibility or repository state is uncertain
9. `release --quiescent` only with the owner token, no active handoffs, and an explicitly requested cleanup

`acquire` allocates below `${XDG_DATA_HOME:-~/.local/share}/agents/worktrees`; callers never choose a destination. New branches use `work/<allocated-name>`.

## Hard no-go actions

- NEVER mix native management, this CLI, and direct raw-Git lifecycle mutations
- NEVER use `--force`, direct directory deletion, automatic repair, or stale-lock breaking
- NEVER reset, clean, stash, prune, delete branches, commit, or push as lifecycle work
- NEVER release a dirty, primary, foreign, unregistered, mismatched, or uncertain worktree
- NEVER expose owner or handoff tokens in logs, prompts, task output, or issue text
- NEVER run implicit setup; pass only requested setup argv values

## Failure and recovery

- Nonzero or `ok:false` means preserve evidence and state
- Failed creation or setup retains a durable failed lease; NEVER auto-clean it
- A conflict, timeout, dirty status, or active handoff is a safe refusal, not a repair request
- Re-run read-only `inspect` or `status` to learn current state
- Use the original manager for recovery. Native-managed state stays native-managed
- Cannot establish ownership, identity, quiescence, or manager authority? Stop lifecycle mutation and report the blocker

<critical>
Select a native manager before this CLI; the CLI cannot discover one. Consumer and foreign worktrees are never raw-CLI lifecycle targets. On uncertainty or failure, preserve state rather than repairing it.
</critical>
