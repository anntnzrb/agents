# Dependent PRs and optional native stacks

Scope: Publishing dependent branches and PRs, with optional native stack association. Use the ordinary PR path unless native association is requested or already exists.

When work depends on an unmerged PR, open the new PR with that PR's branch as its base. For an ordinary chain, use `ship land` bottom-up after the parent reaches the intended trunk and verify the child's live base. Native stacks use the merge workflow in `stack-commands.md`; `ship land` refuses them before merge or cleanup.

## Audit before writing

Fresh session MUST run:

```text
gh --version
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
- If native association is requested or known, check `gh extension list` before extension commands. Resolve remote membership with the REST read in `stack-commands.md`; local `view --json` does not include the remote stack number.
- With the extension installed, check `GH_PROMPT_DISABLED=1 gh stack link --help` before version-sensitive flags. Local `view` exit 2 means absent local tracking, not absent remote membership.
- If code changed, run relevant focused validation before external writes.

MUST stop before mutation if tree dirty, rebase/merge in progress, parent diverged, stack ambiguous or locked, or duplicate PR exists.

## Idempotent path

- Branch without open PR: publish; create exactly one PR; re-read it. Link only when native association is authorized.
- Branch with open PR: never duplicate; re-read; publish only if local branch is ahead and user authorized push; link only if not already stacked.
- Branch already in target stack: do not link again; re-read and report position.
- No native stack requested: finish the ordinary PR workflow without installing or linking anything.
- Native stack requested, none exists: confirm intended trunk and the bottom-to-top layer map before `gh stack link --base`.

## Writes: create first, link second

Confirm that existing authorization covers each external write; do not ask again for necessary scoped Ship operations. Branch without open PR:

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

When native association is authorized, append the new PR to an existing stack from the top. Prefer the verified PR URL so `link` need not push a branch or create another PR:

```text
GH_PROMPT_DISABLED=1 gh stack link \
  --remote <remote> <stack-number> <pr-url>
```

First positional stack number means append to that existing stack; remaining arguments process in stack order. A branch argument may be pushed or used by `gh-stack` to find/create a PR; when separate PR creation is requested, use the explicit create-first sequence above.

After linking, re-read PR and remote stack. Confirm PR open, immediate-parent target, expected top position. An unavailable optional extension does not block an ordinary PR. If native membership already exists or the user requires native association, preserve state and report that unavailable operation; do not silently substitute an ordinary merge.

## Optional post-creation writes

Apply labels, reviewers, projects, or draft/ready changes only when requested, as separate authorized writes. Re-read each affected object after writing:

```text
gh pr edit <pr> --repo <repo> --add-label <label>
```

Report repository, remote, branch, parent PR/base, created PR URL, stack number/position, writes performed, skipped paths, and unavailable checks.
