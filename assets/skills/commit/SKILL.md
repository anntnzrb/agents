---
name: commit
description: "Create granular, logically grouped commits with precise staging or hunk selection. Use whenever the user asks to commit changes, split work into multiple commits, stage or unstage hunks, write or polish commit messages, clean up commit history before handoff, or says /commit. Prefer multiple small truthful commits over one catch-all commit. In GitButler-managed repos, prefer `but`; elsewhere use `git`."
---

# Commit Skill

Turn a dirty worktree into the smallest honest set of commits. Plan commit groups first. Then stage, verify, commit, refresh, and repeat until all intended changes are handled.

WORKING DIRECTORY: optional argument, default current directory.

## Goals
- One logical unit per commit
- No early work hidden inside a later-message catch-all commit
- Exact staging; hunk-level when needed
- Message-file workflow every time
- Repo conventions first; fallback to conventional commits

## Engine selection
1. Read repo-local guidance first: `AGENTS.md`, `CONTRIBUTING.md`, commit docs, templates.
2. Use **But mode** when the repo is GitButler-managed and `but status --json` is the natural write path.
3. Otherwise use **Git mode**.
4. Once in But mode, do not use raw `git add`, `git commit`, `git rebase`, or similar write commands. Read-only Git inspection is fine.

## Commit loop
1. Inspect the full state before the first commit.
2. Draft all logical groups.
3. Commit only the first group.
4. Refresh remaining changes.
5. Re-plan if IDs or hunks changed.
6. Repeat until all intended changes are committed or the user says stop.
7. End with a one-line list of the created commits.

## Grouping heuristics
- Separate unrelated concerns.
- Separate rename or move-only work from behavior changes when possible.
- Separate formatting-only work from semantic changes.
- Separate tests from implementation when independently meaningful.
- Separate docs, config, and build changes unless tightly coupled.
- Mixed file: split by hunk. Escalate from file-level to hunk-level rather than bundling.
- Prefer a few small truthful commits over one “final state” commit.

## Message policy
Use repo-specific convention if defined. Otherwise use conventional commits.

### Default format
- Subject: `type(scope): description`
- Types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`
- Subject: imperative, specific, max 52 chars
- Blank line between subject and body
- Body: wrap at 72 chars
- Focus on intent and effect, not file-by-file narration
- No bullets unless the repo style strongly prefers them

### Message-file rule
Always draft the full message into a temp file first.
- Git: `git commit -F "$msgfile"`
- But: `but commit --message-file "$msgfile"`

This keeps formatting stable and avoids shell-quoting mistakes.

## Git mode
Use this in normal Git repos.

### Inspect
```bash
git status --short
git diff --stat
```

If grouping is unclear, inspect more:
```bash
git diff
git diff --cached
```

### Stage precisely
Preferred order:
1. Whole-file stage only when the file is one logical unit.
2. `git add -p -- <path>` for mixed files.
3. `git add -e -- <path>` when patch mode still groups too much together.

### Repair over-staging
If the index got too much:
```bash
git reset -p
# or
git restore --staged -p -- <path>
```

### Verify before every commit
```bash
git diff --cached
```

### Commit
```bash
git commit -F "$msgfile"
```

### Advanced Git flows
Read `references/git.md` when you need:
- split the previous mixed commit
- `fixup!` / `amend!` / `reword!` flows
- `--pathspec-from-file`
- caveats around `git add -e`

## But mode
Use this in GitButler-managed repos.

### Core rules
- Start write or history work with:
```bash
but status --json
```
- For mutations, prefer:
```bash
but <mutation> --json --status-after
```
- Use CLI IDs from `but status --json` or `but diff --json`.
- Prefer `but` writes over raw Git writes.

### Exact hunk commit
1. Inspect:
```bash
but status --json
but diff --json
```
2. Pick exact file or hunk IDs.
3. Commit only those changes:
```bash
but commit <branch> --message-file "$msgfile" --changes <id1>,<id2> --json --status-after
```

### Assignment-first flow
Useful when work spans multiple stacks or branches:
```bash
but stage <file-or-hunk> <branch> --json --status-after
but commit <branch> --message-file "$msgfile" --only --json --status-after
```

### Repair and cleanup
Use:
- `but unstage`
- `but rub <file-or-hunk> zz`
- `but amend`
- `but uncommit`
- `but move`
- `but squash`
- `but reword`
- `but absorb`
- `but mark`
- `but undo`
- `but oplog restore`

Read `references/but.md` when you need exact command patterns or caveats.

## Split-a-mixed-commit rule
If the task is “split the last mixed commit”:
- Git mode: use the documented reset/patch loop from `references/git.md`
- But mode: prefer native history surgery (`uncommit`, `move`, `squash`, `reword`, `commit empty`, `absorb`) instead of raw Git rewrites

## Safety checks
- Never commit before seeing the whole change set.
- Never stop after the first valid commit if more logical groups remain.
- Never trust staging blindly; verify with cached diff or returned JSON state.
- If a repo has custom commit rules, follow them over the fallback format.
- If the user asks for only part of the work to be committed, leave the rest untouched.

## Return format
Return only a plain-text one-line list of the commits you created, newest first.

Example:
```text
a1b2c3d feat(parser): split env parsing
d4e5f6a test(parser): cover empty value case
```

## References
Load only what you need:
- `references/git.md` - patch-mode Git flows, split-commit recipe, fixup/autosquash, pathspec tips
- `references/but.md` - GitButler/`but` commit flows, hunk IDs, assignment-first workflows, repair tools

Optional arguments: $ARGUMENTS
