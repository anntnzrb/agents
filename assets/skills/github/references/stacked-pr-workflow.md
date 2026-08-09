# Minimum stacked pull request workflow

Read this reference before publishing a branch, creating a pull request, or linking a pull request to a stack. The workflow is repository-agnostic and separates read-only audit from each authorized write.

## Audit before writing

Run these checks in a fresh session:

```text
gh --version
gh extension list
gh skill list
gh auth status
git status --short --branch
git remote -v
gh repo view <host/owner/repo> --json nameWithOwner,url,defaultBranchRef,viewerPermission
```

Establish the exact target and state:

- Confirm the current branch, clean tree, commit ancestry, intended remote, and explicit repository
- Check for an existing remote branch and pull request:
  `git ls-remote --heads <remote> <branch>` and
  `gh pr list --repo <repo> --head <qualified-head> --state all --json number,title,state,url,headRefName,baseRefName`.
- If a parent pull request exists, read its state, head/base refs and OIDs, mergeability, checks, and reviews. A new stacked PR MUST target the immediate parent branch, not the repository trunk
- Resolve the remote stack and its actual stack number. Use `GH_PROMPT_DISABLED=1 gh stack view --json` when local tracking exists; otherwise use the supported remote stack read in `stack-commands.md` and `api.md`
- Run `GH_PROMPT_DISABLED=1 gh stack link --help` before relying on version-sensitive flags. A local `gh stack view` exit 2 means local membership is absent; it does not prove the remote stack is absent
- If code changed, run the relevant focused validation before external writes

Stop before any mutation when the tree is dirty, a rebase/merge is in progress, the parent diverges, the stack is ambiguous or locked, or a duplicate pull request exists.

## Idempotent path selection

- **Branch without an open PR:** publish it, create exactly one PR, re-read that PR, then link it to the stack
- **Branch with an open PR:** do not create a duplicate; re-read it, publish only if the local branch is ahead and the user authorized the push, then link it only if it is not already stacked
- **Branch already in the target stack:** do not link again; re-read and report its position
- **No existing stack:** do not silently create one. Confirm the intended trunk and complete the bottom-to-top stack before using `gh stack link --base`

## Default write sequence: create first, link second

Require explicit authorization immediately before each external write. For a branch without an open PR:

```text
git push -u <remote> <branch>
```

Re-read the remote branch, then create the PR without an implicit prompt:

```text
GH_PROMPT_DISABLED=1 gh pr create \
  --repo <repo> \
  --head <qualified-head> \
  --base <immediate-parent-branch> \
  --title "<approved-title>" \
  --body ""
```

An empty `--body ""` is intentional when no body was requested. If a body is requested, supply it explicitly with `--body-file` or `--body`; never open an editor or browser implicitly. Re-read the created PR and verify its number, head, base, state, draft status, and empty/non-empty body before linking.

For an existing stack, append the new branch or PR from the top:

```text
GH_PROMPT_DISABLED=1 gh stack link \
  --remote <remote> <stack-number> <branch-or-pr>
```

A stack number as the first positional argument means “append to this existing stack”; remaining arguments are processed in stack order. A branch argument may be pushed or used to find/create a PR by `gh-stack`, so use the explicit create-first sequence above when the user requests a separate PR creation.

After linking, re-read the PR and remote stack. Confirm that the PR is open, points to the immediate parent, and occupies the expected top position. Never fall back silently to ordinary PR commands if `gh-stack` is unavailable, returns exit 9, reports a lock/divergence, or rejects the graph.

## Optional post-creation writes

Apply labels, reviewers, projects, or draft/ready changes only when requested and as separate authorized writes. Re-read each affected object after the write:

```text
gh pr edit <pr> --repo <repo> --add-label <label>
```

Report the repository, remote, branch, parent PR/base, created PR URL, stack number/position, writes performed, skipped paths, and unavailable checks.
