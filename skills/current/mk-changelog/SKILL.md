---
name: mk-changelog
description: "Generate Keep a Changelog entries and release notes from Git commits, PRs, or staged diffs."
license: AGPL-3.0-or-later
metadata:
  author: anntnzrb
---

# Make Changelog

Generate structured, user-facing changelog entries and release notes from Git commit ranges, GitHub Pull Requests, or staged diffs. Use the bundled Python CLI to inspect repository state deterministically and patch target `CHANGELOG.md` files idempotently.

## Public entrypoints

The primary entrypoint for `mk-changelog` is the Python CLI at `scripts/cli.py`.

```text
uv run --script <skill-dir>/scripts/cli.py <command> [options]
```

## Required follow-up reads

| Need | Read | When |
| --- | --- | --- |
| Keep a Changelog standards & categories | `references/conventions.md` | Before drafting or categorizing entries |
| Semantic synthesis prompt templates | `references/prompts.md` | When generating changelog bullets from prepared context |

## Workflow

1. Resolve `<skill-dir>` to this skill directory.
2. Extract deterministic commit, PR, diff, and monorepo changelog boundary context:

   ```text
   # 1. From a local commit range (e.g. branch to main, or tag to HEAD)
   uv run --script <skill-dir>/scripts/cli.py prepare --range main..HEAD [--repo PATH]

   # 2. From a GitHub Pull Request URL or number
   uv run --script <skill-dir>/scripts/cli.py prepare --pr https://github.com/owner/repo/pull/123

   # 3. From local staged or working tree changes
   uv run --script <skill-dir>/scripts/cli.py prepare --staged [--repo PATH]

3. The command outputs a single structured JSON payload containing:
   - `commits`: normalized commit records (hash, subject, category, author, PR reference, revert status).
   - `boundaries`: mapped `CHANGELOG.md` paths with their respective modified files.
   - `existing_entries`: already documented items under `## [Unreleased]` to prevent duplicates.
   - `contributors`: external contributors attribution mapping.
   - `diff_stat`: file-level change statistics.

4. Distill and synthesize user-facing entries using the prompt guidance in `references/prompts.md`. Focus strictly on user-observable behavior; omit internal refactoring, tests, and CI churn.

5. Output the result depending on your goal:

   - **For PR Body / Release Notes (no file writes):**
     ```text
     uv run --script <skill-dir>/scripts/cli.py format --entries-file <temp-dir>/entries.json
     ```

   - **For CHANGELOG.md update (idempotent disk patch under ## [Unreleased]):**
     ```text
     uv run --script <skill-dir>/scripts/cli.py patch --target CHANGELOG.md --entries-file <temp-dir>/entries.json
     ```
## Invariants

- Keep entries grouped by standard Keep a Changelog categories: `Breaking Changes`, `Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, `Security`.
- Start each entry with a past-tense verb (Added, Fixed, Changed, Updated) and omit trailing periods.
- Preserve deterministic community attribution format: `([#123](url) by @user)`.
- Never duplicate entries already present under `## [Unreleased]`.
- In monorepos, update the nearest package-level `CHANGELOG.md` unless instructed to target the root changelog.
