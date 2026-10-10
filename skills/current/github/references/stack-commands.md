# `gh stack` commands and lifecycle

Native stacks are generally available on github.com. Enterprise Server availability depends on its release. The extension remains version-sensitive; verify installed help, target, remotes, auth, worktree ownership, and stack state before use.

Writes: `add` staging/commit, checkout/rebase/navigation, submit, sync, push, link, unstack, and merge change local or remote state. Honor existing authorization for the operation and every affected layer/worktree; ask only for missing scope. Afterward re-read local `view --json`, remote branch tips, PRs, and stack state.

Handoff: complete `stack-design.md`; use `stack-troubleshooting.md` for failures. `git-worktrees` and `autommit` remain authorities for local lifecycle and staging/history.

## Capability and target gate

Before any stack command:

```text
gh --version
gh extension list
gh auth status
git remote -v
gh repo view [HOST/]OWNER/REPO --json nameWithOwner,defaultBranchRef,url
```

If absent and useful for the requested work, recommend official `github/gh-stack`. Review publisher, release, and current docs before authorized installation. Do not probe a missing command with `gh stack --help`, which may trigger installation:

```text
gh extension install github/gh-stack --pin TAG_OR_COMMIT
```

A missing command, 404, disabled feature, or stack exit `9` limits the requested stack operation, not ordinary PR work. Preserve known native membership instead of silently merging or unstacking it. With multiple remotes, set verified `GH_REPO=<host/owner/repo>` for the API target as well as `--remote` for pushes; `--remote` alone does not bind both targets.

Use explicit arguments, `view --json`, `submit --auto`, `merge --yes`, and a non-TTY stdout. `GH_PROMPT_DISABLED=1` is not sufficient to suppress the extension's prompts under a PTY. Avoid interactive `modify`, `switch`, and picker forms in agent execution. Examples below also set the host CLI's prompt control; it does not authorize writes. Check installed `gh stack <command> --help` after discovery.

Read native membership without the extension:

```text
gh api --method GET 'repos/OWNER/REPO/stacks?pull_request=PR_NUMBER'
```

An empty array means no native membership. Do not infer that result from an auth or network failure. `view --json` describes locally tracked layers but omits the remote stack number; resolve that number through the remote read.

## Local lifecycle

```text
# Initialize/adopt a linear stack with explicit branches (local state)
GH_PROMPT_DISABLED=1 gh stack init --base <trunk> <layer-1> <layer-2> <layer-3>

# Add one branch by name; hand staging/commit to `autommit` unless explicitly allowed
GH_PROMPT_DISABLED=1 gh stack add <layer-name>

# Read and refresh local/remote membership as JSON
GH_PROMPT_DISABLED=1 gh stack view --json

# Select an explicit stack/PR/branch (may fetch remote branches)
GH_PROMPT_DISABLED=1 gh stack checkout <stack-number|pr-number|pr-url|branch>

# Noninteractive navigation
GH_PROMPT_DISABLED=1 gh stack up [N]
GH_PROMPT_DISABLED=1 gh stack down [N]
GH_PROMPT_DISABLED=1 gh stack top
GH_PROMPT_DISABLED=1 gh stack bottom
GH_PROMPT_DISABLED=1 gh stack trunk
```

- `init` records local tracking and can adopt/create explicit branches; default trunk is the repository default unless `--base` is set; it is not a remote write.
- `add` creates/checks out a branch. Its `-A/-u/-m` staging/commit options are a write boundary owned by `autommit`; do not use them to bypass staging policy.
- `view --json` is the canonical refresh before and after any stack operation; avoid default pager/human output in automation.
- `checkout` may fetch a remote stack and change the active worktree. Route lifecycle and ownership through `git-worktrees`; never adopt a foreign/consumer worktree.
- Navigation changes local branch state. `switch` is interactive and is not an agent default.

Git 2.36+ is required. From extension v0.2.0, linked worktrees share `<common-dir>/gh-stack` and recovery journals. Nonconflicting legacy catalogs migrate automatically with backups; conflicting definitions stop. Do not mix old and new writers in one clone or edit recovery journals.

`rebase`, `sync`, and `modify` operate in the checkout that owns each affected branch. Check ownership and authorization for all affected checkouts before invocation. The extension checks clean/busy state and never creates, removes, steals, or auto-stashes worktrees. Its clone-wide locks coordinate extension processes, not other Git commands or editors.

Navigation and explicit-target `checkout` accept `--print-path`. For a branch occupied elsewhere, successful stdout identifies its checkout without switching it. An unoccupied branch is checked out here before its path is printed. Parse only successful stdout and retain the owning manager's lifecycle authority.

## Remote operations

```text
# Push/create/update all PRs and remote stack without the editor
GH_PROMPT_DISABLED=1 gh stack submit --auto --remote <remote>
# Add new PRs as ready for review only when authorized
GH_PROMPT_DISABLED=1 gh stack submit --auto --open --remote <remote>

# Fetch, reconcile, cascade-rebase, push, and refresh remote stack state
GH_PROMPT_DISABLED=1 gh stack sync --remote <remote>
GH_PROMPT_DISABLED=1 gh stack sync --remote <remote> --prune

# Cascade rebase; resolve explicitly with --continue or restore with --abort
GH_PROMPT_DISABLED=1 gh stack rebase --remote <remote>
GH_PROMPT_DISABLED=1 gh stack rebase --remote <remote> --upstack
GH_PROMPT_DISABLED=1 gh stack rebase --continue
GH_PROMPT_DISABLED=1 gh stack rebase --abort

# Push active branches only; do not expect PR creation
GH_PROMPT_DISABLED=1 gh stack push --remote <remote>

# Link branches/PRs managed elsewhere, in bottom-to-top order
GH_PROMPT_DISABLED=1 gh stack link --remote <remote> <bottom> <middle> <top>
```

- `submit` pushes branches, creates/updates PRs, and creates/updates the remote stack. With `--auto`, new PRs are drafts unless `--open` is authorized. It can partially land before a later failure; re-read each branch/PR/stack instead of retrying.
- `sync` fetches, reconciles, fast-forwards trunk when possible, cascades rebases, pushes, refreshes PR/stack state, and optionally prunes local merged branches. It does not open PRs. It can exit `0` after a failed push or an aborted divergence. Verify intended remote branch tips and PR heads, not the exit code or success message. Do not select a local/remote truth automatically.
- `rebase` changes local commit ancestry and may require `git add` plus `--continue`; `--abort` restores the pre-rebase state when supported. A rebase can make pushes non-fast-forward; verify leases and branch ownership.
- `push` fetches before building its leases and can overwrite remote-only commits that local branches never incorporated. Inspect remote tips and account for those commits before any rewrite; a refreshed lease is not that proof. Updates are not atomic, so report per-branch state after partial failures.
- `link` is remote-affecting and can push branches, create or adjust PR bases, and adjust the stack. Supply arguments bottom-to-top, verify the same repository, and re-read all PRs. It does not create local tracking; this is the handoff for Jujutsu, Sapling, git-town, or another external branch manager.

## Unstack and merge

```text
# Remove local tracking and remote stack association (destructive remote boundary)
GH_PROMPT_DISABLED=1 gh stack unstack <stack-number>
# Local tracking only; does not change GitHub
GH_PROMPT_DISABLED=1 gh stack unstack --local <stack-number>

# Merge whole/current stack or through an explicit PR without a prompt
GH_PROMPT_DISABLED=1 gh stack merge --yes --squash <stack-number|pr-number>
```

`unstack` may leave merged/merging/queued PRs stacked and can dissolve the remote stack only after its remaining PRs are removed. `--local` skips the remote operation. Do not confuse unstacking with deleting branches or PRs; inspect the exact boundary.

`merge --yes` merges through the selected PR, including every unmerged PR below it. Verify that all selected layers are reviewed and authorized; naming one PR does not authorize extra lower layers. Direct merging is all-or-nothing. With a merge queue, the selected stack lands as one merge group and the queue determines the method. Confirm each PR reaches MERGED; a queued request is pending delivery. **Never use `gh pr merge` for a native stack merge.**

The extension does not expose `--match-head-commit`; do not claim that it preserves `ship land`'s reviewed-head condition. Ship's CLI handles ordinary PRs and refuses known native membership. Native automation must establish its head conditions and merge scope through the documented API before replacing that guarantee. After partial merges, refresh every remaining layer's base/head and checks before cleanup or further landing.

## CI, review, and API boundaries

Branch protection and required checks are evaluated for each stack PR. Read checks and reviews per layer with `collaboration.md`/`automation.md` after every rebase or push; a lower-layer green check can become stale when ancestry changes.

A stack is remote GitHub state, not merely local branch metadata. Webhooks include a `stack` object in pull-request events. REST supports stack membership/list/create/extend/dissolve operations; GraphQL exposes read-only stack fields on PRs. Use `api.md` for endpoint/method/pagination safety; do not recreate `gh stack` local state with guessed API calls.

Direct stack merges through the API require GitHub's asynchronous merge API. If a request returns a queued/in-progress result, poll the documented status endpoint and re-read stack/PR state; do not issue another merge request. Review/UI navigation is a browser side effect. Use structured CLI/API state unless the user explicitly requests web interaction.

## Exit codes

The extension documents these stack-specific codes; installed help wins if drifted:

|Code|Meaning|Safe handling|
|---:|---|---|
|`0`|Command completed|Verify intended local and remote state; sync may have failed to push|
|`1`|Generic error|Preserve state; inspect stderr|
|`2`|Not in/found stack|Verify target/membership; no fallback mutation|
|`3`|Rebase conflict|Resolve or abort explicitly|
|`4`|GitHub API failure|Inspect target/auth/response; do not retry blindly|
|`5`|Invalid args/flags|Read installed help; change plan, not remote state|
|`6`|Branch belongs to multiple stacks|Disambiguate explicitly; never choose one|
|`7`|Rebase already in progress|Inspect and continue/abort the owning operation|
|`8`|Stack locked|Wait/coordinate with owner; never break the lock|
|`9`|Feature unavailable/disabled|Report rollout; never fall back silently|
|`10`|Modify session interrupted|Preserve state; recover with documented continue/abort|

## Official references

- [Stacked PR CLI commands](https://docs.github.com/en/pull-requests/reference/stacked-prs-cli-commands)
- [Stack overview](https://docs.github.com/en/pull-requests/get-started/about-stacked-prs)
- [Stack quickstart](https://docs.github.com/en/pull-requests/get-started/stacked-prs-quickstart)
- [Managing stacks](https://docs.github.com/en/pull-requests/how-tos/create-pull-requests/managing-stacked-pull-requests)
- [Reviewing stacks](https://docs.github.com/en/pull-requests/how-tos/review-pull-requests/reviewing-stacked-pull-requests)
- [Merging stacks](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/merging-stacked-pull-requests)
- [Stack troubleshooting](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-stacked-pull-requests)
- [REST pull request merge](https://docs.github.com/en/rest/pulls/pulls#merge-a-pull-request-asynchronously)
- [Native stack availability and merge behavior](https://github.blog/changelog/2026-10-06-stacked-pull-requests-generally-available/)
- [Worktree support](https://github.com/github/gh-stack/releases/tag/v0.2.0)
- [Push lease limitation](https://github.com/github/gh-stack/issues/380)
- [Sync exit status limitation](https://github.com/github/gh-stack/issues/472)
