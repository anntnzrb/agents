---
name: git-worktrees
description: Manage isolated Git worktrees for parallel branches, PR review, experiments, lifecycle, and safe cleanup.
---

# Git Worktrees

Use for isolated Git workspaces, parallel branches, PR review, experiments, existing linked worktrees, or explicit cleanup.

## Decide role before tools

- **Consumer:** use the current or explicitly selected linked worktree in place; read-only by default.
- A native consumer-only detector identifies consumption; it NEVER starts Git lifecycle fallback.
- Consumer mode NEVER creates, relocates, owns, or removes a worktree.
- Writable access to a harness-assigned linked worktree requires an explicit assignment binding physical canonical path, canonical common Git directory, and session/actor identity.
- Validate every binding against read-only discovery; NEVER infer authorization from cwd.
- Unassigned, foreign, or pre-existing worktrees remain consumer/read-only.
- **Owner:** manage an explicitly requested lifecycle under an exclusive lease.
- Workers operate only inside an assigned, ready handed-off lease; workers NEVER manage lifecycle.
- Ask when ownership, retention, setup, or cleanup policy is unclear.

## Select exactly one lifecycle manager

1. Only owner mode needs a lifecycle manager.
2. Identify requested mutations: create, reuse, and/or remove.
3. Discover every native manager claiming a requested mutation for this repository/worktree.
4. Select ONE only when it safely owns the complete requested lifecycle; record its stable identity/handle.
5. Any claim but no complete safe owner? Block, report, and preserve.
6. NEVER mix managers or raw Git; raw Git is allowed only when no manager claims any requested mutation.
7. Native detection without a requested mutation remains consumer-only.
8. After any native lifecycle operation fails, preserve state; NEVER fall back to Git.

## Git fallback: inspect first

- Use raw Git only for a caller-requested managed lifecycle when no native lifecycle manager claims any requested mutation.
- Reject a non-Git directory or bare repository.
- Resolve and normalize canonical root and common Git directory:
  ```text
  git rev-parse --show-toplevel
  git rev-parse --git-common-dir
  git rev-parse --is-bare-repository
  ```
- Resolve relative common-dir output against command cwd, then resolve symlinks to physical absolute paths before identity or containment checks.
- Enumerate before every lifecycle decision:
  ```text
  git worktree list --porcelain -z
  ```
- Derive registered paths, primary path, HEADs, branches, detached state, and linked provenance from porcelain.
- `canonical_root` is repository context, not primary-worktree identity.
- Store and compare the porcelain-derived primary path; NEVER clean up the primary worktree.
- Treat foreign or provenance-unknown pre-existing linked worktrees as consumer-only.
- No native detector? Read-only Git/filesystem discovery MAY resolve canonical root/common Git directory and enumerate porcelain-registered linked worktrees; it grants no lifecycle authority or writable access.

## Controller capability

- **Shared mode:** caller provides an external access-controlled store available to every actor.
- It atomically locks canonical common Git directory; creates/reads/revokes path-keyed leases; verifies cleanup owner; lock spans re-enumeration, create/remove, and lease record/revoke.
- **Fallback mode:** prove one designated orchestrator is sole live raw-Git authority; it serially creates/removes before/after handoffs. Cannot prove it? Refuse lifecycle mutation; read-only only.

## Create safely

- Re-enumerate under the shared lock or serial fallback orchestrator; reject changed path, branch, or ownership assumptions.
- Require explicit `new-branch`, `existing-branch`, or `detached-ephemeral` mode.
- Require a resolved base commit/ref and a validated branch/ref where applicable:
  ```text
  git rev-parse --verify <base-or-ref>^{commit}
  git check-ref-format --branch <branch>
  ```
- New-branch mode requires that `refs/heads/<branch>` does not already exist:
  ```text
  git show-ref --verify --quiet refs/heads/<branch>
  ```
- Existing-branch mode requires a valid existing branch absent from every porcelain record.
- Physically canonicalize the existing parent; accept one validated non-symlink basename; construct an absent absolute target directly beneath it.
- Reject an existing empty target that is a symlink; otherwise it MUST physically resolve directly beneath that canonical parent, be non-primary, unregistered, and outside every worktree. Preserve collisions.
- Create a new writable branch with:
  ```text
  git worktree add -b <branch> <absolute-destination> <base-commit>
  ```
- Attach an eligible existing branch with:
  ```text
  git worktree add <absolute-destination> <branch>
  ```
- Create detached only in explicit ephemeral mode:
  ```text
  git worktree add --detach <absolute-destination> <base-commit>
  ```
- NEVER use `--force`; preserve collisions and report them.
- Re-enumerate before releasing the lock or handing off.

## Lease and handoff

Record a lease containing:

```text
lease_id: <unique identity>
owner: <identity>
session_actor: <session/actor identity>
manager: <native | git | none>; native_handle: <stable identity or null>
canonical_root: <absolute path>
common_git_dir: <absolute physical path>
path: <absolute physical path>
primary_path: <absolute physical path>
ref: <branch or null>
head_sha_at_handoff: <full commit SHA>
mode: <new-branch | existing-branch | detached-ephemeral | consumer>
provenance: <created-by-lease | native-managed-pre-existing | pre-existing-registered>
cleanup_policy: <none | owner-removes-on-explicit-request | native-owner-explicit-request>
ready: <false | true>
```
- Shared mode atomically persists an exclusive lease keyed by common Git directory plus canonical worktree path; reject an active writable lease.
- Fallback mode keeps an in-memory coordination lease owned only by its designated orchestrator.
- Cleanup is permitted only for the shared recorded owner or still-live fallback orchestrator.
- Foreign or provenance-unknown pre-existing leases MUST use `manager: none` and `cleanup_policy: none`.
- A pre-existing native-managed worktree retains `manager: native`, its handle, `provenance: native-managed-pre-existing`, and native explicit cleanup authority.
- Handoff grants workspace access, never lease ownership; include task, manager/handle, cleanup policy, and readiness.
- Workers MAY edit, inspect, and run task-required commands only inside an assigned ready leased path.

## Cleanup and recovery

- Cleanup is explicit only: shared recorded owner or still-live fallback orchestrator; otherwise preserve.
- Use the lease manager/handle: native-managed cleanup MUST use that exact native manager, never raw Git.
- Owner MUST revoke new handoffs, drain and confirm every handoff complete, and stop/reap every task-started terminal, container, and process.
- Cannot prove quiescence? Preserve and report; NEVER remove.
- After quiescence, revalidate root, common Git directory, primary path, target path, ref/null, provenance, and owner/orchestrator identity.
- Report current HEAD and dirtiness; `head_sha_at_handoff` is identity, not an immutable cleanup condition.
- Normal branch progress alone NEVER rejects cleanup.
- Preserve on dirty, primary, unregistered, mismatched, foreign, cancelled, or error state.
- Before raw Git cleanup, confirm target remains a registered linked worktree, not primary.
- Report current HEAD and check dirtiness before Git-managed removal:
  ```text
  git -C <absolute-path> rev-parse HEAD
  git -C <absolute-path> status --porcelain
  ```
- Ask Git to remove a clean matching Git-managed worktree before filesystem action:
  ```text
  git -C <canonical-root> worktree remove <absolute-path>
  ```
- NEVER delete the directory directly; preserve it when removal fails.
- Failed or interrupted creation? Re-enumerate; preserve any registered path and report state.

## Setup and exclusions

- Setup is separate explicit opt-in: run only supplied setup after creation or reuse, before handoff.
- Mark ready only on success; failure reports, preserves, and NEVER hands off.
- NEVER run an implicit project command.
- NEVER copy environments, allocate ports, edit `.gitignore`, or run tests/builds/formatters automatically.
- NEVER reset, clean, stash, prune, force-remove, delete branches, commit, or push as lifecycle work.
- Preserve uncertainty, dirtiness, collisions, and conflicts rather than repairing destructively.
