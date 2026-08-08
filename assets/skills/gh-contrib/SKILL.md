---
name: gh-contrib
description: Create upstream GitHub issues and pull requests following repository contribution rules.
license: GPL-3.0-or-later
metadata:
  author: anntnzrb

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

### 6. Triage PR CI

- You MUST inspect PR checks read-only and distinguish GitHub Actions from external providers.
- For GitHub Actions, you MUST read failing job and step logs.
- Before any CI-driven code change, you MUST identify the root cause and have an existing request or explicit authorization.
- For external providers, you MUST report check status, name, and details URL.
- NEVER claim unavailable external-provider logs were inspected.

### 7. Handle Review Threads

- You MUST inspect reviews read-only and fetch thread-aware state before any mutation.
- You MUST preserve every comment's file and line anchor.
- You MUST ignore resolved or outdated threads unless relevant to current work.
- You MUST cluster related actionable comments by underlying request.
- Before replying, resolving threads, or making unrequested code changes, you MUST apply the Prerequisites authorization rule.
- Missing authorization? You MUST request it once before mutation.

### 8. Verify

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
