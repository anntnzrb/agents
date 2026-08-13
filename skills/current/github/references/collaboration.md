# GitHub collaboration commands

Covers `issue`, `pr`, `discussion`, `project`, `label`; JSON selection, checks, reviews, post-write verification.

## Defaults and boundaries
- Safe default: identify explicit host/repository/object; read current state; use structured output. Ordinary contribution policy → `gh-contrib`.
- External writes: create, edit, comment, close, reopen, merge, request review, resolve threads, change labels/projects/milestones. MUST obtain explicit authorization at mutation boundary; re-read resulting object. NEVER put secrets in issue/PR bodies or comments.
- Shared rules → `core.md`; Actions checks/logs → `automation.md`; dependent PRs → `stack-design.md`, `stack-commands.md`; repository contribution policy and ordinary PR review → `gh-contrib`.

## Common reads
Bind target explicitly:

```text
gh issue list --repo OWNER/REPO --state open --json number,title,author,labels,url
gh pr view NUMBER --repo OWNER/REPO --json number,title,state,headRefName,baseRefName,isDraft,reviewDecision,statusCheckRollup,url
```

Discover fields with `--json` without a field list when installed options drift. Use `--jq`/`--template` to return only selected values. Numbers repository-local; NEVER reuse issue/PR numbers across repositories or hosts.

## Issues
- Reads: `gh issue list`, `view`, `status`; reproducible reports MUST include `--repo` and state/author/label filters.
- Writes: `gh issue create`, `comment`, `edit`, `close`, `reopen`, `delete`, `develop`, `lock`; first capture issue URL/number and current state.
- `gh issue create` MAY prompt/open an editor; use noninteractive title/body flags only for user-supplied or user-approved content; re-read with `view`.
- `gh issue transfer` changes repository ownership; verify destination and permission before authorization. Failures MAY be partial; re-read both sides.

## Pull requests and reviews
- Inspection reads: `gh pr list`, `view`, `diff`, `checks`, `status`, `review`. `diff` returns patch text; a browser URL is not the patch.
- Required-check machine route: `gh pr checks NUMBER --repo OWNER/REPO --json ... --jq ...`. Separate pending, failed, skipped, successful; NEVER claim CI green from a human summary.
- `gh pr view --json reviews,reviewDecision,statusCheckRollup,latestReviews` (fields available in installed CLI) exposes review/check state. If thread-level anchors or unresolved conversations matter, use the GitHub API reference and preserve file/line identity.
- `gh pr diff --patch` remains a read; use `hunk` only for a live Hunk review.
- `gh pr checkout` changes local branch/worktree state; route lifecycle decisions to `git-worktrees` and inspect current worktree ownership first.
- Writes: `gh pr create`, `edit`, `close`, `reopen`, `comment`, `review`, `ready`, `lock`, `unlock`, `update-branch`, `merge`. Before execution, confirm base/head/repository, draft state, body, reviewers, and requested authorization.
- Ordinary single-PR contribution sequencing, repository rules, push policy, and issue/PR creation → `gh-contrib`; this file owns CLI selection and state verification only.
- `gh pr merge` is an ordinary PR path, NOT a stacked-PR merge path. Explicit stack intent → `stack-commands.md`, which owns merge order and queue state.

## Discussions
- `gh discussion list`, `view`, and category reads are remote reads when available in installed CLI.
- `create`, `comment`, `edit`, `close`, `reopen`, answer/reply operations are writes. Categories, node IDs, repository scope MUST be explicit.
- Absent or preview-only command: use `gh help`, then `api.md` for the smallest documented endpoint; NEVER fabricate a fallback.

## Projects
- Scope: repository, organization, or user. Before any change, read project owner, number/ID, visibility, fields, views, item IDs:

```text
gh project list --owner OWNER --format json
gh project view NUMBER --owner OWNER --format json
```

- `gh project item-list`, `field-list`, and `link`/`copy` inspection helps identify stable IDs.
- Writes: `gh project create`, `item-add`, `item-edit`, `item-delete`, `field-create`, `field-edit`, `field-delete`, `close`, `delete`; project delete and item delete are destructive. After each authorized change, re-read project/item state.

## Labels
- Read: `gh label list --repo OWNER/REPO --json name,description,color,isDefault`.
- `create`, `edit`, `delete` change repository metadata. Confirm exact name and color. NEVER delete a label merely because absent from a filtered listing.
- Issue/PR label add/remove operations are writes; re-read objects.

## Failure handling
Report permission errors, review/check API gaps, merge conflicts, stale objects, and rate limits with exact target and command exit. If edit/comment/merge fails, preserve current object; NEVER retry or close/reopen to “unstick” it. For a lower PR in a stack, follow `stack-troubleshooting.md`, not ordinary merge or force-push.

## Official references
- [gh issue](https://cli.github.com/manual/gh_issue)
- [gh pr](https://cli.github.com/manual/gh_pr)
- [gh discussion](https://cli.github.com/manual/gh_discussion)
- [gh project](https://cli.github.com/manual/gh_project)
- [gh label](https://cli.github.com/manual/gh_label)
