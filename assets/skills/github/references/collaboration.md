# GitHub collaboration commands

**Covers:** `issue`, `pr`, `discussion`, `project`, and `label`, including JSON
selection, checks, reviews, and post-write verification.

**Safe default:** identify the explicit host/repository/object, read current state,
and use structured output. Keep ordinary contribution policy with `gh-contrib`.

**Write boundary:** creating, editing, commenting, closing, reopening, merging,
requesting review, resolving threads, changing labels, changing projects, and
changing milestones are external writes. Require explicit authorization at the
mutation boundary and re-read the resulting object. Never put secrets in issue/PR
body or comment text.

**Adjacent handoff:** read `core.md` for shared auth/output rules, `automation.md`
for Actions checks/logs, `stack-design.md` and `stack-commands.md` for dependent
PRs, and `gh-contrib` for repository contribution policy and ordinary PR review.

## Common read shape

Bind the target explicitly:

```text
gh issue list --repo OWNER/REPO --state open --json number,title,author,labels,url
gh pr view NUMBER --repo OWNER/REPO --json number,title,state,headRefName,baseRefName,isDraft,reviewDecision,statusCheckRollup,url
```

Discover fields with `--json` and no field list when installed options drift. Use
`--jq`/`--template` to return only selected values. Numbers are repository-local;
do not reuse an issue or PR number across repositories or hosts.

## Issues

- `gh issue list`, `view`, and `status` are reads. Include `--repo` and state/author/
  label filters in reproducible reports.
- `gh issue create`, `comment`, `edit`, `close`, `reopen`, `delete`, `develop`, and
  `lock` mutate remote state. Capture the issue URL/number and current state first.
- `gh issue create` may prompt or open an editor; provide noninteractive title/body
  flags only when the user supplied or approved the content. Re-read with `view`.
- `gh issue transfer` changes repository ownership; verify destination and permission
  before authorization. Treat failures as potentially partial and re-read both sides.

## Pull requests and reviews

- `gh pr list`, `view`, `diff`, `checks`, `status`, and `review` inspection modes are
  reads. `diff` returns patch text; do not mistake a browser URL for the patch.
- `gh pr checks NUMBER --repo OWNER/REPO --json ... --jq ...` is the machine-readable
  route for required checks. Separate pending, failed, skipped, and successful
  checks; do not claim CI is green from a human summary.
- `gh pr view --json reviews,reviewDecision,statusCheckRollup,latestReviews` (using
  fields available in the installed CLI) exposes review/check state. If thread-level
  anchors or unresolved conversations matter, use the GitHub API reference and
  preserve file/line identity.
- `gh pr diff --patch` is still a read; use `hunk` only for a live Hunk review
- `gh pr checkout` changes local branch/worktree state. Route lifecycle decisions to
  `git-worktrees` and inspect current worktree ownership first.
- `gh pr create`, `edit`, `close`, `reopen`, `comment`, `review`, `ready`, `lock`,
  `unlock`, `update-branch`, and `merge` are writes. Confirm base/head/repository,
  draft state, body, reviewers, and requested authorization before executing.
- Ordinary single-PR contribution sequencing, repository rules, push policy, and
  issue/PR creation belong to `gh-contrib`; this file owns CLI selection and state
  verification only.

`gh pr merge` is an ordinary PR path. It is **not** a stacked-PR merge path; explicit
stack intent must route to `stack-commands.md`, where merge order and queue state are
owned.

## Discussions

`gh discussion list`, `view`, and category reads are remote reads when available in
the installed CLI. `create`, `comment`, `edit`, `close`, `reopen`, and answer/reply
operations are writes. Categories, node IDs, and repository scope must be explicit.
When a command is absent or preview-only, use `gh help` and then `api.md` for the
smallest documented endpoint; do not fabricate a fallback.

## Projects

Projects can be repository-, organization-, or user-scoped. Read the project owner,
number/ID, visibility, fields, views, and item IDs before changing anything:

```text
gh project list --owner OWNER --format json
gh project view NUMBER --owner OWNER --format json
```

`gh project item-list`, `field-list`, and `link`/`copy` inspection help identify
stable IDs. `gh project create`, `item-add`, `item-edit`, `item-delete`, `field-create`,
`field-edit`, `field-delete`, `close`, and `delete` are writes; project delete and
item delete are destructive. Re-read project/item state after each authorized change.

## Labels

`gh label list --repo OWNER/REPO --json name,description,color,isDefault` is a read.
`create`, `edit`, and `delete` change repository metadata. Confirm exact name and
color; never delete a label merely because it is absent from a filtered listing.
Issue/PR label add/remove operations are also writes and need object re-reads.

## Failure handling

Report permission errors, review/check API gaps, merge conflicts, stale objects, and
rate limits with the exact target and command exit. Preserve the current object when
an edit/comment/merge fails; do not retry or close/reopen to "unstick" it. For a lower
PR in a stack, follow `stack-troubleshooting.md` rather than choosing an ordinary
merge or force-push.

## Official references

- [gh issue](https://cli.github.com/manual/gh_issue)
- [gh pr](https://cli.github.com/manual/gh_pr)
- [gh discussion](https://cli.github.com/manual/gh_discussion)
- [gh project](https://cli.github.com/manual/gh_project)
- [gh label](https://cli.github.com/manual/gh_label)
