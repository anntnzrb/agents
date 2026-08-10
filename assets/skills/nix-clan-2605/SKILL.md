---
name: nix-clan-2605
description: Use for Clan 26.05 inventory, services, vars, deployment, migrations, and NixOS workflow documentation.
license: MIT
metadata:
  upstream: https://git.clan.lol/clan/clan-core
  branch: 26.05
  commit: 1ec96dde9a8e3244b32abe41e3b3bfdd86520929
  retrieved: 2026-08-10
---

# Clan 26.05 Documentation

Use this skill for Clan-specific 26.05 workflows, concepts, services, inventory,
vars, deployment, migrations, and release behavior. Use the `nix` skill for
generic Nix, NixOS, nixpkgs, flakes, or module-system mechanics.

## Snapshot boundary

The bundled snapshot is Clan `clan-core` branch `26.05`, commit
`1ec96dde9a8e3244b32abe41e3b3bfdd86520929`, retrieved 2026-08-10. Do not silently
substitute `main`, `latest`, or another release. State when guidance comes from
the pinned snapshot versus a separately retrieved current source.

## Use workflow

1. Read `references/INDEX.md` to select only the relevant topic entry.
2. Read the linked source page(s) under `references/docs/`; preserve their version
   and hierarchy when applying procedures or quoting examples.
3. For disk-encryption examples, read `references/docs/guides/disk-encryption.md`
   and the matching files under `references/embeds/`.
4. Treat links to options, `clan.core`, CLI, and official services as generated
   documentation. Follow the pinned `https://clan.lol/docs/26.05/` URL; never
   invent a local generated page.
5. When asked to refresh this snapshot, read `references/update-workflow.md` and
   invoke `scripts/cli.py`; plan first, then apply only after reviewing its
   summary. Never remove the old release without explicit user approval.
6. If the request is generic Nix rather than Clan-specific behavior, hand it to
   the `nix` skill instead of loading this snapshot broadly.

## Required follow-up reads

| Need | Read | When |
| --- | --- | --- |
| Topic routing and snapshot rules | `references/INDEX.md` | First read for every Clan request |
| Installation or first deployment | `references/docs/getting-started/` | When creating or installing a Clan |
| Inventory, services, vars, backups, or networking | Matching `references/docs/guides/<topic>/` | Before prescribing that workflow |
| Migration or 26.05 release behavior | `references/docs/guides/migrations/` and `references/docs/releases/26-05.md` | When upgrading or migrating |
| Disk encryption and initrd SSH | `references/docs/guides/disk-encryption.md` and `references/embeds/` | When configuring encrypted disks |
| CLI, options, `clan.core`, or official service details | Pinned rendered URL in `references/INDEX.md` | When a generated reference is needed |
| Snapshot updater | `references/update-workflow.md` | When refreshing to another release |
| Copyright and redistribution terms | `references/NOTICE.md` | Before copying or redistributing text |
