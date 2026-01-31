---
name: commit
description: "Create atomic conventional git commits. Activate when user asks to commit changes, write conventional commits, or says /commit."
---

# Commit Skill

Create atomic, logically separated git commits. First follow any repo-specific commit guidelines; if none exist, use the conventional commits format below. Focus on WHY over WHAT. Use imperative mood and paragraph body (no bullet lists).

WORKING DIRECTORY: optional argument, default current directory.

## Granularity (critical)

- One logical change per commit; never bundle unrelated changes
- If multiple logical units exist, create multiple commits; do not batch them into one
- Renames/moves/structure-only changes are their own logical unit when separate from content changes
- Use `git add -p` for mixed changes in a single file
- Interactive staging via pipe: `printf 'y\nn\ny\n' | git add -p <file>`
- Verify with `git diff --cached` before each commit

## Format

- If the repo defines commit conventions (`*.md` files), follow them
- Otherwise use conventional commits:
- Subject <= 52 chars, imperative
- Format: `type(scope): description`
- Types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`

## Workflow

1. Check for repo commit guidelines
2. `git status -s` and `git diff --stat`
3. Group changes by logical unit
4. Stage precisely -> verify -> commit
5. Repeat steps 3-4 until all relevant changes are committed or user says stop
6. Final: `git log --oneline -n <count>`

Return only: `git log --oneline` output of created commits

Optional arguments: $ARGUMENTS
