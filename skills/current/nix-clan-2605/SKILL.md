---
disable-model-invocation: true
name: nix-clan-2605
description: "Use when Clan 26.05 inventory, services, vars, deployment, migrations, or NixOS workflow docs are involved."
license: AGPL-3.0-or-later
metadata:
  upstream: https://git.clan.lol/clan/clan-core
  branch: 26.05
  commit: 1ec96dde9a8e3244b32abe41e3b3bfdd86520929
  retrieved: 2026-08-10
---

# Clan 26.05 Documentation

Clan-specific 26.05 workflows, concepts, services, inventory, vars, deployment, migrations, and release behavior → this skill. Generic Nix, NixOS, nixpkgs, flakes, or module-system mechanics → `nix` skill.

## Snapshot boundary

Bundled snapshot: Clan `clan-core`, branch `26.05`, commit `1ec96dde9a8e3244b32abe41e3b3bfdd86520929`, retrieved 2026-08-10. NEVER silently substitute `main`, `latest`, or another release. State whether guidance comes from this pinned snapshot or separately retrieved current source.

## Use workflow

1. MUST read `references/INDEX.md`; select only its relevant topic entry.
2. MUST read linked page(s) under `references/docs/`; preserve source version and hierarchy when applying procedures or quoting examples.
3. Disk-encryption examples: MUST read `references/docs/guides/disk-encryption.md` and matching files under `references/embeds/`.
4. Options, `clan.core`, CLI, and official-service links → generated documentation. Follow `https://clan.lol/docs/26.05/`; NEVER invent a local generated page.
5. Snapshot refresh: MUST read `references/update-workflow.md`; invoke `scripts/cli.py`; plan first, then apply only after reviewing its summary. NEVER remove the old release without explicit user approval.
6. Generic Nix request rather than Clan-specific behavior → hand off to `nix` skill; do not broadly load this snapshot.

## Required follow-up reads

- Every Clan request: `references/INDEX.md`; topic routing and snapshot rules; first read.
- Creating or installing a Clan: `references/docs/getting-started/`; installation or first deployment.
- Prescribing inventory, services, vars, backups, or networking: matching `references/docs/guides/<topic>/`.
- Upgrading or migrating: `references/docs/guides/migrations/` and `references/docs/releases/26-05.md`; migration or 26.05 release behavior.
- Configuring encrypted disks: `references/docs/guides/disk-encryption.md` and `references/embeds/`; disk encryption and initrd SSH.
- Generated CLI, options, `clan.core`, or official-service reference: pinned rendered URL in `references/INDEX.md`.
- Refreshing to another release: `references/update-workflow.md`; snapshot updater.
- Copying or redistributing text: `references/NOTICE.md`; copyright and redistribution terms.
