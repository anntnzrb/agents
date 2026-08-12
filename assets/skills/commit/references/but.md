# `but` reference for commit skill

Use only when repo is GitButler-managed and `but` is the write path.

## Core rules

Start write/history work:

```bash
but status --json
```

Inspect exact change IDs:

```bash
but diff --json
```

Mutations: prefer:

```bash
but <mutation> --json --status-after
```

Large JSON: save to temp files; inspect with `jq`, not rendered text. Use CLI IDs from `but status --json` and `but diff --json`. Refresh IDs after every mutation; `commit`, `move`, `squash`, `reword`, `amend`, and `uncommit` may change them. But mode: avoid raw Git write commands.

## JSON-first loop

```bash
status_json=$(mktemp)
diff_json=$(mktemp)
but status --json > "$status_json"
but diff --json > "$diff_json"
# inspect branch / file / hunk IDs from JSON before mutating
```

Prefer this loop for large change sets, changes split across stacks, or exact hunk ownership.

## Exact hunk commit

```bash
but status --json
but diff --json
but commit <branch> --message-file "$msgfile" --changes <id1>,<id2> --json --status-after
```

`--changes` targets exact file or hunk IDs; `but diff --json` may expose one ID per split hunk. After commit, returned status JSON is the new source of truth.

## Assignment-first flow

For changes belonging to different stacks/branches, or files spanning multiple logical commits:

```bash
but stage <file-or-hunk> <branch> --json --status-after
but commit <branch> --message-file "$msgfile" --only --json --status-after
```

## Repair tools

- `but unstage`
- `but rub <file-or-hunk> zz`
- `but amend <file-id> <commit-id>`
- `but uncommit <commit-or-file-in-commit>`
- `but move <commit> <target>`
- `but squash <commits...>`
- `but reword <commit>`
- `but absorb`
- `but mark`

## History surgery

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

If installed CLI supports `--json --status-after` here, prefer it, then refresh IDs.

### Reword a commit

Prefer message files. If installed `but reword` lacks `--message-file`, pass file contents explicitly.

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

Useful for creating a destination commit before assigning or absorbing changes into it.

## Recovery flows

GitButler has a strong undo model:

```bash
but undo
but oplog restore <snapshot>
```

Use after a move, squash, amend, or absorb plan goes sideways. After recovery, rerun `but status --json` and `but diff --json` before continuing.

## Caveats

- Cross-stack move to a precise position is not always one-step; sometimes move to the branch first, then reorder within the stack.
- Some binary or text-converted diffs disable hunk-level operations.
- Prefer returned JSON state over assumptions.
- `reword`, `move`, `squash`, and `uncommit` can invalidate saved IDs.
- Do not stop after the first valid commit if more logical groups remain.
