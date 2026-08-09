# `gh stack` commands and lifecycle

**Covers:** capability gates, local/remote effects, noninteractive commands, remote
selection, JSON refreshes, CI/review state, merge queues, API boundaries, and exit
codes for the GitHub stacked-PR extension.

**Safe default:** treat `gh stack` as public preview and version-sensitive. Verify
capability, target, remotes, auth, worktree/manager, and stack state read-only; use
explicit arguments, `GH_PROMPT_DISABLED=1`, `--json`, and `--remote` when needed.

**Write boundary:** `add` with staging/commit, checkout/rebase/navigation, submit,
sync, push, link, unstack, and merge change local or remote state. Require explicit
authorization for each external write (and local authorization when it changes an
assigned worktree); re-read local `view --json`, branches, PRs, and stack state.

**Adjacent handoff:** complete `stack-design.md` first. Use `stack-troubleshooting.md`
for failures. `git-worktrees`, `commit`, and `gh-contrib` remain authorities for
local lifecycle, staging/history, and ordinary contribution policy.

## Capability and target gate

Before any stack command:

```text
gh --version
gh extension list
gh skill list
gh auth status
git remote -v
gh repo view [HOST/]OWNER/REPO --json nameWithOwner,defaultBranchRef,url
```

Do not probe a missing `gh stack` with `gh stack --help`: the installed environment
may auto-install `github/gh-stack`. If the extension is absent, review publisher,
version, permissions, and the current official docs, then obtain explicit authorization
before installing:

```text
gh extension install github/gh-stack --pin TAG_OR_COMMIT
```

If a focused `github/gh-stack` agent skill is installed and active, hand off to it.
Otherwise these references are the fallback. A missing command, 404, disabled
feature, or stack exit `9` means availability/rollout failure; do not silently use
ordinary PR commands. When multiple remotes exist, name the intended remote on every
remote-aware command and verify its host/repository before proceeding.

Set `GH_PROMPT_DISABLED=1` for automation and verification. It prevents prompts; it
does not authorize writes. Prefer explicit branch/stack/PR arguments and avoid the
interactive `modify`, `switch`, or picker forms in agent execution.

## Local lifecycle

These examples are planning forms; exact flags are version-sensitive, so check
`gh stack <command> --help` after capability discovery.

```text
# Initialize/adopt a linear stack with explicit branches (local state)
GH_PROMPT_DISABLED=1 gh stack init --base <trunk> <layer-1> <layer-2> <layer-3>

# Add one branch by name; hand staging/commit to `commit` unless explicitly allowed
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

- `init` records local tracking and can adopt/create explicit branches; default trunk
  is the repository default unless `--base` is set. It is not a remote write.
- `add` creates/checks out a branch. Its `-A/-u/-m` staging/commit options are a
  write boundary owned by `commit`; do not use them to bypass staging policy.
- `view --json` is the canonical refresh before and after any stack operation. Avoid
  the default pager/human output in automation.
- `checkout` may fetch a remote stack and change the active worktree. Route lifecycle
  and ownership through `git-worktrees`; never adopt a foreign/consumer worktree.
- Navigation changes local branch state. `switch` is interactive and is not an agent
  default.

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

- `submit` pushes branches, creates/updates PRs, and creates/updates the remote stack
  With `--auto`, new PRs are drafts unless `--open` is authorized. It can partially
  land before a later failure; re-read each branch/PR/stack instead of retrying.
- `sync` fetches, reconciles, fast-forwards trunk when possible, cascades rebases,
  pushes with force-with-lease when needed, refreshes PR/stack state, and optionally
  prunes local merged branches. It does not open PRs. A clean remote-ahead update may
  be adopted; true divergence is a no-op in noninteractive mode and exits without
  pushing/updating. Do not select a local/remote truth automatically.
- `rebase` changes local commit ancestry and may require `git add` plus `--continue`;
  `--abort` restores the pre-rebase state when supported. A rebase can make pushes
  non-fast-forward; verify leases and branch ownership.
- `push` uses force-with-lease checks but is not atomic: earlier branches can update
  when a later lease fails. Report per-branch state.
- `link` is remote-affecting and can push branches/create or adjust PR bases and the
  stack. Supply arguments bottom-to-top, verify same repository, and re-read all PRs.
  It does not create local tracking; this is the handoff for Jujutsu, Sapling,
  git-town, or another external branch manager.

## Unstack and merge

```text
# Remove local tracking and remote stack association (destructive remote boundary)
GH_PROMPT_DISABLED=1 gh stack unstack <stack-number>
# Local tracking only; does not change GitHub
GH_PROMPT_DISABLED=1 gh stack unstack --local <stack-number>

# Merge whole/current stack or through an explicit PR without a prompt
GH_PROMPT_DISABLED=1 gh stack merge --yes --squash <stack-number|pr-number>
```

`unstack` may leave merged/merging/queued PRs stacked and can dissolve the remote
stack only after its remaining PRs are removed. `--local` skips the remote operation.
Do not confuse unstacking with deleting branches or PRs; inspect the exact boundary.

`merge --yes` is the stack merge path. It merges through the selected PR in one
all-or-nothing request when direct merge is possible; repository rules still apply.
If a merge queue is configured, GitHub queues the selected PRs and may process them
in separate groups asynchronously, ignoring the requested merge method. Poll each PR
and the queue until a terminal state, or report pending/failed state. **Never use
`gh pr merge` for an explicit stack merge.**

## CI, review, and API boundaries

- Branch protection and required checks are evaluated for each stack PR; read checks
  and reviews per layer with `collaboration.md`/`automation.md` after every rebase or
  push. A lower-layer green check can become stale when ancestry changes.
- A stack is remote GitHub state, not merely local branch metadata. Webhooks include a
  `stack` object in pull-request events. REST supports stack membership/list/create/
  extend/dissolve operations; GraphQL exposes read-only stack fields on PRs. Use
  `api.md` for endpoint/method/pagination safety and do not recreate `gh stack` local
  state with guessed API calls.
- Direct stack merges through the API require GitHub's asynchronous merge API. If a
  request returns a queued/in-progress result, poll the documented status endpoint
  and re-read stack/PR state; do not issue another merge request.
- Review/UI navigation is a browser side effect. Use structured CLI/API state unless
  the user explicitly requests web interaction.

## Exit codes

The extension documents these stack-specific codes (installed help wins if drifted):

| Code | Meaning | Safe handling |
| ---: | --- | --- |
| `0` | Success | Refresh JSON state |
| `1` | Generic error | Preserve state; inspect stderr |
| `2` | Not in/found stack | Verify target/membership; no fallback mutation |
| `3` | Rebase conflict | Resolve or abort explicitly |
| `4` | GitHub API failure | Inspect target/auth/response; do not retry blindly |
| `5` | Invalid args/flags | Read installed help; change plan, not remote state |
| `6` | Branch belongs to multiple stacks | Disambiguate explicitly; never choose one |
| `7` | Rebase already in progress | Inspect and continue/abort the owning operation |
| `8` | Stack locked | Wait/coordinate with owner; never break the lock |
| `9` | Feature unavailable/disabled | Report rollout; never fall back silently |
| `10` | Modify session interrupted | Preserve state; recover with documented continue/abort |

## Official references

- [Stacked PR CLI commands](https://docs.github.com/en/pull-requests/reference/stacked-prs-cli-commands)
- [Stack overview](https://docs.github.com/en/pull-requests/get-started/about-stacked-prs)
- [Stack quickstart](https://docs.github.com/en/pull-requests/get-started/stacked-prs-quickstart)
- [Managing stacks](https://docs.github.com/en/pull-requests/how-tos/create-pull-requests/managing-stacked-pull-requests)
- [Reviewing stacks](https://docs.github.com/en/pull-requests/how-tos/review-pull-requests/reviewing-stacked-pull-requests)
- [Merging stacks](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/merging-stacked-pull-requests)
- [Stack troubleshooting](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-stacked-pull-requests)
- [REST pull request merge](https://docs.github.com/en/rest/pulls/pulls#merge-a-pull-request-asynchronously)
