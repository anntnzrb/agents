# Clan 26.05 Reference Index

## Snapshot

- Source: `https://git.clan.lol/clan/clan-core/src/branch/26.05/docs/src`
- Repository: `https://git.clan.lol/clan/clan-core`
- Branch: `26.05`
- Commit: `1ec96dde9a8e3244b32abe41e3b3bfdd86520929`
- Retrieved: `2026-08-10`
- Vendored: 66 Markdown files from upstream `docs/src`; excludes
  `test.md`, non-Markdown sources such as `index.svelte`, and generated-prefix
  Markdown pages when present.

## Topic router

| Need | Read first |
| --- | --- |
| Install or start a Clan | `docs/getting-started/install-nix.md`, then `docs/getting-started/quick-start.md` |
| Provider-specific installation | `docs/getting-started/getting-started-physical.md`, `docs/getting-started/getting-started-virtualbox.md`, `docs/getting-started/getting-started-aws.md`, `docs/getting-started/getting-started-google.md`, or `docs/getting-started/getting-started-hetzner.md` |
| Inventory and auto-included machine files | `docs/guides/inventory/intro-to-inventory.md` |
| Clan services and service authoring | `docs/guides/services/intro-to-services-revised.md`, `docs/guides/services/community.md`, `docs/guides/services/exports.md` |
| Vars, secrets, generators, and backends | `docs/guides/vars/intro-to-vars.md`, `docs/guides/vars/vars-concepts.md`, `docs/guides/vars/sops/secrets.md`, `docs/guides/vars/age/age-backend.md` |
| Backups and state | `docs/guides/backups/intro-to-backups.md` |
| Networking and mesh VPN | `docs/guides/networking/networking.md`, `docs/guides/networking/mesh-vpn.md` |
| Flakes, build hosts, macOS, rebuilds, or specialisations | `docs/guides/flake-parts.md`, `docs/guides/build-host.md`, `docs/guides/macos.md`, `docs/guides/nixos-rebuild.md`, `docs/guides/specialisations.md` |
| Disk encryption or secure boot | `docs/guides/disk-encryption.md`, `docs/guides/secure-boot.md` (embeds are in `embeds/`) |
| Migration from existing systems or 25.11 | `docs/guides/migrations/` and `docs/releases/26-05.md` |
| Templates and disko templates | `docs/concepts/templates.md`, `docs/guides/disko-templates/community.md` |
| Contributor or documentation authoring | `docs/guides/contributing/` |
| Architecture rationale | `docs/decisions/` |
| Glossary and manually authored reference overview | `docs/reference/glossary.md`, `docs/reference/index.md`, `docs/reference/clanLib/index.md` |
| Community services pointer | `docs/services/community.md`; definition: `docs/services/definition.md` |
| Historical release notes | `docs/releases/25-11.md` |

The authored source hierarchy under `docs/` is authoritative for this snapshot;
read narrowly rather than loading the whole tree. Exclusions are listed above.

## Embeds

`embeds/disko-single-disk.nix`, `embeds/disko-raid.nix`, and `embeds/initrd.nix`
are exact copies of the corresponding upstream embed files and are inlined in
the disk-encryption page as ordinary fenced Nix blocks.

## Generated documentation

The source tree does not contain generated option, `clan.core`, CLI, or official
service pages. Do not create substitutes. Follow these pinned rendered routes:
`https://clan.lol/docs/26.05/reference/options/...`,
`https://clan.lol/docs/26.05/reference/clan.core/...`,
`https://clan.lol/docs/26.05/reference/cli/...`, and
`https://clan.lol/docs/26.05/services/official/...`.

## Rewrite and provenance policy

- Links to copied pages use local relative `.md` paths and preserve anchors.
- Generated-page links remain external and use the `/docs/26.05/` prefix.
- Runnable installer commands and version-selection links were pinned to the
  literal `26.05`; the escaped `{{! version }}` authoring-template example in
  `docs/guides/contributing/writing-documentation.md` is preserved as
  documentation-authoring guidance, not a runnable command. No moving release
  or repository snapshot is implied.
- Source license and attribution are in `NOTICE.md`.
- Excluded upstream `docs/src/test.md` (renderer fixture), non-Markdown source
  files such as `docs/src/index.svelte`, and Markdown pages under generated
  prefixes (`reference/options/`, `reference/clan.core/`, `reference/cli/`, and
  `services/official/`) when present; other authored Markdown is preserved.
