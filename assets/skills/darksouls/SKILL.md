---
name: darksouls
description: "Spoiler-safe Dark Souls Remastered companion and reference. Use for DSR mechanics, stats, builds, starting classes, weapons, upgrade paths, equip load, rings, spells, farming, achievements/platinum, route planning, source-backed/current PC or mod questions, the bundled local PSNProfiles platinum-guide search, and read-only save inspection when a supported save is supplied. Do not use for save editing or unverified parser claims."
license: GPL-3.0-or-later
metadata:
  author: anntnzrb
allowed-tools: "Read, Bash, WebSearch"
---

# Dark Souls Remastered Companion

Give conservative, spoiler-safe DSR help. The skill is stateless: it does not own a playthrough, silently write tracking files, or mutate saves. Use deterministic local commands for mechanics and catalog calculations; use source-cache/live research for current, route, location, NPC, mod, or contested claims.

## Entry point and operating loop

Run the one public entry point:

```text
uv run --script <skill-dir>/scripts/cli.py ...
```

Use the directory containing this file (normally `C:/Users/Nil/.config/agents/assets/skills/darksouls`). Do not require a PATH alias, executable bit, shell profile, or ask the user to install a second CLI.

1. Classify the request: deterministic mechanic/catalog, current/save state, route/guide, achievement, source-backed/current, or mod support.
2. Run the narrowest applicable CLI command first. `ds1_core.py` owns mechanics, spoiler gates, source/cache, and guide-search interfaces; `ds1_catalog.py` owns item lookup and deterministic AR/compare helpers; `ds1_save.py` is read-only and must report unsupported categories explicitly; `cli.py` composes these APIs.
3. Use `sources status` before source-backed/current claims. Refresh only the needed key when the cache is absent or stale, then use live research when the claim is not covered.
4. Treat bundled catalogs and transformed guide chunks as operational lookup aids, not copied encyclopedia prose or proof of save state.
5. Apply the spoiler policy before showing names. Answer with the actionable result, then command/source evidence and uncertainty.

## CLI contract

All commands have this form:

```text
uv run --script <skill-dir>/scripts/cli.py <command> [args...]
```
### Mechanics, origins, builds, and math

```text
fresh
softcaps
origins [filter]
build [quality|strength|dexterity|sorcerer|sorcery|pyromancer|cleric|miracle|dragon] [--level N]
soul-cost <current-level> <target-level>
equip-load [--endurance N] [--havels | --favor]
```

Use these for stat breakpoints, starting-class tradeoffs, target-stat sketches, level-cost math, and roll/equip-load calculations. A build is a conditional example, not a prescription for an unspecified player. Do not invent a formula, breakpoint, class, or result absent from deterministic output; label approximations.
Equip-load roll boundaries are inclusive in the CLI: fast roll at or below 25%, mid roll at or below 50%, and fat roll at or below 100% of maximum load. `--havels` and `--favor` cannot be combined.

### Weapons, upgrades, and catalog lookup

```text
weapons [<name>] [--limit N] [--json] [--spoilers]
calc "<weapon>" <str> <dex> [--int N] [--fth N] [--json]
compare "<weapon A>" "<weapon B>" [--str N --dex N --int N --fth N] [--json]
upgrade <level> [--type normal|unique|dragon]
rings [<name>] [--limit N] [--json] [--spoilers]
goods [<name>] [--limit N] [--json] [--spoilers]
```
Catalog results are deterministic only for rows present in the bundled resources. Without `--spoilers`, catalog output must not reveal future item names or locations beyond a name the user supplied; use generic redaction where required. `--json` preserves the command's machine-readable schema while applying the same spoiler gate. `calc`/`compare` produce approximate AR for known rows; they must say when a weapon or path is unknown and never extrapolate AR from a similarly named item. Exact acquisition locations are separate source-backed claims and may be spoiler-filtered.

### Progression, areas, bosses, farming, and achievements

```text
areas [--spoilers]
bosses [--area <area>] [--spoilers]
route [--defeated <id,id,...>] [--spoilers]
farm [souls|titanite|humanity|moss] [--spoilers]
estus [max|shards|souls|kindling]
achievements [--missable] [--spoilers]
```

The default is a safe overview. Pass `--spoilers` only after the user permits future names or names are already in context. `--havels` and `--favor` are mutually exclusive equip-load choices; do not combine them. Exact routes, item locations, NPC steps, farming spots, and missable cleanup require the source-cache/live path; do not convert an incomplete checklist into a claim that an area is clear.

### Local platinum-guide corpus

```text
guide info [--spoilers]
guide kinds [--spoilers]
guide headings [--spoilers]
guide search <query...> [--kind <kind>] [--heading <text>] [--limit N] [--json] [--spoilers]
guide get <row-number> [--json] [--spoilers]
```

These commands search only the transformed, user-provided PSNProfiles DSR platinum-guide corpus at:

```text
resources/guides/dsr_plat_guide/dsr-plat-guide.manifest.json
resources/guides/dsr_plat_guide/dsr-plat-guide.chunks.jsonl
```

Raw chunk rows use `{ "h": string[], "k": string, "t": string }`; search results add a row number/snippet for lookup. Guide output is redacted by default and `--json` changes representation only, not the spoiler gate. Every guide answer must carry this warning:

> Local guide lookup: transformed from the user-provided PSNProfiles platinum-guide PDF; spoiler-heavy, non-authoritative, not save/parser truth, and not permission to republish the PDF or its text.

The manifest reports `title`, `authors`, `url`, source-PDF identity/hash, transformation metadata, and provenance/usage constraints; do not substitute undocumented keys such as `author`, `updated`, or `source`. The source PDF is not tracked or bundled, and raw PDF text must never be copied into the repository. Summarize only the minimum text needed. The corpus is produced by `uv run --script scripts/preprocess_dsr_plat_guide.py [pdf] [outdir]`; keep only the manifest/chunks outputs.

### Sources, mods, and audit

```text
sources list
sources status
sources policy
sources explain <source-key>
sources refresh [<source-key> ...] [--force]
audit
track [section] --path <tracking-json>
recommend --path <tracking-json>
```

`sources refresh` is for registered remote HTTP(S) sources; local registry entries are introspection-only and must not be fetched. Use the source registry/cache and live research for current loader/tool information; this is discovery and risk guidance, not a compatibility guarantee.

### Read-only saves

```text
save [PATH=auto] [ACTION=summary|stats|name|level|currency|inventory|owned|bosses|bonfires|progress|completion|achievements|checklist|missed] [--spoilers] [--json]
```

`summary`, `stats`, `name`, and `level` may report validated DSR container/slot identity, character name, level, class, and stats when AES/MD5/name-copy/range checks pass. The `achievements` action returns the static checklist plus an explicitly unsupported save-backed unlock state; it does not read platform ownership. `currency`, `inventory`, `owned`, `bosses`, `bonfires`, `progress`, `completion`, `checklist`, and `missed` remain explicit unsupported results until their DSR mappings are validated. Unsupported JSON requests must remain JSON objects; never turn them into prose.

Default save output must redact character/progression names, locations, bosses, bonfires, and requirements unless the user has permitted spoilers; `--json` preserves the schema while applying the same gate. `save auto` checks only the documented Windows DSR location and selects the newest candidate that passes full validation and contains a nonempty valid character slot; malformed, empty, or unreadable newer files are skipped. Use an explicit `.sl2` path for backups or non-default installs.

Save support is read-only: never write, repair, decrypt, convert, or recommend an editor. Unknown IDs, unvalidated offsets, and unsupported categories remain unknown—not zero, absent, or complete. Do not advertise exact quest state, every key item, gestures, covenant rank, bonfire flags, inventory ownership, or achievement completion as save-backed. A static checklist is not save state; a save may be stale, transferred, edited, a different character, or a different game build.
## Natural-language routing

| Intent | First action | Follow-up and boundary |
|---|---|---|
| Stats, level, current class, or verified save identity | `save auto summary` / `save auto stats` | Use explicit save path if auto-detect fails; only verified fields are facts. |
| Starting class or build direction | `origins`, `softcaps`, `build` | Ask for goals/current stats; compare tradeoffs rather than prescribing. |
| AR, scaling, weapon choice | `weapons`, `calc`, `compare` | Use only known catalog rows; state approximation and upgrade path. |
| Upgrade route/materials | `upgrade`, `farm` | Source-cache/live-check exact locations; keep future names hidden by default. |
| Rings, goods, and farming | `rings`, `goods`, `farm` | Save ownership only when parser resolves it; location prose needs source evidence. |
| “Where next?”, areas, bosses, NPCs | `save auto summary` only for verified fields, then `areas`/`route`/`bosses` | Use generic placeholders until spoilers are permitted; unsupported save progress means unknown. |
| Platinum/achievement cleanup | `achievements`; `guide search` for the local corpus | Separate static checklist from save-backed completion; cite guide/source and warn about spoilers. |
| Exact guide phrase or checklist row | `guide search` then `guide get` | Transform/summarize; never paste raw PDF or imply authority. |
| Latest/current PC, mod, or compatibility question | `sources status` | Refresh/live research and cite the dated source; no unsupported compatibility guarantee. |
| Source-backed or contested mechanic | deterministic CLI first, then `sources explain/status` | Refresh/live-check and distinguish observed fact, source claim, and recommendation. |

## Spoiler policy

Default output MUST omit future proper names. It may include mechanics and names that the user supplied, that appear in an explicitly supplied save/tracking context, or that the user explicitly permits. Without permission, do not reveal future boss/area/NPC/item names, exact locations, quest outcomes, endings, lore/story reveals, or DLC/late-game identities. Use “the next required boss”, “the optional area”, “a key upgrade material”, or “that NPC” instead. `--spoilers` is an explicit opt-in for CLI output; it does not override a user’s stated no-spoiler request.

Mechanics that are normally safe include stats, softcaps, scaling, reinforcement rules, durability, equip load, poise, parry/riposte/backstab, kindling/Estus mechanics, controls, and general combat fundamentals. Even safe mechanics must not smuggle in a future location or quest outcome.

## Evidence and source hierarchy

1. **Observed deterministic output** from the current CLI/kernel for supported mechanics or catalog rows.
2. **Validated read-only parser output** for fields whose DSR offsets/IDs are explicitly sourced and tested by the save implementation.
3. **Official/primary sources** for product/platform facts and published requirements.
4. **Fresh cached/live community sources** for routes, locations, NPC steps, farming, calculators, and current mod status.
5. **Local transformed guide chunks** only for targeted walkthrough lookup, with provenance and spoiler warning.

Label claims as observed, source-backed, calculated, or recommendation. If sources disagree, show the disagreement and avoid false precision. Cache metadata is a fetch receipt, not a citation; cite the source URL/source key.

## Mod guidance boundaries

DSR mod advice is PC-native and version-sensitive. Describe loader/tool names only when supported by the registry, distinguish legitimate Steam from other distributions, recommend backups and offline testing, and separate cosmetic/QoL risk from gameplay/save changes. Do not promise online safety, anti-cheat safety, multiplayer compatibility, or support for cracked copies. Do not give instructions that circumvent DRM, platform protections, anti-cheat, or license checks. Current claims require live verification.

## Resource contract

```text
darksouls/
  SKILL.md
  REFERENCES.md
  scripts/
    cli.py
    ds1_core.py
    ds1_catalog.py
    ds1_save.py
  resources/
    game_data.json
    source_registry.json
    weapons.json
    rings.json
    goods_magic.json
    achievement_checklist.json
    save_support.json
    guides/dsr_plat_guide/
      dsr-plat-guide.manifest.json
      dsr-plat-guide.chunks.jsonl
  evals/evals.json
```

`game_data.json` and the checklist are stable, curated contracts; catalogs are intentionally thin and conservative. Read `REFERENCES.md` when a source, cache, guide-corpus, or mod boundary matters. Do not add raw PDF text, copied wiki prose, broad location tables, or unlicensed datasets.
