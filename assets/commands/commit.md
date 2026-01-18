---
description: Create atomic git commits with conventional commits
subtask: true
---

Create atomic, logically-separated git commits using conventional commits.

WORKING DIRECTORY: ${1:-.} (defaults to current directory)

## Granularity (CRITICAL)

- ONE logical change per commit - never bundle unrelated changes
- Use `git add -p` for mixed changes in a single file
- Interactive staging via pipe: `printf 'y\nn\ny\n' | git add -p <file>`
- Verify with `git diff --cached` before each commit

## Format

- Subject: ≤52 chars, imperative mood
- Format: type(scope): description
- Types: feat | fix | docs | style | refactor | perf | test | build | ci | chore

## Workflow

1. `git status -s` and `git diff --stat`
2. Group changes by logical unit
3. Stage precisely → verify → commit
4. Final: `git log --oneline -n <count>`

Return only: `git log --oneline` output of created commits.

$ARGUMENTS
