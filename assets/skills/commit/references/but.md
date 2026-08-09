# `but` reference for the commit skill

Read this file only when the repo is GitButler-managed and `but` is the write path.

## Core rules

- Start write or history work with:

```bash
but status --json
```

- Inspect exact change IDs with:

```bash
but diff --json
```

- For mutations, prefer:

```bash
but <mutation> --json --status-after
```

- Save large JSON outputs to temp files and inspect them with `jq` instead of relying on rendered text
- Use CLI IDs from `but status --json` and `but diff --json`
- Refresh IDs after every mutation; they may change after `commit`, `move`, `squash`, `reword`, `amend`, or `uncommit`
- Once in But mode, avoid raw Git write commands

## JSON-first loop

```bash
status_json=$(mktemp)
diff_json=$(mktemp)
but status --json > "$status_json"
but diff --json > "$diff_json"
# inspect branch / file / hunk IDs from JSON before mutating
```

Prefer this whenever the change set is large, split across stacks, or you need exact hunk ownership.

## Exact hunk commit

```bash
but status --json
but diff --json
but commit <branch> --message-file "$msgfile" --changes <id1>,<id2> --json --status-after
```

Notes:

- `--changes` can target exact file or hunk IDs
- `but diff --json` may expose one ID per split hunk
- After the commit, treat the returned status JSON as the new source of truth

## Assignment-first flow

Useful when changes belong to different stacks or branches, or when the same file spans multiple logical commits.

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

If the installed CLI supports `--json --status-after` here, prefer it and then refresh IDs.

### Reword a commit

Prefer message files. If the installed `but reword` lacks `--message-file`, pass the file contents explicitly.

```bash
message=$(cat "$msgfile")
but reword <commit-id> -m "$message"
```

After rewording, rerun `but status --json` before further mutations.

### Placeholder commit

```bash
but commit empty --before <target>
# or
but commit empty --after <target>
```

Useful when you want a destination commit before assigning or absorbing changes into it.

## Recovery flows

GitButler has a strong undo model.

```bash
but undo
but oplog restore <snapshot>
```

Use this if a move, squash, amend, or absorb plan goes sideways. After recovery, rerun `but status --json` and `but diff --json` before continuing.

## Caveats

- Cross-stack move to a precise position is not always one-step; sometimes move to the branch first, then reorder within the stack
- Some binary or text-converted diffs disable hunk-level operations
- Prefer returned JSON state over assumptions
- `reword`, `move`, `squash`, and `uncommit` can invalidate saved IDs
- Do not stop after the first valid commit if more logical groups remain
