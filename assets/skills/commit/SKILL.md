---
name: commit
description: Create, split, stage, unstage, or polish precise Git commits and commit history.
license: GPL-3.0-or-later
metadata:
  author: anntnzrb

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

| Need | Read | When |
| --- | --- | --- |
| End-to-end commit execution | `references/workflow.md` | Before planning, grouping, messaging, validating, handling changelogs, splitting, or recovering |
| Precise Git staging/history | `references/git.md` | For patch-mode, partial new files, pathspecs, amend/fixup/reword, split-last-commit, or recovery |
| GitButler writes/history | `references/but.md` | For JSON mutations, hunk IDs, assignment-first flows, rewording, surgery, branch movement, or recovery |
| Changelog/release handling | `references/changelog.md` | When the repo may use changelogs, fragments, release automation, or issue-closing notes |

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
