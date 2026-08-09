# Git reference for the commit skill

Read this file only when the task needs low-level Git staging, noninteractive precise selection, or history cleanup.

## Core Git commit loop

```bash
git status --short
git diff --stat
# plan groups
git add -p -- <path>
git diff --cached
git commit -F "$msgfile"
```

## Interactive hunk tools

### Stage exact hunks

```bash
git add -p -- <path>
```

Use for mixed files when patch UI is usable.

Interactive patch controls worth remembering:

- `y` stage hunk
- `n` skip hunk
- `s` split hunk
- `e` manually edit hunk
- `q` quit

### Escalate when hunks are still too coarse

```bash
git add -e -- <path>
```

Use sparingly. It is powerful, but easy to make the patch invalid or confusing.

### Repair over-staging

```bash
git reset -p
# or
git restore --staged -p -- <path>
```

Use this when the index contains too much.

## Noninteractive precise staging

Use these flows when patch UI is unavailable, filenames are awkward, or you need exact line-level control.

### NUL-safe file-set staging

```bash
paths=$(mktemp)
printf '%s\0' "src/a.ts" "docs/odd name.md" > "$paths"
git add --pathspec-from-file="$paths" --pathspec-file-nul
git diff --cached --stat
```

Use the same path list for repair:

```bash
git restore --staged --pathspec-from-file="$paths" --pathspec-file-nul
```

### Stage exact hunks with a patch file

```bash
git add -N -- path/new-file
pick=$(mktemp)
git diff --unified=0 -- path/file path/new-file > "$pick"
# edit $pick until only the wanted hunks remain
git apply --check --cached --unidiff-zero "$pick"
git apply --cached --unidiff-zero "$pick"
git diff --cached -- path/file path/new-file
```

Notes:

- `git add -N` keeps new files visible to patch-based staging
- `--unified=0` reduces context so the patch is easier to trim
- If `git apply --check` fails, regenerate the patch from a fresh diff

### Reverse-apply to unstage exact hunks

```bash
drop=$(mktemp)
git diff --cached --unified=0 -- path/file > "$drop"
# edit $drop until only the staged hunks to remove remain
git apply --check -R --cached --unidiff-zero "$drop"
git apply -R --cached --unidiff-zero "$drop"
git diff --cached -- path/file
```

## Split the previous mixed commit

Git’s documented recipe:

```bash
git reset -N HEAD^
# stage the first logical group with patch or pathspec tools
git diff --cached
git commit -c HEAD@{1}
# repeat staging / diff --cached / commit as needed
```

Notes:

- `-N` keeps new files visible to patch mode
- `-c HEAD@{1}` reuses the previous commit message as a starting point
- If you already prepared a clean message file, commit with `-F "$msgfile"` after verification

## Fixup and autosquash flows

Use these when a change clearly belongs to an earlier commit, but immediate amend is not the best move.

```bash
git commit --fixup=<commit>
git commit --fixup=amend:<commit>
git commit --fixup=reword:<commit>
git rebase --autosquash <base>
```

Quick guidance:

- `--fixup=<commit>`: content-only fixup
- `--fixup=amend:<commit>`: refine content and replace message later
- `--fixup=reword:<commit>`: message-only intent

## Amend and reword

Prefer the same message-file workflow here too.

```bash
git commit --amend -F "$msgfile"
```

Notes:

- With staged changes, this amends content and message
- With no staged changes, this is effectively a reword
- Re-check `git diff --cached` before amending content into the last commit

## Merge / rebase / cherry-pick states

If the repo is already mid-operation, do not pile a normal commit on top. Finish or abort the existing state first.

```bash
git status --short --branch
git rebase --continue
git rebase --abort
git cherry-pick --continue
git cherry-pick --abort
git merge --abort
```

Use these only to resolve the in-progress operation the user already has, not as a surprise rewrite.

## Hook failures

- Read stderr; hooks often explain the exact policy they enforce
- If a hook rewrites files, refresh the diff and re-plan before committing again
- Do not use `--no-verify` unless the user explicitly approves and repo policy allows it

## Message-file workflow

Prefer message files over long `-m` chains.

```bash
git commit -F "$msgfile"
```

Policy still belongs in the skill:

- subject <= 52 unless repo style differs
- blank line before body
- body wrapped at 72

Git recommends short subjects, but does not enforce the limit.

## Message examples

Wrong:

```text
chore: various updates.
```

Right:

```text
chore(config): tighten commit lint
```

## Safety example

Wrong:

```text
Commit whatever is already staged without inspection.
```

Right:

```text
Inspect the cached diff or returned JSON state, then commit only accounted-for changes.
```

## Pathspec-from-file

Useful for many paths or tricky filenames.

```bash
git add --pathspec-from-file=.paths
git reset --pathspec-from-file=.paths
git restore --staged --pathspec-from-file=.paths
```

Use `--pathspec-file-nul` if you need NUL-separated entries.
Prefer this for staging and unstaging. Commit from the verified index with `git commit -F "$msgfile"`.

## Scripting hygiene

- Put options before positional args
- Use long options in scripts when clarity helps
- Use `--` when a path could be mistaken for a rev
- Verify every commit with `git diff --cached` before finalizing

## Caveats

- `git add -e` can create a patch that does not apply
- `git apply --cached` requires a fresh diff; regenerate after worktree or index changes
- `diff.interHunkContext` can fuse nearby hunks; be careful if you need finer splits
- `git commit <pathspec>` stages from the working tree and can bypass a carefully prepared index. Prefer explicit staging + `git commit -F "$msgfile"`
- Do not stop after one commit if multiple logical groups remain
