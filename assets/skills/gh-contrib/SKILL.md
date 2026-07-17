---
name: gh-contrib
description: Create upstream GitHub issues and pull requests following repository contribution rules.
license: GPL-3.0-or-later
metadata:
  author: anntnzrb
allowed-tools: ""
---

# GitHub Contribution Workflow

## Prerequisites

- Changes committed in a feature branch.
- Repository contribution rules inspected read-only.
- Duplicate issues and pull requests checked read-only.
- External writes require explicit user authorization.

## Workflow

### 1. Check Contribution Guidelines

Inspect contribution guidelines read-only:

- Look for CONTRIBUTING.md, README, issue/PR templates
- Extract: title format, target branch, required labels

### 2. Detect Fork & Push

Inspect remotes first. Before pushing, state the fork, branch, issue, and PR plan. If the user's request
did not explicitly authorize those writes, ask once before continuing.

```bash
git remote -v  # identify fork remote
git push -u <fork-remote> <branch>
```

### 3. Create Issue

```bash
gh issue create --repo <owner>/<repo> \
  --title "<title per guidelines>" \
  --body "<body>"
```

### 4. Create PR

```bash
gh pr create --repo <owner>/<repo> \
  --head <fork-user>:<branch> \
  --base <target-branch> \
  --title "<title>" \
  --body "## Summary

<description>

Closes #<issue-number>"
```

### 5. Comment on Issue

```bash
gh issue comment <issue-number> --repo <owner>/<repo> --body "PR: #<pr-number>"
```

### 6. Verify

Re-read the created issue and pull request. Report their URLs and any failed or skipped mutation.

## Default Conventions

Use only if no contribution guidelines found:

| Type    | Issue Prefix | PR Prefix |
| ------- | ------------ | --------- |
| Feature | `[FEATURE]:` | `feat:`   |
| Bug     | `[BUG]:`     | `fix:`    |
| Docs    | `[DOCS]:`    | `docs:`   |
| Chore   | `[CHORE]:`   | `chore:`  |

## Flow

```
changes committed -> push to fork -> open issue -> open pr -> comment on issue
```
