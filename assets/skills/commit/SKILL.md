---
name: commit
description: "Create atomic conventional git commits. Activate when user asks to commit changes, write conventional commits, or says /commit."
---

# Commit Skill

Create atomic, logically separated git commits using conventional commits. Focus on WHY over WHAT. Use imperative mood and paragraph body (no bullet lists).

WORKING DIRECTORY: optional argument, default current directory.

## Granularity (critical)

- One logical change per commit; never bundle unrelated changes.
- If multiple logical units exist, create multiple commits; do not batch them into one.
- Renames/moves/structure-only changes are their own logical unit when separate from content changes.
- Use `git add -p` for mixed changes in a single file.
- Interactive staging via pipe: `printf 'y\nn\ny\n' | git add -p <file>`.
- Verify with `git diff --cached` before each commit.

## Format

- Subject <= 52 chars, imperative.
- Format: `type(scope): description`.
- Types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`.

## Workflow

1. `git status -s` and `git diff --stat`.
2. Group changes by logical unit.
3. Stage precisely -> verify -> commit.
4. Repeat steps 2-3 until all relevant changes are committed or user says stop.
5. Final: `git log --oneline -n <count>`.

Return only: `git log --oneline` output of created commits.

Optional arguments: $ARGUMENTS
