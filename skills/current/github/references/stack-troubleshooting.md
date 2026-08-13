# Stacked pull request troubleshooting

## Scope and safety
Covers dirty trees, conflicts, divergence/rollback, locks/interrupted sessions, merge ancestry, pruning/unstacking, external managers, signatures, partial writes, and preview/document drift.

Safe default: stop at uncertainty; preserve evidence/current state; re-read local/remote JSON before recovery. NEVER auto-repair, force, prune, break locks, choose local/remote truth, or silently fall back to ordinary PRs.

Writes: conflict resolution; rebase continue/abort; force-with-lease push; stack unstack/prune; branch deletion; PR retarget/merge; API recovery. Require explicit authorization and owning manager at every write boundary.

Handoffs: `stack-commands.md` command/version/exit semantics; `stack-design.md` graph/manager ownership; `git-worktrees` worktree lifecycle; `commit` staging/history; `gh-contrib` contribution policy; `api.md` custom endpoint recovery.

## Any failure
1. Record command, target host/repository, branch/PR/stack IDs, exit code, stdout, stderr, and whether a write was attempted.
2. Read-only inspect `git status`, current branch/worktree/rebase state, remotes, `gh stack view --json`, relevant PRs/checks, and remote branch tips.
3. Classify local-only, remote-only, or mixed. Treat mixed operations as potentially partial until every affected object is re-read.
4. Do not retry push, POST, merge, unstack, prune, or dispatch because output looks incomplete; compare stable IDs/tips first.

## Dirty trees and ownership
`init`, `add`, `checkout`, `rebase`, `sync`, and `modify` may require a clean tree or change the current branch. With uncommitted changes, NEVER clean, reset, stash, commit, or move them without an explicit plan and owning `commit`/`git-worktrees` authority. Determine whether the checkout is assigned, consumer/foreign, or native-manager-owned; the current directory grants no rewrite permission. Report dirty paths and stop stack mutation; do not hide state with a new branch or force option.

## Rebase conflicts/recovery
For `gh stack rebase`, `sync`, or cascading operations:
1. Preserve conflict markers and operation metadata; inspect conflicted files and `git status`; do not run an unrelated rebase.
2. The layer owner resolves intended content, stages exactly that resolution under `commit` policy, then runs `gh stack rebase --continue` or the installed command's documented continue form.
3. Run `gh stack rebase --abort` only when abandonment, authorization, and ownership are clear; afterward re-read every branch tip and `gh stack view --json`.
4. Post-rebase push uses force-with-lease, NEVER `--force`. Lease failure means stop, fetch/read remote, and resolve divergence without overwriting.

Squash/rebase merges may change ancestry; the old bottom tip may no longer be a simple ancestor. After a merged lower layer, use documented stack rebase/`--onto` behavior, never manual branch reset to make the graph linear. Refresh base/head and checks for every upstack PR.

## Sync divergence/rollback
`sync` may adopt clean remote-ahead additions, but true local/remote divergence never authorizes choosing a source of truth. In noninteractive mode, documented behavior is abort/no-op without pushing or updating PRs; successful exit can mean “nothing changed,” not “synced.”

Re-read local/remote stack composition, branch tips, and uncommitted state. Present competing layer maps; ask the owning user/manager to choose remote, local recreation, or cancellation. NEVER delete the remote stack automatically. After a sync rebase conflict, expect branch restoration to original state and verify it. `--prune` deletes local branches for merged PRs; NEVER use it while diagnosing divergence, unknown ownership, or a dirty worktree. Re-read local refs after authorized prune.

## Locks and interrupted TUI
A stack lock or exit `8` means another process may write. NEVER break lock files, kill an unknown process, or run a second stack command. Identify the owner through installed-tool read-only status, coordinate, and retry only after lock release.

Interrupted `modify` or exit `10` requires documented recovery. Preserve session metadata. Use `gh stack modify --continue` only after conflicts are resolved and staged, or `gh stack modify --abort` to restore prior state. NEVER open a second interactive TUI or hand-edit branch metadata during recovery.

## Ambiguous stacks/identifiers
A branch may occur in multiple stacks; exit `6` requires explicit disambiguation. A bare number may be a stack or PR number. Use an explicit stack/PR URL or read-only `view`, never positional guessing. If a branch is not in a stack (exit `2`), inspect local tracking and remote PR stack membership before adding it. Missing local metadata is not grounds to create a new stack.

## External managers/worktrees
Jujutsu, Sapling, git-town, GitButler, native harness managers, and linked worktrees may own branch movement/history. Determine ownership before `checkout`, `rebase`, `push`, `link`, or `unstack`.

- Use `gh stack link` for remote association when another local manager owns branches; it does not create local tracking and may still push/create/retarget PRs.
- Do not mix `gh stack` local rewrites with GitButler or raw-Git writes. Delegate staging/commits to `commit` and lifecycle to `git-worktrees`.
- NEVER adopt, delete, relocate, or reset a consumer/foreign worktree; preserve it and report the ownership blocker.

## Unstack, prune, partial writes
`unstack` removes remote stack association and/or local tracking; it does not imply branch/PR deletion. Merged, merging, or queued PRs may remain stacked. `--local` changes only local tracking. Verify the requested boundary before authorization.

Remote operations are not uniformly atomic:
- `submit` pushes, creates/updates PRs, then links the stack; failure may leave branches/PRs without complete stack association.
- `push` may update earlier branches before a later force-with-lease failure.
- `link` may push and create/retarget multiple PRs before later validation fails.
- `merge --yes` is all-or-nothing for direct stack merging; merge queues are asynchronous and may process selected PRs in groups.

After any partial result, inventory every branch, PR, and stack object; resume only from explicit remaining state. NEVER rerun the whole operation blindly.

## Signatures/provenance
Rebases, cherry-picks, squash merges, and GitHub-generated merge commits may alter commit IDs, committer identity, or signature verification. Preserve repository-policy author/committer and signed-state requirements. Do not claim a rebased commit retains its original signature without checking the new object. Use `gh api` or the repository's documented verification command only for deliberate read.

## Preview/document drift
Stacked PRs and `gh stack` are public preview. Installed `gh stack <command> --help` and current official docs outrank this reference; flags, exit codes, API fields, and TUI behavior may change. Missing/404/exit-`9` capability is rollout failure, NOT permission to silently use ordinary PRs. Record installed version and exact unsupported surface in the report.

## Official references
- [Troubleshooting stacked pull requests](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-stacked-pull-requests)
- [Stacked PR CLI commands](https://docs.github.com/en/pull-requests/reference/stacked-prs-cli-commands)
- [Managing stacked pull requests](https://docs.github.com/en/pull-requests/how-tos/create-pull-requests/managing-stacked-pull-requests)
- [Reviewing stacked pull requests](https://docs.github.com/en/pull-requests/how-tos/review-pull-requests/reviewing-stacked-pull-requests)
- [Merging stacked pull requests](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/merging-stacked-pull-requests)
