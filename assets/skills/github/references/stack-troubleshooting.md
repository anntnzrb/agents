# Stacked pull request troubleshooting

**Covers:** dirty trees, conflicts, divergence, rollback, locks, interrupted sessions,
merge ancestry, pruning/unstacking, external managers, signatures, partial writes,
and preview/document drift.

**Safe default:** stop at uncertainty, preserve the evidence and current state, and
re-read local/remote JSON before choosing a recovery. Never auto-repair, force, prune,
break a lock, choose local/remote truth, or silently fall back to ordinary PRs.

**Write boundary:** conflict resolution, rebase continue/abort, force-with-lease
push, stack unstack/prune, branch deletion, PR retarget/merge, and API recovery are
writes. Require explicit authorization and the owning manager at each boundary.

**Adjacent handoff:** use `stack-commands.md` for command/version/exit semantics,
`stack-design.md` for graph and manager ownership, `git-worktrees` for worktree
lifecycle, `commit` for staging/history, `gh-contrib` for contribution policy, and
`api.md` for custom endpoint recovery.

## First response to any failure

1. Record command, target host/repository, branch/PR/stack identifiers, exit code,
   stdout, stderr, and whether any write was attempted.
2. Read-only inspect `git status`, current branch/worktree/rebase state, remotes,
   `gh stack view --json`, relevant PRs/checks, and remote branch tips.
3. Determine whether the operation is local-only, remote-only, or mixed. Assume a
   mixed operation may have partially landed until every affected object is re-read.
4. Do not retry a push, POST, merge, unstack, prune, or dispatch just because output
   looks incomplete. Compare stable IDs/tips first.

## Dirty tree and worktree ownership

`init`, `add`, `checkout`, `rebase`, `sync`, and `modify` may require a clean tree or
may change the current branch. If uncommitted changes exist:

- Do not clean, reset, stash, commit, or move them without an explicit plan and the
  owning `commit`/`git-worktrees` authority.
- Verify whether the checkout is assigned, consumer/foreign, or native-manager-owned
  A current directory is not permission to rewrite it.
- Report the dirty paths and stop the stack mutation. Do not hide the state with a
  new branch or force option.

## Rebase conflicts and recovery

For `gh stack rebase`, `sync`, or a cascading operation:

1. Preserve the conflict markers and operation metadata. Inspect conflicted files and
   `git status`; do not run an unrelated rebase.
2. The layer owner resolves the intended content, stages exactly the resolution via
   `commit` policy, then runs `gh stack rebase --continue` (or the installed command's
   documented continue form).
3. If the operation should be abandoned, run `gh stack rebase --abort` only after
   authorization and ownership are clear. Re-read every branch tip and
   `gh stack view --json` afterward.
4. A post-rebase push uses force-with-lease, never `--force`. If a lease fails, stop;
   fetch/read the remote and resolve the divergence instead of overwriting it.

Squash/rebase merges can change ancestry and cause the old bottom branch tip not to
be a simple ancestor. Use the documented stack rebase/`--onto` behavior after a
merged lower layer; do not manually reset branches to make a graph appear linear.
Refresh base/head and checks for every upstack PR.

## Sync divergence and rollback

`sync` can adopt clean remote-ahead additions, but a true local/remote divergence is
not a license to choose a source of truth. In noninteractive mode, documented behavior
is an abort/no-op without pushing or updating PRs; a successful exit can therefore
mean "nothing changed," not "synced."

- Re-read local and remote stack composition, branch tips, and uncommitted state
- Present the competing layer maps and ask the owning user/manager to choose remote,
  local recreation, or cancellation. Do not delete the remote stack automatically.
- If a rebase conflict occurs during sync, expect restoration of branches to their
  original state; verify instead of assuming rollback.
- `--prune` deletes local branches for merged PRs. Never enable it while diagnosing
  divergence, unknown branch ownership, or a dirty worktree. Re-read local refs after
  an authorized prune.

## Locks and interrupted TUI sessions

A stack lock or exit `8` means another process may be writing. Do not break lock files,
kill an unknown process, or run a second stack command. Identify the owning process/
session through the installed tool's read-only status, coordinate with its owner, and
retry only after the lock is released.

An interrupted `modify` session or exit `10` requires the documented recovery path.
Preserve the session metadata; use `gh stack modify --continue` only after conflicts
are resolved and staged, or `gh stack modify --abort` to restore the prior state.
Do not open a second interactive TUI or hand-edit branch metadata while recovery is
pending.

## Multiple stacks and ambiguous identifiers

A branch can appear in multiple stacks; exit `6` requires explicit disambiguation.
A bare number can be a stack number or PR number. Use an explicit stack/PR URL or
read-only `view` result, not positional guesswork. If a branch is not in a stack
(exit `2`), inspect local tracking and remote PR stack membership before adding it.
Do not create a new stack merely because local metadata is missing.

## External managers and worktrees

Jujutsu, Sapling, git-town, GitButler, native harness managers, and linked worktrees
may own branch movement or history. Determine the owner before `checkout`, `rebase`,
`push`, `link`, or `unstack`:

- Use `gh stack link` for remote stack association when another local manager owns
  branches; it does not create local tracking and may still push/create/retarget PRs.
- Do not mix `gh stack` local rewrites with GitButler or raw-Git writes. Hand staging/
  commits to `commit` and lifecycle to `git-worktrees`.
- Do not adopt, delete, relocate, or reset a consumer/foreign worktree. Preserve it
  and report the ownership blocker.

## Unstack, prune, and partial writes

`unstack` removes remote stack association and/or local tracking; it does not imply
branch or PR deletion. Merged, merging, or queued PRs may remain stacked. `--local`
changes only local tracking. Verify the requested boundary before authorizing.

Remote operations are not uniformly atomic:

- `submit` pushes, creates/updates PRs, then links the stack; an intermediate failure
  can leave branches/PRs without a complete stack.
- `push` can update earlier branches while a later force-with-lease fails
- `link` can push and create/retarget multiple PRs before a later validation failure
- `merge --yes` is all-or-nothing for direct stack merging, but a merge queue is
  asynchronous and may process selected PRs in groups.

After any partial result, inventory each branch, PR, and stack object and resume only
from the remaining explicit state. Never rerun the entire operation blindly.

## Signatures and provenance

Rebases, cherry-picks, squash merges, and GitHub-generated merge commits can alter
commit IDs, committer identity, or signature verification. Preserve author/committer
and signed-state requirements from repository policy. Do not claim a rebased commit
retains the original signature without checking the new object. Use `gh api` or the
repository's documented verification command only for a deliberate read.

## Preview and documentation drift

Stacked PRs and `gh stack` are public preview. Installed `gh stack <command> --help`
and current official docs outrank this reference. Flags, exit codes, API fields, and
TUI behavior may change. A missing/404/exit-9 capability result is rollout failure,
not permission to use ordinary PRs silently. Record the installed version and exact
unsupported surface in a report.

## Official troubleshooting references

- [Troubleshooting stacked pull requests](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-stacked-pull-requests)
- [Stacked PR CLI commands](https://docs.github.com/en/pull-requests/reference/stacked-prs-cli-commands)
- [Managing stacked pull requests](https://docs.github.com/en/pull-requests/how-tos/create-pull-requests/managing-stacked-pull-requests)
- [Reviewing stacked pull requests](https://docs.github.com/en/pull-requests/how-tos/review-pull-requests/reviewing-stacked-pull-requests)
- [Merging stacked pull requests](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/merging-stacked-pull-requests)
