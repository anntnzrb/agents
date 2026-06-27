---
name: darksouls3
description: "Spoiler-safe Dark Souls 3 companion/reference skill. Use for DS3 gameplay questions: stats, builds, classes, weapons, infusions, upgrades, titanite, souls, Estus, covenants, combat mechanics, routing, farming, controls, item mechanics, achievements, mods, and no-spoiler guidance. Covers base game + DLCs. PC-native: no emulation. Mod-aware: supports Mod Engine 1 (dinput8 proxy / passive) and Mod Engine 3 (ME3 / injection-based for legit Steam)."
license: GPL-3.0-or-later
metadata:
  author: anntnzrb
allowed-tools: "Read, Bash, WebSearch"
---

# Dark Souls 3 Companion

Spoiler-safe Dark Souls 3 companion for gameplay advice, deterministic mechanics, build/math lookups, save-file inspection, achievement/checklist help, and PC mod guidance. Use the bundled CLI first. Use live web research only when the CLI/static resources cannot answer or the user explicitly asks for current/source-backed corroboration.

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
2. Use CLI commands for deterministic mechanics, math, static catalogs, save-backed progress, and first-pass recommendations.
3. Use live research only for stale/missing data, exact route/checklist gaps, current mod versions, or explicit citation requests.
4. Filter spoilers before replying. Do not paste future names, future locations, boss identities, quest outcomes, endings, or DLC reveals unless the user has introduced them or explicitly permits spoilers.
5. Answer with the actionable result first, then evidence/command used, then caveats.

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
bonfires      save-backed unlocked/locked bonfire list from known event flags
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
- Bosses/bonfires are save-backed only for event flags in `resources/event_flags.json`.
- Rings, sorceries, pyromancies, miracles, and weapon reinforcement can be completion-counted from save-backed data when resolved.
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
| upgrade materials | `upgrade`, `farm` | source registry/live for exact route | Main weapon first. |
| equip load/fat roll | `equip-load`, `softcaps` | save stats if current VIT matters | Medium roll below 70%. |
| rings/spells/covenants | `rings`, `spells`, `covenants`, `farm` | save completion if ownership matters | Avoid location spoilers unless permitted. |
| areas/bosses/route | `areas`, `bosses`, `route`, save progress | live research for full route | Default spoiler-safe. |
| achievements/platinum | `achievements`, `save auto achievements`, `save auto completion` | live checklist for exact cleanup | Base-game achievements only. |
| mods/PC fixes | `mods --current` | live research for latest versions | Ask legit/cracked/online only if needed. |
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
    bonfires.json
    bosses.json
    completion_categories.json
    event_flags.json
    game_data.json
    goods_magic.json
    rings.json
    weapons.json
```

Resource roles:

- `event_flags.json`: known save event flag offsets for bosses and bonfires.
- `achievement_checklist.json`: rings, spells, gestures, infusions, reinforcement checklist.
- `completion_categories.json`: maps checklist categories to save-backed/static support.
- `area_checklists.json`: area-specific bosses/key items/NPCs/shards where known.
- `game_data.json`: broad area graph, Estus/Bone totals, base static route data.
- `weapons.json`, `armor.json`, `rings.json`, `goods_magic.json`: item-name maps for inventory and ownership resolution.
- `bosses.json`, `bonfires.json`: metadata catalogs.

Do not reintroduce legacy names like `Bosses.json`, `bonfire.json`, `ring.json`, or `goods_magic_bulk.json`.

## Source registry and cache

The CLI has 16 registered sources. Address them by key with `sources refresh <key>`:

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

Cache entries are JSON with fetch timestamp `ts`, raw `content`, and `meta` containing `url` and `sha256`. Staleness is evaluated against a 24-hour TTL. License strings are in the in-memory source registry/list output, not guaranteed in cache files. Runtime remains stateless with respect to playthrough progress.

## Live research fallback

Use web/Brave/Reddit when CLI coverage is missing, source cache is stale, or the user asks for source-backed corroboration. Keep queries spoiler-safe unless spoilers are permitted.

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
