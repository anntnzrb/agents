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

## Required follow-up reads

| Reference                 | Read when                                                                                                                                                                                                               |
| ------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `references/git.md`       | Git mode needs patch-mode details, noninteractive precise staging, partial new-file staging, pathspec files, amend/fixup/autosquash/reword, split-last-commit, or recovery from bad staging/hook/merge states.          |
| `references/but.md`       | But mode needs exact JSON command patterns, hunk IDs, assignment-first flows, message-file-safe rewording, history surgery, branch/stack movement, or `but` recovery sequences.                                         |
| `references/changelog.md` | Any touched repo uses or may require `CHANGELOG.md`, `NEWS.md`, `.changeset/`, `newsfragments/`, `changelog.d/`, release-please, semantic-release, Towncrier, issue-closing release notes, or generated release output. |

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

Detailed message examples live in `references/git.md` and repo history; keep SKILL decisions here.

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

Detailed changelog examples live in `references/changelog.md`; keep fragments/manual entries with the code commit they describe.

## Git mode

Use this in normal Git repos.

- Inspect with `git status --short` and `git diff --stat`; use `git diff` / `git diff --cached` when grouping is unclear.
- Stage whole files only when each file is one logical unit.
- Use `git add -p -- <path>` for mixed files when patch UI is usable.
- Escalate to `git add -e -- <path>` only when patch mode groups too much together.
- Use patch-file or pathspec-file flows from `references/git.md` when exact noninteractive control, weird filenames, or partial new-file staging are required.
- Repair over-staging with `git reset -p`, `git restore --staged -p -- <path>`, or reverse-apply patterns from `references/git.md`.
- Before every commit, verify `git diff --cached`; the cached diff MUST match the intended commit.
- Commit with `git commit -F "$msgfile"`.

Read `references/git.md` for noninteractive precise staging, split-last-commit, amend/fixup/autosquash/reword, `--pathspec-from-file`, recovery from hook/merge/rebase/cherry-pick states, and caveats around `git add -e` or `git commit <pathspec>`.

## But mode

Use this in GitButler-managed repos.

- Start write or history work with `but status --json`.
- Inspect exact file/hunk IDs with `but diff --json`.
- For mutations, SHOULD use `but <mutation> --json --status-after`.
- Use CLI IDs from `but status --json` or `but diff --json`.
- SHOULD use `but` writes over raw Git writes.
- Refresh IDs after every mutation. NEVER assume old IDs still point at the same hunks or commits.
- Commit exact files/hunks with `but commit <branch> --message-file "$msgfile" --changes <id1>,<id2> --json --status-after`.
- For assignment-first flows, use `but stage <file-or-hunk> <branch> --json --status-after` before `but commit <branch> --message-file "$msgfile" --only --json --status-after`.
- Repair and cleanup commands include `but unstage`, `but rub`, `but amend`, `but uncommit`, `but move`, `but squash`, `but reword`, `but absorb`, `but mark`, `but undo`, and `but oplog restore`.

Read `references/but.md` for exact JSON command patterns, assignment-first flows, message-file-safe rewording, history surgery, branch/stack movement, and recovery sequences.

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

Reference examples live in `references/git.md` and `references/but.md`; safety checks above are binding.

## Return format

Return a compact plain-text report:

- `commits:` created commits with SHA + subject, oldest -> newest
- `validation:` commands run, skipped, or failed
- `changelog:` updated files or `none`
- `remaining:` clean worktree or remaining paths intentionally left uncommitted

For preview-only or dry-run:

- say `no commits created`
- print the proposed commit message(s) and split order instead

## Reference routing

Use the Required follow-up reads table near the top of this file; do not preload commit references before engine selection makes them relevant.

Optional arguments: $ARGUMENTS
