# Git reference for the commit skill

Read this file only when the task needs low-level Git staging or history cleanup.

## Core Git commit loop
```bash
git status --short
git diff --stat
# plan groups
git add -p -- <path>
git diff --cached
git commit -F "$msgfile"
```

## Hunk tools

### Stage exact hunks
```bash
git add -p -- <path>
```
Use for mixed files.

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

## Split the previous mixed commit
Git’s documented recipe:

```bash
git reset -N HEAD^
git add -p
git diff --cached
git commit -c HEAD@{1}
# repeat add -p / diff --cached / commit as needed
```

Notes:
- `-N` keeps new files visible to patch mode.
- `-c HEAD@{1}` reuses the previous commit message as a starting point.
- If you already prepared a clean message file, commit with `-F "$msgfile"` after verification.

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

## Message-file workflow
Prefer message files over long `-m` chains.

```bash
git commit -F "$msgfile"
```

Policy still belongs in the skill:
- subject <= 52
- blank line before body
- body wrapped at 72

Git recommends short subjects, but does not enforce the limit.

## Pathspec-from-file
Useful for many paths or tricky filenames.

```bash
git add --pathspec-from-file=.paths
git commit --pathspec-from-file=.paths
git reset --pathspec-from-file=.paths
git restore --staged --pathspec-from-file=.paths
```

Use `--pathspec-file-nul` if you need NUL-separated entries.

## Scripting hygiene
- Put options before positional args.
- Use long options in scripts when clarity helps.
- Use `--` when a path could be mistaken for a rev.
- Verify every commit with `git diff --cached` before finalizing.

## Caveats
- `git add -e` can create a patch that does not apply.
- `diff.interHunkContext` can fuse nearby hunks; be careful if you need finer splits.
- Do not stop after one commit if multiple logical groups remain.
