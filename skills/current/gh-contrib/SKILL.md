---
disable-model-invocation: true
name: gh-contrib
description: "Use when creating an upstream GitHub issue or pull request under a repository's contribution rules."
license: AGPL-3.0-or-later
metadata:
  author: anntnzrb

---

# GitHub Contribution Workflow

## Prerequisites

- Changes committed on a feature branch
- Contribution rules and duplicate issues/pull requests inspected read-only
- External writes require explicit user authorization

## Workflow

### Contribution Guidelines

Inspect read-only: CONTRIBUTING.md, README, issue/PR templates. Extract title format, target branch, required labels.

### Fork & Push

Inspect remotes first. Before pushing, state fork, branch, issue, and PR plan. If the user's request did not explicitly authorize those writes, ask once before continuing.

```bash
git remote -v  # identify fork remote
git push -u <fork-remote> <branch>
```

### Create Issue

```bash
gh issue create --repo <owner>/<repo> \
  --title "<title per guidelines>" \
  --body "<body>"
```

### Create PR

```bash
gh pr create --repo <owner>/<repo> \
  --head <fork-user>:<branch> \
  --base <target-branch> \
  --title "<title>" \
  --body "## Summary

<description>

Closes #<issue-number>"
```

### Comment on Issue

```bash
gh issue comment <issue-number> --repo <owner>/<repo> --body "PR: #<pr-number>"
```

### Triage PR CI

- MUST inspect PR checks read-only and distinguish GitHub Actions from external providers.
- GitHub Actions: MUST read failing job and step logs.
- Before any CI-driven code change, MUST identify the root cause and have an existing request or explicit authorization.
- External providers: report check status, name, and details URL.
- NEVER claim unavailable external-provider logs were inspected.

### Handle Review Threads

- MUST inspect reviews read-only and fetch thread-aware state before any mutation.
- MUST preserve every comment's file and line anchor.
- MUST ignore resolved or outdated threads unless relevant to current work.
- MUST cluster related actionable comments by underlying request.
- Before replying, resolving threads, or making unrequested code changes, MUST apply the Prerequisites authorization rule.
- Missing authorization? MUST request it once before mutation.

### Verify

Re-read the created issue and pull request. Report their URLs and any failed or skipped mutation.

## Default Conventions

Use only if no contribution guidelines found:

|Type|Issue Prefix|PR Prefix|
|---|---|---|
|Feature|`[FEATURE]:`|`feat:`|
|Bug|`[BUG]:`|`fix:`|
|Docs|`[DOCS]:`|`docs:`|
|Chore|`[CHORE]:`|`chore:`|

## Flow

```
changes committed -> push to fork -> open issue -> open pr -> comment on issue
```
