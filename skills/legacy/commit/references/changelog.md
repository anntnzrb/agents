# Changelog reference for the commit skill

Read this file only when the repo has changelogs, release-note fragments, or release automation.

## Detect the system

Inspect repo docs and nearby release files before editing anything.

```bash
rg -n "changeset|towncrier|release-please|semantic-release|Keep a Changelog|newsfragment|changelog" README.md CONTRIBUTING.md package.json pyproject.toml .github/workflows .changeset 2>/dev/null
```

Common patterns:

- Manual files: `CHANGELOG.md`, `NEWS.md`, `HISTORY.md`
- Fragment systems: `.changeset/*.md`, `newsfragments/*`, `changelog.d/*`, Towncrier
- Generated release output: release-please, semantic-release, version scripts, release PR automation

## Manual changelog rules

- Read the current draft section first, usually `[Unreleased]`
- Add only user-visible changes
- Reuse the file's existing headings. If it follows Keep a Changelog, common sections are `Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, `Security`
- Keep the changelog hunk in the same logical commit as the change it describes
- Deduplicate or update draft entries instead of appending duplicates
- Never rewrite released sections unless the user explicitly asked for history surgery

## Fragment-system rules

- Create or edit the fragment in the same commit as the code change
- Do not hand-edit generated `CHANGELOG.md` output if automation owns it
- One logical user-visible change usually means one fragment
- Internal-only refactors, formatting-only changes, and test-only changes usually do not get fragments unless repo policy says otherwise

## Examples

Wrong:

```text
Commit code now and add the changelog later.
```

Right:

```text
Commit the changelog fragment with the code change it describes.
```

## Split-commit rule

When several logical commits touch the same package:

- default: split manual changelog hunks or fragments per commit
- exception: if repo history clearly prefers one final manual changelog edit, attach the combined changelog hunk to the last relevant commit and say so in the preview
- never dump unrelated entries into one blob just because they hit the same file

## Verification

Before committing, inspect the staged release-note files directly.

```bash
git diff --cached -- CHANGELOG.md NEWS.md HISTORY.md .changeset newsfragments changelog.d 2>/dev/null
```

Check:

- internal-only work did not create user-facing release notes by accident
- generated version bumps or release artifacts did not slip into ordinary feature or fix commits unless repo docs couple them
- staged entries describe the same commit group they ship with
