# `but` reference for the commit skill

Read this file only when the repo is GitButler-managed and `but` is the write path.

## Core rules
- Start write or history work with:
```bash
but status --json
```
- For mutations, prefer:
```bash
but <mutation> --json --status-after
```
- Use CLI IDs from `but status --json` and `but diff --json`.
- Once in But mode, avoid raw Git write commands.

## Exact hunk commit
```bash
but status --json
but diff --json
but commit <branch> --message-file "$msgfile" --changes <id1>,<id2> --json --status-after
```

Notes:
- `but` uses `--message-file`, not `-F`.
- `--changes` can target exact file or hunk IDs.
- Refresh IDs after each mutation; they may change.

## Assignment-first flow
Useful when changes belong to different stacks or branches.

```bash
but stage <file-or-hunk> <branch> --json --status-after
but commit <branch> --message-file "$msgfile" --only --json --status-after
```

## Repair tools
Use these when grouping needs cleanup:
- `but unstage`
- `but rub <file-or-hunk> zz`
- `but amend <file-id> <commit-id>`
- `but uncommit <commit-or-file-in-commit>`
- `but move <commit> <target>`
- `but squash <commits...>`
- `but reword <commit>`
- `but absorb`
- `but mark`

## History surgery patterns

### Amend exact work into a commit
```bash
but amend <file-id> <commit-id> --json --status-after
```

### Move a commit
```bash
but move <source-commit-id> <target-commit-id> --json --status-after
but move <source-commit-id> <branch-id> --json --status-after
```

### Squash commits
```bash
but squash <commit-a> <commit-b>
# or
but squash <branch>
```

### Reword a commit
```bash
but reword <commit-id> -m "new subject\n\nnew body"
```
Use message files or editor flow if the message is long.

### Placeholder commit
```bash
but commit empty --before <target>
# or
but commit empty --after <target>
```
Useful when you want a destination commit before assigning or absorbing changes into it.

## Safety net
GitButler has a strong undo model.

```bash
but undo
but oplog restore <snapshot>
```

Use this if a move, squash, or absorb plan goes sideways.

## Caveats
- Cross-stack move to a precise position is not always one-step; sometimes move to the branch first, then reorder within the stack.
- Some binary or text-converted diffs disable hunk-level operations.
- Prefer returned JSON state over assumptions.
- Do not stop after the first valid commit if more logical groups remain.
