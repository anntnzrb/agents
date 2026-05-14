---
name: commit
description: Create granular, logically grouped commits with precise staging or hunk selection. Use whenever the user asks to commit changes, split or preview commits, stage or unstage hunks, write or polish commit messages, manage changelog fragments, clean up commit history before handoff, or says /commit. Prefer multiple small truthful commits over one catch-all commit. In GitButler-managed repos, prefer `but`; elsewhere use `git`.
license: GPL-3.0-or-later
metadata:
  author: anntnzrb
allowed-tools: ""
disable-model-invocation: true
---

# Commit Skill

Turn a dirty worktree into the smallest honest set of commits. Plan the full set first. Stage exactly, validate intentionally, commit from a message file, refresh state, and repeat until every intended change is committed or explicitly left behind.

WORKING DIRECTORY: optional argument, default current directory.

## Goals
- Create one logical unit per commit.
- Keep early work out of later catch-all commits.
- Stage exact files or hunks; use hunk-level staging for mixed files.
- Use message-file commits every time.
- Follow repo conventions before fallback conventions.
- Commit changelog or release fragments with the code they describe.
- End with a complete accounting of committed and remaining work.

## Engine selection
1. Discover repo policy first. Read the smallest repo-local set that controls commits:
   - nearest + root `AGENTS.md`
   - `CONTRIBUTING.md`, `README.md`, release docs, issue-closing rules
   - commit templates, `.gitmessage`, `commitlint*`, hook config (`.husky/`, `.lefthook/`, `.pre-commit-config.yaml`, `lint-staged`)
   - changelog/release systems: `CHANGELOG.md`, `.changeset/`, `newsfragments/`, `changelog.d/`, release automation
   - recent commit subjects when style is still unclear
   Extract message format, trailers/signoff/DCO, required validation, changelog expectations, issue refs, and push policy.
2. Use **But mode** when the repo is GitButler-managed and `but status --json` is the natural write path.
3. Otherwise use **Git mode**.
4. In But mode, NEVER use raw `git add`, `git commit`, `git rebase`, or equivalent write commands. Read-only Git inspection MAY be used.

## Planning rules
Before the first write:
- Inspect the full state. NEVER commit from a partial view.
- Fast-path trivial diffs. If the full change is whitespace-only, formatting-only, import-only, or comment-only, SHOULD use one small `style` or `chore` commit and usually skip changelog work unless repo policy requires it.
- Draft the full commit plan:
  - every intended staged hunk belongs to exactly one commit
  - mixed files name exact hunk or line ownership per commit
  - dependency order is explicit when order matters
  - validation and changelog handling are decided per commit
- If the user asked for preview, dry-run, or message help only, stop after the plan.

## Commit loop
1. Inspect the full state before the first commit.
2. Preview the plan:
   - single commit: message, files/hunks, validation plan, changelog intent
   - split plan: numbered commits, files/hunks, dependencies, execution order
3. If grouping, policy, or validation scope is ambiguous, call `clarify` before mutating.
4. Commit only the next approved group.
5. Refresh remaining changes after each commit.
6. Re-plan if hunk IDs, file ownership, changelog targets, or validation scope changed.
7. Repeat until all intended changes are committed or the user says stop.
8. End with a compact report: commits created, validation run/skipped, changelog updates, and remaining changes.

## Grouping heuristics
- Separate unrelated concerns.
- Separate rename or move-only work from behavior changes when possible.
- Separate formatting-only work from semantic changes.
- Separate tests from implementation when independently meaningful.
- Separate docs, config, and build changes unless tightly coupled.
- Split mixed files by hunk. Escalate from file-level to hunk-level rather than bundling.
- Keep changelog fragments or manual changelog hunks with the commit they describe.
- Prefer a few small truthful commits over one “final state” commit.

## Message policy
Use repo-specific convention if defined. Otherwise use conventional commits.

### Default format
- Subject: `type(scope): description`
- Types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`
- Subject MUST be imperative, specific, and max 52 chars unless repo history clearly uses a different limit.
- Leave one blank line between subject and body.
- Wrap body at 72 chars.
- Focus on intent and effect, not file-by-file narration.
- Avoid bullets unless repo style strongly prefers them.

### Message lint
Before commit, verify:
- subject has no trailing period
- subject is imperative
- subject is max 52 chars unless repo history clearly uses a different limit
- subject has no filler words: `various`, `several`, `misc`, `improved`, `enhanced`, `better`
- message has no meta phrases: `this commit`, `this change`, `updated code`, `modified files`, `address review comments`
- scope and type fit the touched files
- repo-specific tense, trailer, signoff, and issue-reference style override fallback style

WRONG:
```text
chore: various updates.
```

RIGHT:
```text
chore(config): tighten commit lint
```

### Message-file rule
Always draft the full message into a temp file first.
- Git: `git commit -F "$msgfile"`
- But: `but commit --message-file "$msgfile"`

This preserves formatting and avoids shell-quoting mistakes. NEVER pass multiline messages directly on the command line.

## Validation gate
- Discover repo-required validation before committing.
- Prefer the narrowest meaningful gate for the affected package/app: focused tests, lint, typecheck, or build before whole-repo suites.
- NEVER invent expensive validation when the repo gives no signal. If only heavy or ambiguous validation exists, call `clarify`.
- If validation fails, stop before the next commit. Report:
  - failing command
  - whether anything was already committed
  - exact remaining staged/unstaged state
- If the user explicitly wants unvalidated commits, say so in the final report.

## Changelog behavior
When the repo expects changelog or release fragments:
- Detect whether the repo uses manual changelogs or fragment/generated systems.
- Manual `CHANGELOG.md` / `NEWS.md` / `HISTORY.md`:
  - read the current `[Unreleased]` section first
  - add only user-visible entries
  - skip trivial/style/test-only/internal refactor entries unless repo policy requires them
  - deduplicate or update draft entries instead of appending duplicates
  - NEVER edit released sections
- Fragment systems (`.changeset`, `newsfragments`, `changelog.d`, Towncrier, release-please, semantic-release):
  - commit the fragment with the code change it describes
  - NEVER hand-edit generated release output unless repo docs explicitly require it
- If changelog policy is ambiguous, missing an `[Unreleased]` section, or release automation owns the file, stop and ask.

Load `references/changelog.md` when changelog or release automation is relevant.

WRONG:
```text
Commit code now and add the changelog later.
```

RIGHT:
```text
Commit the changelog fragment with the code change it describes.
```

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
2. `git add -p -- <path>` for mixed files when patch UI is usable.
3. `git add -e -- <path>` when patch mode still groups too much together.
4. Patch-file or pathspec-file flows from `references/git.md` when exact noninteractive control, weird filenames, or partial new-file staging are required.

### Repair over-staging
If the index got too much:
```bash
git reset -p
# or
git restore --staged -p -- <path>
```

For noninteractive repair or exact reversals, use the reverse-apply patterns in `references/git.md`.

### Verify before every commit
```bash
git diff --cached
```

NEVER trust staging blindly. The cached diff MUST match the intended commit.

### Commit
```bash
git commit -F "$msgfile"
```

### Advanced Git flows
Read `references/git.md` when you need:
- noninteractive precise staging
- split the previous mixed commit
- amend, fixup, autosquash, or reword flows
- `--pathspec-from-file`
- recovery from hook failures, merge/rebase/cherry-pick states, or bad staging
- caveats around `git add -e` and `git commit <pathspec>`

## But mode
Use this in GitButler-managed repos.

### Core rules
- Start write or history work with:
```bash
but status --json
```
- For mutations, SHOULD use:
```bash
but <mutation> --json --status-after
```
- Use CLI IDs from `but status --json` or `but diff --json`.
- SHOULD use `but` writes over raw Git writes.
- Refresh IDs after every mutation. NEVER assume old IDs still point at the same hunks or commits.

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

Read `references/but.md` when you need exact command patterns, message-file-safe reword flows, or recovery sequences.

## Split-a-mixed-commit rule
If the task is “split the last mixed commit”:
- Git mode: use the documented reset/patch loop from `references/git.md`
- But mode: SHOULD use native history surgery (`uncommit`, `move`, `squash`, `reword`, `commit empty`, `absorb`) instead of raw Git rewrites

## Edge cases
Stop and reassess before writing when you see:
- merge, rebase, cherry-pick, or revert in progress
- submodules, sparse checkouts, or binary files
- rename-heavy diffs where rename-only and content changes should separate
- generated files or lockfiles mixed with hand-written code
- hooks that fail or mutate files unexpectedly
- user requested only a subset and the rest of the worktree is dirty

## Safety checks
- NEVER commit before seeing the whole change set.
- If nothing is staged, stage only the intended files/hunks unless the user explicitly said staged-only.
- NEVER leave staged files/hunks unaccounted for. Every staged change MUST be committed now or intentionally left untouched because the user asked.
- NEVER trust staging blindly; verify with cached diff or returned JSON state.
- If split-plan dependencies become circular or unclear, stop and re-plan.
- NEVER push unless the user explicitly asked for it.
- If a repo has custom commit rules, follow them over the fallback format.
- If the user asks for only part of the work to be committed, leave the rest untouched.

WRONG:
```text
Commit whatever is already staged without inspection.
```

RIGHT:
```text
Inspect the cached diff or returned JSON state, then commit only accounted-for changes.
```

## Return format
Return a compact plain-text report:
- `commits:` created commits with SHA + subject, oldest -> newest
- `validation:` commands run, skipped, or failed
- `changelog:` updated files or `none`
- `remaining:` clean worktree or remaining paths intentionally left uncommitted

For preview-only or dry-run:
- say `no commits created`
- print the proposed commit message(s) and split order instead

## References
Load only what you need:
- `references/git.md` - patch-mode Git flows, noninteractive precise staging, split/recovery, fixup/autosquash, pathspec tips
- `references/but.md` - GitButler/`but` JSON workflows, hunk IDs, history surgery, repair tools, recovery
- `references/changelog.md` - manual changelog vs fragment systems, verification, grouping rules

Optional arguments: $ARGUMENTS
