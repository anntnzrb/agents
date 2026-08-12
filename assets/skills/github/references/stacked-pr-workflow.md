# Minimum stacked pull request workflow

Scope: Before publishing a branch, creating a pull request, or linking a pull request to a stack. Repository-agnostic; read-only audit separate from each authorized write.

## Audit before writing

Fresh session MUST run:

```text
gh --version
gh extension list
gh skill list
gh auth status
git status --short --branch
git remote -v
gh repo view <host/owner/repo> --json nameWithOwner,url,defaultBranchRef,viewerPermission
```

Establish target/state:

- Confirm current branch, clean tree, commit ancestry, intended remote, and explicit repository.
- Check existing remote branch and PR:
  `git ls-remote --heads <remote> <branch>` and `gh pr list --repo <repo> --head <qualified-head> --state all --json number,title,state,url,headRefName,baseRefName`.
- If a parent PR exists, read state, head/base refs and OIDs, mergeability, checks, and reviews. New stacked PR MUST target the immediate parent branch, not repository trunk.
- Resolve remote stack and actual stack number. With local tracking, use `GH_PROMPT_DISABLED=1 gh stack view --json`; otherwise use the supported remote-stack read in `stack-commands.md` and `api.md`.
- Before version-sensitive flags, run `GH_PROMPT_DISABLED=1 gh stack link --help`. Local `gh stack view` exit 2 means absent local membership, not absent remote stack.
- If code changed, run relevant focused validation before external writes.

MUST stop before mutation if tree dirty, rebase/merge in progress, parent diverged, stack ambiguous or locked, or duplicate PR exists.

## Idempotent path

- Branch without open PR: publish; create exactly one PR; re-read it; link it.
- Branch with open PR: never duplicate; re-read; publish only if local branch is ahead and user authorized push; link only if not already stacked.
- Branch already in target stack: do not link again; re-read and report position.
- No existing stack: do not silently create one. Confirm intended trunk and complete the bottom-to-top stack before `gh stack link --base`.

## Writes: create first, link second

Explicit authorization required immediately before each external write. Branch without open PR:

```text
git push -u <remote> <branch>
```

Re-read remote branch, then create PR without an implicit prompt:

```text
GH_PROMPT_DISABLED=1 gh pr create \
  --repo <repo> \
  --head <qualified-head> \
  --base <immediate-parent-branch> \
  --title "<approved-title>" \
  --body ""
```

Empty `--body ""` is intentional when no body was requested. If a body is requested, supply it explicitly with `--body-file` or `--body`; NEVER open editor or browser implicitly. Re-read the created PR and verify number, head, base, state, draft status, and empty/non-empty body before linking.

Existing stack, append new branch or PR from the top:

```text
GH_PROMPT_DISABLED=1 gh stack link \
  --remote <remote> <stack-number> <branch-or-pr>
```

First positional stack number means append to that existing stack; remaining arguments process in stack order. A branch argument may be pushed or used by `gh-stack` to find/create a PR; when separate PR creation is requested, use the explicit create-first sequence above.

After linking, re-read PR and remote stack. Confirm PR open, immediate-parent target, expected top position. NEVER silently fall back to ordinary PR commands if `gh-stack` unavailable, returns exit 9, reports lock/divergence, or rejects graph.

## Optional post-creation writes

Apply labels, reviewers, projects, or draft/ready changes only when requested, as separate authorized writes. Re-read each affected object after writing:

```text
gh pr edit <pr> --repo <repo> --add-label <label>
```

Report repository, remote, branch, parent PR/base, created PR URL, stack number/position, writes performed, skipped paths, and unavailable checks.
