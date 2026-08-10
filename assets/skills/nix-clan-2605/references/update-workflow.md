# Updating the Clan snapshot

Use the updater when a Clan release branch needs a new, reviewable skill snapshot.
It is an agent-assisted copier, not a deployment tool: it never invents generated
option, CLI, or official-service pages.

## Naming and source

The current release is displayed as `26.05` and its normalized skill ID is
`nix-clan-2605`. A `26.11` branch produces the sibling skill `nix-clan-2611`.
The upstream `26.11` branch does not exist yet; the command must fail cleanly
until Clan publishes it. Do not substitute `main`, `latest`, or another branch.

## Workflow

1. Plan first. The default is dry-run and does not create or modify the target:

   ```text
   uv run --script assets/skills/nix-clan-2605/scripts/cli.py update --to-branch 26.11
   ```

   Use `--json` when a machine-readable SHA/count/delta summary is useful. Use
   `--source-dir` and `--target-dir` only when working outside the normal sibling
   layout; the target name must match the normalized release ID.

2. Review the summary and the resulting file list. Confirm the resolved branch
   SHA, copied Markdown and embed counts, excluded test fixtures, link rewrites,
   generated external routes, embed inlining, compatibility-patch warnings,
   generated TOCs, and added/changed/deleted/unchanged SHA-256 entries. Unchanged
   files remain byte-identical; a later Git diff should show only the snapshot
   delta and intentional updater/router changes.

3. Apply only after review:

   ```text
   uv run --script assets/skills/nix-clan-2605/scripts/cli.py update --to-branch 26.11 --apply
   ```

   The updater resolves the exact branch SHA, shallow-clones and verifies that
   SHA, stages a complete sibling copy, validates transforms, and atomically
   renames the staged directory into `nix-clan-2611`. It refuses an existing
   target. The source `nix-clan-2605` remains intact.

4. Run the repository's normal skill gates after the user-approved change. Do
   not remove the old skill automatically. Removing `nix-clan-2605` is a separate
   review decision requiring explicit user approval.

## Review checklist

- `SKILL.md` has `name: nix-clan-2611`, release `26.11`, exact branch SHA, and
  retrieved date; unrelated body text is unchanged.
- `references/INDEX.md` has updated snapshot/provenance/count and generated URLs,
  while its topic router remains intact.
- `references/NOTICE.md` carries the target `LICENSE.md` text verbatim.
- Every copied `docs/src/**/*.md` is present except `test.md`; every non-test
  `docs/embeds/**/*.nix` is present; no generated pages were added.
- `{{ version }}` is pinned to the release while `{{! version }}` remains an
  authoring escape. Manual `/docs/...` links point to local `.md`/`index.md` files;
  only generated prefixes remain external under `/docs/26.11/`.
- Embed placeholders are inlined, generated TOCs have updater markers, and any
  unknown manual link or compatibility warning is reviewed before apply.
- For an idempotence check, run `--to-branch 26.05` without `--apply`; it may
  compare the staged candidate with `nix-clan-2605` but must not write. Applying a
  same-release update is refused because source and target are identical.
