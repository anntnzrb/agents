# Dark Souls 3 CLI and save contract

Read this when exact commands, save actions, guide lookup, or intent routing matter.

## Public entry point

```text
uv run --script <skill-dir>/scripts/cli.py <command> [args...]
```

Do not rely on executable bits, shell aliases, `ds3` on `PATH`, or manual user commands.

## Starting and stat planning

```text
fresh
softcaps
origins [quality|str|dex|int|fth|pyro|luck]
build [quality|strength|dexterity|sorcerer|pyromancer|cleric|luck] [--level N]
soul-cost <current-level> <target-level>
```

- `fresh` is spoiler-safe.
- `origins` compares classes; it does not choose one for an unspecified user.
- `build` prints target stats, class, infusion, weapons, and notes.

## Weapons, upgrades, and equip load

```text
weapons [<weapon-name>] [--all]
calc "<weapon>" <str> <dex> [int] [fth]
compare "<weapon A>" "<weapon B>" --str N --dex N [--int N] [--fth N]
infusions [<weapon-name>] [--build quality|strength|dexterity|sorcerer|pyromancer|cleric|luck]
upgrade <1-10> [--type normal|twinkling|scale]
equip-load [--vitality N] [--havels] [--favor]
```

- `weapons` defaults to the starter-safe catalog; `--all` exposes the bundled catalog.
- `calc` and `compare` are approximate for known rows. NEVER invent missing AR.
- DS3 roll thresholds are `<30%` fast, `30-70%` medium, `70-100%` fat, and `>100%` overburdened.

## Progression and items

```text
areas [--spoilers]
bosses [--area <area>] [--required] [--spoilers]
route [--defeated boss-id,boss-id] [--spoilers]
npcs [<name-or-key>] [--all] [--missable]
rings [<ring-name>] [--build quality|strength|dex|sorcerer|pyro|cleric|luck]
spells [<spell-name>] [--type sorcery|miracle|pyromancy] [--achievement]
covenants [<covenant-id>]
farm [shards|large-shards|chunks|slabs|twinkling|scales|proofs|shackles|medals|grass|dregs|tongues]
estus [shards|bones|allotment|max]
```

- Default route/area/boss output is spoiler-safe.
- Use `--spoilers` only with permission; it NEVER overrides an explicit no-spoiler request.
- Exact routes, locations, quest steps, and contested details require fresh source evidence.
- DS3 has 11 Estus Shards, 10 Undead Bone Shards, and at most 15 flask uses.

## Achievements, guide, audit, tracking, and sources

```text
achievements [--missable] [--plat-route]
guide info
guide kinds
guide headings
guide search [query] [--kind <kind>] [--heading <text>] [--limit N] [--json]
guide get <row-number> [--json]
mods [--current]
audit
track [summary|stats|gear|next] --path <tracking-json>
recommend --path <tracking-json>
sources list
sources status
sources policy
sources explain <source-key>
sources refresh [source-key ...] [--force]
```

- The 43 platinum achievements are base-game achievements; DLC is not required.
- `track` and `recommend` read an explicit file. The skill never owns or persists tracking state.
- `guide` searches the transformed, user-provided PSNProfiles platinum-walkthrough corpus.
- Guide output is spoiler-heavy, non-authoritative, not parser/save truth, and not permission to republish the PDF or its text.
- Summarize only the minimum guide text needed. `--json` changes representation, not evidence quality.

## Read-only save support

Auto-detection checks `%APPDATA%/DarkSoulsIII/*/DS30000.sl2`.

```text
save [auto|<path-to-DS30000.sl2>] [summary|stats|name|level|covenants|bosses|bonfires|progress|inventory|gestures|missed|achievements|checklist|owned|completion] [--all] [--find TEXT]
```

Default:

```text
save auto summary
```

Scoped inventory:

```text
save auto inventory --find "Sellsword"
save auto owned --find "Ring"
save auto inventory --all
```

Supported facts include validated character identity, class, level, souls, stats, Estus, max reinforcement, known boss flags, tracked bonfire flags, covenant fields, and conservatively resolved inventory rows. Rings, sorceries, pyromancies, and miracles may be completion-counted only when inventory IDs resolve.

Boundaries:

- Save reading is read-only. NEVER mutate `.sl2`.
- Unknown raw IDs remain unknown.
- Missing area checklist means unknown, not clear.
- Gestures and infusion-achievement completion are static/unsupported; NEVER present them as save-backed.
- Reinforcement level is observable; reinforcement-achievement completion remains unsupported.
- Compact inventory truncates. Use `--all` or `--find` before claiming absence.
- A save may be stale, transferred, edited, a different character, or a different NG cycle/build.
- If auto-detection fails, request an explicit `.sl2` path.

## Intent routing

| User need | First action | Boundary |
| --- | --- | --- |
| Current stats/class/Estus/progress | `save auto summary` or `save auto stats` | Only verified fields are facts |
| Exact owned item | `save auto inventory --find "<name>"` | Unresolved IDs remain unknown |
| Missing checklist item | `save auto missed` or `save auto checklist` | Missing checklist data is not completion |
| Level/build direction | `save auto stats`, `softcaps`, `build` | Compare tradeoffs; do not infer a default build |
| AR/scaling | `calc`, `compare`, `weapons`, `infusions` | NEVER guess missing AR |
| Upgrade materials | `upgrade`, `farm` | Live-check exact locations/routes |
| Rings/spells/covenants | `rings`, `spells`, `covenants`, `farm` | Use save completion only when ownership matters |
| Route/areas/bosses | `areas`, `bosses`, `route`, `save auto progress` | Keep future names hidden by default |
| Platinum cleanup | `achievements`, save completion, then narrow `guide search` | Guide text is not parser truth |
| Mods/current facts | `sources status`, `mods --current` | Live-check releases and compatibility |
| Source-backed request | `sources status`, targeted refresh, live research | Cite final URLs |
