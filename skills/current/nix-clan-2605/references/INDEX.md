# Clan 26.05 Reference Index

## Snapshot

- Source: `https://git.clan.lol/clan/clan-core/src/branch/26.05/docs/src`
- Repository: `https://git.clan.lol/clan/clan-core`
- Branch: `26.05`
- Commit: `1ec96dde9a8e3244b32abe41e3b3bfdd86520929`
- Retrieved: `2026-08-10`
- Vendored: 66 upstream `docs/src` Markdown files.

## Topic router

`Need → read first:`

- Install/start Clan → `docs/getting-started/install-nix.md`; `docs/getting-started/quick-start.md`
- Provider-specific installation → `docs/getting-started/getting-started-physical.md` | `docs/getting-started/getting-started-virtualbox.md` | `docs/getting-started/getting-started-aws.md` | `docs/getting-started/getting-started-google.md` | `docs/getting-started/getting-started-hetzner.md`
- Inventory and auto-included machine files → `docs/guides/inventory/intro-to-inventory.md`
- Clan services/service authoring → `docs/guides/services/intro-to-services-revised.md` | `docs/guides/services/community.md` | `docs/guides/services/exports.md`
- Vars, secrets, generators, backends → `docs/guides/vars/intro-to-vars.md` | `docs/guides/vars/vars-concepts.md` | `docs/guides/vars/sops/secrets.md` | `docs/guides/vars/age/age-backend.md`
- Backups/state → `docs/guides/backups/intro-to-backups.md`
- Networking/mesh VPN → `docs/guides/networking/networking.md` | `docs/guides/networking/mesh-vpn.md`
- Flakes, build hosts, macOS, rebuilds, specialisations → `docs/guides/flake-parts.md` | `docs/guides/build-host.md` | `docs/guides/macos.md` | `docs/guides/nixos-rebuild.md` | `docs/guides/specialisations.md`
- Disk encryption/secure boot → `docs/guides/disk-encryption.md` | `docs/guides/secure-boot.md` (embeds in `embeds/`)
- Migration from existing systems or 25.11 → `docs/guides/migrations/` | `docs/releases/26-05.md`
- Templates/disko templates → `docs/concepts/templates.md` | `docs/guides/disko-templates/community.md`
- Contributor/documentation authoring → `docs/guides/contributing/`
- Architecture rationale → `docs/decisions/`
- Glossary/manually authored reference overview → `docs/reference/glossary.md` | `docs/reference/index.md` | `docs/reference/clanLib/index.md`
- Community services → `docs/services/community.md`; definition → `docs/services/definition.md`
- Historical release notes → `docs/releases/25-11.md`

Authored `docs/` hierarchy authoritative for this snapshot; read narrowly, not the whole tree. Exclusions below.

## Embeds

`embeds/disko-single-disk.nix`, `embeds/disko-raid.nix`, and `embeds/initrd.nix` are exact copies of corresponding upstream embed files, inlined in the disk-encryption page as ordinary fenced Nix blocks.

## Generated documentation

Source tree lacks generated option, `clan.core`, CLI, and official service pages. Do not create substitutes. Follow pinned rendered routes:

- `https://clan.lol/docs/26.05/reference/options/...`
- `https://clan.lol/docs/26.05/reference/clan.core/...`
- `https://clan.lol/docs/26.05/reference/cli/...`
- `https://clan.lol/docs/26.05/services/official/...`

## Rewrite and provenance policy

- Copied-page links: local relative `.md` paths; anchors preserved.
- Generated-page links: external; `/docs/26.05/` prefix.
- Runnable installer commands and version-selection links: literal `26.05` pinned. The escaped `{{! version }}` authoring-template example in `docs/guides/contributing/writing-documentation.md` remains documentation-authoring guidance, not a runnable command. No moving release or repository snapshot implied.
- Source license/attribution: `NOTICE.md`.
- Exclusions: upstream `docs/src/test.md` (renderer fixture); non-Markdown sources such as `docs/src/index.svelte`; Markdown under generated prefixes `reference/options/`, `reference/clan.core/`, `reference/cli/`, and `services/official/` when present. Other authored Markdown preserved.
