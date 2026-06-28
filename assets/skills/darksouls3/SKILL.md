---
name: darksouls3
description: "Spoiler-safe Dark Souls 3 companion/reference skill. Use for DS3 gameplay questions: stats, builds, classes, weapons, infusions, upgrades, titanite, souls, Estus, covenants, combat mechanics, routing, farming, controls, item mechanics, achievements, mods, and no-spoiler guidance. Covers base game + DLCs. PC-native: no emulation. Mod-aware: supports Mod Engine 1 (dinput8 proxy / passive) and Mod Engine 3 (ME3 / injection-based for legit Steam)."
license: GPL-3.0-or-later
metadata:
  author: anntnzrb
allowed-tools: "Read, Bash, WebSearch"
---

# Dark Souls 3 Companion

Spoiler-safe Dark Souls 3 companion for gameplay advice, deterministic mechanics, build/math lookups, save-file inspection, achievement/checklist help, and PC mod guidance. Use the bundled CLI first for deterministic mechanics, save parsing, spoiler gates, and source/cache inspection. Use live research or a fresh source cache for user-facing external claims such as exact item locations, route steps, NPC quest details, current PC mod/tool status, contested facts, or any request for citations/currentness.

This file is the operator manual. Assume an agent may read only `SKILL.md`; every public command and boundary needed to use the skill is documented here.

## Entry point

Run the single bundled CLI entry point:

```text
uv run --script <skill-dir>/scripts/cli.py ...
```

Use the skill directory that contains this file. Do not rely on executable bits, shell aliases, `ds3` being on `PATH`, or manual user commands.

Typical Windows path in this environment:

```text
C:/Users/Nil/.config/agents/assets/skills/darksouls3
```

## Core workflow

1. If the question depends on the user's current character/save, run `save auto summary` first unless the user provided a specific `.sl2` path.
2. Use CLI commands for deterministic mechanics, math, save-backed progress, spoiler-safe placeholders, source/cache inspection, and first-pass recommendations.
3. Use live research or a fresh cache from `sources refresh <source-key>` for user-facing external facts: exact item locations, route/checklist gaps, NPC quest details, current mod versions/compatibility, contested claims, and explicit citation/currentness requests.
4. Treat bundled catalogs as operational scaffolds, not authoritative guide prose. If a local catalog answer includes a location or route hint, present it as a bundled/static hint and live-check it before making a source-backed final claim.
5. Filter spoilers before replying. Do not paste future names, future locations, boss identities, quest outcomes, endings, or DLC reveals unless the user has introduced them or explicitly permits spoilers.
6. Answer with the actionable result first, then observed command/source evidence, then caveats.

## Save-file support

The CLI can read local DS3 `.sl2` saves read-only. It auto-detects:

```text
%APPDATA%/DarkSoulsIII/*/DS30000.sl2
```

Use:

```text
uv run --script <skill-dir>/scripts/cli.py save auto <action>
uv run --script <skill-dir>/scripts/cli.py save <path-to-DS30000.sl2> <action>
```

Supported save actions:

```text
summary       compact character overview: name, class, SL, souls, Estus, max weapon, bosses, bonfires, stats
stats         summary plus full stat row
name          character name only
level         soul level and held souls
covenants     nonzero covenant rank/point fields
bosses        save-backed boss defeated/remaining list from known event flags
bonfires      save-backed tracked per-bonfire unlock list from known TGA event bits mapped into DS30000 bytes
progress      compact progress dashboard
inventory     resolved weapons/armor/rings/goods from save inventory; conservative name matching
owned         sorted owned item names from resolved inventory
completion    save-backed achievement categories where possible; static-only categories labeled as such
achievements  completion plus static achievement/checklist categories
checklist     current-area static checklist if area data exists
missed        current-area missing boss/key-item hints when checklist data exists; otherwise says unsupported
gestures      static gesture checklist only; save-backed gesture offsets are unavailable
```

Truthfulness rules for save output:

- Save reading is read-only. Never mutate `.sl2`.
- Bosses are save-backed by known event flag bytes in `resources/event_flags.json`; tracked bonfires are save-backed by `resources/bonfire_flags.json` entries derived from TGA `SprjEventFlagMan` bit offsets and validated against the current DS30000 layout.
- Rings, sorceries, pyromancies, and miracles can be completion-counted from save-backed inventory data when resolved; max weapon reinforcement is observable, but reinforcement achievement completion remains static/unsupported.
- Gestures and infusions are not save-backed right now; they are static checklist entries only.
- `missed` must not claim an area is clear if no area checklist exists. Treat "Area checklist: not available" as unknown, not complete.
- Inventory name resolution is conservative. Unknown or unresolved raw IDs should not be claimed as owned collectibles.

## Full CLI API

All commands use:

```text
uv run --script <skill-dir>/scripts/cli.py <command> [args...]
```

### Starting and stat planning

```text
fresh
softcaps
origins [quality|str|dex|int|fth|pyro|luck]
build [quality|strength|dexterity|sorcerer|pyromancer|cleric|luck] [--level N]
soul-cost <current-level> <target-level>
```

- `fresh` gives a spoiler-safe new-player overview.
- `softcaps` gives stat breakpoints.
- `origins` compares starting classes; filters are build archetypes.
- `build` prints target stats, class, infusion, weapons, and notes.
- `soul-cost` calculates souls needed between levels.

### Weapons, infusions, upgrades, equip load

```text
weapons [<weapon-name>] [--all]
calc "<weapon>" <str> <dex> [int] [fth]
compare "<weapon A>" "<weapon B>" --str N --dex N [--int N] [--fth N]
infusions [<weapon-name>] [--build quality|strength|dexterity|sorcerer|pyromancer|cleric|luck]
upgrade <1-10> [--type normal|twinkling|scale]
equip-load [--vitality N] [--havels] [--favor]
```

- `weapons` without args lists starter-safe weapons; use `--all` for the whole bundled starter catalog.
- `calc` and `compare` are approximate AR tools for bundled known weapons; do not invent AR for missing weapons.
- `infusions` covers all 15 infusion types; use build filters for recommendations.
- `upgrade` supports normal, twinkling, and scale paths.
- `equip-load` uses DS3 roll thresholds: `<30%` fast, `30-70%` medium, `70-100%` fat, `>100%` overburdened.

### Areas, bosses, route, NPCs

```text
areas [--spoilers]
bosses [--area <area>] [--required] [--spoilers]
route [--defeated boss-id,boss-id] [--spoilers]
npcs [<name-or-key>] [--all] [--missable]
```

- Default route/area/boss output should stay spoiler-safe.
- Use `--spoilers` only when the user permits future names.
- `route --defeated ...` accepts comma-separated boss IDs from the CLI's route data.
- `npcs --missable` is for missable questline warnings; avoid unprompted quest outcome spoilers.

### Items, rings, spells, covenants, farming, Estus

```text
rings [<ring-name>] [--build quality|strength|dex|sorcerer|pyro|cleric|luck]
spells [<spell-name>] [--type sorcery|miracle|pyromancy] [--achievement]
covenants [<covenant-id>]
farm [shards|large-shards|chunks|slabs|twinkling|scales|proofs|shackles|medals|grass|dregs|tongues]
estus [shards|bones|allotment|max]
```

- `rings` searches by case-insensitive substring or filters by build.
- `spells --achievement` lists spells needed for platinum/master achievements.
- `covenants` accepts IDs such as `sunlight`, `darkmoon`, `watchdogs`, `mound_makers`, etc.
- `farm` covers titanite, covenant items, and tongues.
- DS3 has 11 Estus Shards, 10 Undead Bone Shards, and max 15 flask uses.

### Achievements, mods, audit, tracking, sources

```text
achievements [--missable] [--plat-route]
mods [--current]
audit
track [summary|stats|gear|next] --path <tracking-json>
recommend --path <tracking-json>
sources list
sources status
sources refresh [source-key ...] [--force]
```

- `achievements` covers the 43 base-game achievements. DLC bosses/items are not required for platinum.
- `mods --current` summarizes current PC mod guidance.
- `audit` runs skill data self-consistency checks.
- `track`/`recommend` read an explicit user-supplied tracking JSON. The skill does not own or persist tracking state.
- `sources refresh` updates cached source pages. Use when source-backed/current data is requested.

### Save commands

```text
save [auto|<path-to-DS30000.sl2>] [summary|stats|name|level|covenants|bosses|bonfires|progress|inventory|gestures|missed|achievements|checklist|owned|completion]
```

Default is:

```text
save auto summary
```

Use save-backed data for current build/progress questions whenever possible. If save data contradicts the user's recollection, state the observed save facts and note that the file may be a different character, NG cycle, transferred save, edited save, or stale save.

## Natural-language routing

Route by intent, not exact wording:

| User asks about | First source | Then | Notes |
|---|---|---|---|
| current stats, SL, class, Estus, boss/bonfire progress | `save auto summary` / `save auto stats` | ask for save path only if auto-detect fails | Save parser is available. |
| exact inventory or owned rings/spells/items | `save auto inventory`, `save auto owned`, `save auto completion` | live/static checklist if unresolved | Be conservative with unresolved IDs. |
| "what did I miss?", current area checklist | `save auto missed`, `save auto checklist` | live research if checklist missing | Unknown area checklist means unknown, not clear. |
| where to level next | `save auto stats`, `softcaps`, `build` | `calc`, `compare`, `infusions` | Use actual current stats. |
| starting class / build archetype | `origins`, `build`, `softcaps` | source refresh/live if user requests citations | Knight quality, Warrior strength, Mercenary dex are common optimized starts. |
| weapon AR/scaling/breakpoints | `calc`, `compare`, `weapons`, `infusions` | MugenMonkey/SoulsPlanner/live for missing weapons | Do not guess AR. |
| upgrade materials | `upgrade`, `farm` | `sources status` / `sources refresh fextralife-upgrades` / live research for exact routes and current source-backed locations | Main weapon first. |
| equip load/fat roll | `equip-load`, `softcaps` | save stats if current VIT matters | Medium roll below 70%. |
| rings/spells/covenants | `rings`, `spells`, `covenants`, `farm` | `save auto completion` when ownership matters; live/source-cache for exact locations, route steps, or covenant quest details | Avoid location spoilers unless permitted. |
| areas/bosses/route | `areas`, `bosses`, `route`, `save auto progress` | live/source-cache for full route or exact checklist details | Default spoiler-safe. |
| achievements/platinum | `achievements`, `save auto achievements`, `save auto completion` | live/source-cache for exact cleanup locations and quest step details | Base-game achievements only. |
| mods/PC fixes | `sources status`, `mods --current` | live research for latest versions/releases/compatibility before final source-backed claims | Ask legit/cracked/online only if needed. |
| source-backed/current data | `sources status`, `sources refresh`, web research | cite URLs | Cite final sources. |

## Spoiler policy

Allowed without special permission:

- Mechanics: stats, softcaps, scaling, upgrade materials, durability, infusions, equip load, poise/hyperarmor, parry/riposte/backstab, weapon arts, FP, Estus, covenants as mechanics, controls, combat fundamentals.
- Names, locations, bosses, NPCs, and items already provided by the user.
- Names already present in observed save output or explicit tracking files.

Forbidden unless introduced or permitted:

- Future boss names, future area names, NPC identities, quest outcomes, item locations, story/lore reveals, endings, and DLC reveals.

When uncertain, say "the next boss", "that optional area", "the current route", "a key item", or "an NPC quest step".

## Mod awareness

PC-native guidance:

- Mod Engine 1: passive `dinput8.dll` proxy, works with cracked and legit copies, mods in `mod/`.
- Mod Engine 3 / ME3: injection-based launcher, legit Steam only, supports boot/logo/arxan improvements, can collide with cracked exes.
- Proper PC Experience: `d3d11.dll` proxy for FPS/refresh/FoV/intro fixes; passive.
- FromStutterFix: `dinput8` chain-loaded frame-pacing fix.
- Blue Sentinel: online protection/overlay/backups, legit Steam only.
- Camera Fix: ME3-native camera auto-center fix.

Use `mods --current` first, then live research for latest release/version or compatibility claims.

## Resources and file layout

Canonical files:

```text
darksouls3/
  SKILL.md
  REFERENCES.md
  scripts/
    cli.py
    ds3_core.py
    ds3_save.py
    cli_catalog.py
    ds3_catalog.py
  resources/
    achievement_checklist.json
    area_checklists.json
    armor.json
    bonfire_flags.json
    bosses.json
    completion_categories.json
    event_flags.json
    game_data.json
    goods_magic.json
    rings.json
    weapons.json
```

Resource roles:

- parser-required: `event_flags.json` and `bonfire_flags.json`; required for read-only `.sl2` boss/bonfire status checks.
- mechanic-invariant: `game_data.json`, `achievement_checklist.json`, and `completion_categories.json`; stable totals/category contracts and parser support metadata.
- thin-catalog: `weapons.json`, `armor.json`, `rings.json`, and `goods_magic.json`; conservative item-name-to-ID maps for inventory resolution only, not gameplay-stat/guide tables.
- area-checklist scaffold: `area_checklists.json`; small spoiler-filtered local checklist hints where curated, incomplete by design.
- eval-fixture: `evals/evals.json`; prompt expectations that enforce routing, spoiler safety, source policy, and command use.

Source and license ranking lives in `REFERENCES.md`. Use it before replacing embedded resource data.

## Source registry and cache

The CLI has 20 registered sources. Address them by key with `sources refresh <key>`:

```text
fextralife-stats      https://darksouls3.wiki.fextralife.com/Stats
fextralife-classes    https://darksouls3.wiki.fextralife.com/Classes
fextralife-weapons    https://darksouls3.wiki.fextralife.com/Weapons
fextralife-infusions  https://darksouls3.wiki.fextralife.com/Infusion
fextralife-upgrades   https://darksouls3.wiki.fextralife.com/Upgrades
fextralife-covenants  https://darksouls3.wiki.fextralife.com/Covenants
fextralife-areas      https://darksouls3.wiki.fextralife.com/Areas
fextralife-progress   https://darksouls3.wiki.fextralife.com/Game+Progress+Route
wikidot-stats         https://darksouls3.wikidot.com/stats
mugenmonkey           https://mugenmonkey.com/darksouls3
soulsplanner          https://soulsplanner.com/darksouls3
cheat-sheet           https://zkjellberg.github.io/dark-souls-3-cheat-sheet
pcgamingwiki          https://www.pcgamingwiki.com/wiki/Dark_Souls_III
soulsmods             https://github.com/soulsmods
alfizari-save-editor https://github.com/alfizari/Dark-Souls-3-Save-Editor-PS4-PC
tga-ct               https://github.com/The-Grand-Archives/Dark-Souls-III-CT-TGA
paramdex-bonfire     https://raw.githubusercontent.com/soulsmods/Paramdex/master/DS3/Defs/BONFIRE_WARP_PARAM_ST.xml
soulsmodding-flags   https://soulsmodding.com/doku.php?id=ds3-refmat:event-flag-list
modengine1            https://github.com/katalash/ModEngine
me3                   https://github.com/garyttierney/me3
```

Use:

```text
sources list
sources status
sources refresh [source-key ...] [--force]
```

Cache location:

```text
~/.cache/darksouls3-companion
```

Override with:

```text
DS3_CACHE_DIR=<path>
```

Cache entries are JSON with fetch timestamp `ts`, raw `content`, and `meta` containing `url` and `sha256`. Staleness is evaluated against a 24-hour TTL. License strings are in the in-memory source registry/list output and the source-use hierarchy is documented in `REFERENCES.md`; cache files are transport artifacts, not provenance records. Runtime remains stateless with respect to playthrough progress.

Cache policy: cache files are transport artifacts. They may support fresh source-backed answers when within TTL, but they are not canonical truth and they do not replace source URLs, source keys, license/provenance records, or final-answer citations.

## Live research fallback

Use web/Brave/Reddit/read URLs when CLI coverage is missing, source cache is stale, the user asks for source-backed/current data, or the claim is an exact location, route step, NPC quest detail, mod/tool compatibility fact, or contested gameplay detail. Keep queries spoiler-safe unless spoilers are permitted.

Example queries:

```text
Dark Souls 3 Vigor HP per level softcap
Dark Souls 3 proof of concord kept farming offline
Dark Souls 3 weapon AR calculator heavy infusion
Dark Souls 3 equip load thresholds fast roll
Dark Souls 3 estus shard locations no spoilers
Dark Souls 3 Mod Engine 3 latest release
```

For final answers using live research, cite URLs and separate observed source facts from inference.
