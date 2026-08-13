# Updating the Clan snapshot

Updater: agent-assisted, reviewable snapshot copier for Clan release branches; NOT deployment; never invents generated option, CLI, or official-service pages.

## Naming and source
Current release displayed as `26.05` → normalized skill ID `nix-clan-2605`. Target `26.11` → sibling skill `nix-clan-2611`. Upstream `26.11` branch does not exist yet; command MUST fail cleanly until Clan publishes it. NEVER substitute `main`, `latest`, or another branch.

## Workflow
1. Plan first. Default dry-run; target neither created nor modified:

```text
uv run --script skills/current/nix-clan-2605/scripts/cli.py update --to-branch 26.11
```

Use `--json` when a machine-readable SHA/count/delta summary is useful. Use `--source-dir` and `--target-dir` only outside normal sibling layout; target name MUST match normalized release ID.

2. Review summary and resulting file list: resolved branch SHA; copied Markdown and embed counts; excluded test fixtures; link rewrites; generated external routes; embed inlining; compatibility-patch warnings; generated TOCs; added/changed/deleted/unchanged SHA-256 entries. Unchanged files remain byte-identical; later Git diff SHOULD show only snapshot delta and intentional updater/router changes.

3. Apply only after review:

```text
uv run --script skills/current/nix-clan-2605/scripts/cli.py update --to-branch 26.11 --apply
```

Updater resolves exact branch SHA, shallow-clones and verifies that SHA, stages a complete sibling copy, validates transforms, and atomically renames staging to `nix-clan-2611`; refuses an existing target. Source `nix-clan-2605` remains intact.

4. Run repository normal skill gates after the user-approved change. Do NOT remove old skill automatically; removing `nix-clan-2605` requires separate explicit user approval.

## Review checklist
- `SKILL.md`: `name: nix-clan-2611`, release `26.11`, exact branch SHA, retrieved date; unrelated body text unchanged.
- `references/INDEX.md`: updated snapshot/provenance/count and generated URLs; topic router intact.
- `references/NOTICE.md`: target `LICENSE.md` text verbatim.
- Every copied `docs/src/**/*.md` except `test.md`; every non-test `docs/embeds/**/*.nix`; no generated pages.
- `{{ version }}` pinned to release; `{{! version }}` remains an authoring escape. Manual `/docs/...` links point to local `.md`/`index.md` files; only generated prefixes remain external under `/docs/26.11/`.
- Embed placeholders inlined; generated TOCs have updater markers; every unknown manual link or compatibility warning reviewed before apply.
- Idempotence check: run `--to-branch 26.05` without `--apply`; it may compare staged candidate with `nix-clan-2605` but MUST NOT write. Applying a same-release update is refused because source and target are identical.
