---
name: bloodborne
description: Spoiler-safe Bloodborne help for builds, mechanics, weapons, routing, farming, and progression.
license: AGPL-3.0-or-later
metadata:
  author: anntnzrb

---

# Bloodborne Companion

Use the bundled deterministic CLI first; use live research only as specified below. Generic and stateless: no player progress, tone preferences, or local workspace paths stored.

## Entry point

Single CLI:
```text
uv run --script <skill-dir>/scripts/cli.py ...
```
No other Bloodborne CLI; NEVER ask the user to run commands manually.

Tracking files are workspace state, not skill state. CLI may read a caller-supplied tracking file for `track`/`recommend`, but never owns or persists playthrough state.

## Workflow

1. If an active workspace has a local tracking file and the answer depends on current build, progress, gear, or location, read it first.
2. Use CLI for deterministic mechanics/math, summaries, save reads, source status/cache refreshes, and first-pass recommendations.
3. Use live web research only when CLI/save/static data cannot answer, cached source data is stale/missing, or the user explicitly requests corroboration.
4. Filter spoilers; never paste raw web/CLI output containing unintroduced names.
5. Give the actionable result first, then the reason.

## Intent routing

Route by intent, not exact wording. First source → fallback; apply notes:

- Current stats, exact inventory, defeated bosses, materials, key items → `save <path> summary` when save path provided; otherwise caller tracking file. Save parser is factual; tracking contextual.
- Level allocation, build direction, weapon choice → `build`, `track`/`recommend`, or `save` stats → `calc`, `compare`, `softcaps`, `weapons`; use current stats before generic advice.
- Weapon AR, scaling, stat breakpoints → `calc`, `compare`, `weapons`, `softcaps` → `sources status bb-wiki-scaling` (refresh if stale and source-backed answer requested); NEVER guess AR.
- Upgrade materials/order → `upgrade <level>` → `save materials` when save exists; main weapon first unless user explicitly pivots.
- Insight, runes, gems, farming, durability, consumables → `insight`, `runes`, `gems`, `farm`; for exact player state also `save <path> runes` / `save <path> gems` → source registry/live research when exact thresholds or shop unlocks matter. Keep thresholds spoiler-filtered; save runes/gems authoritative for actual inventory.
- Areas, bosses, key items, checklist, “what did I miss?” → `areas`, `bosses`, `items`, `checklist`; live research only for full item-location checklists. Defaults use safe names where possible.
- Route/“what next?” → `route` with explicit defeated IDs, caller-supplied tracking, or save boss/key state; live research for exact route/item checklist. NEVER reveal future proper nouns without permission.
- Source-backed/latest-data → `sources status` → `sources refresh <keys>` and web research; cite source URLs in final.
- shadPS4/decrypted save analysis → `save <path> ...` (`summary|stats|materials|weapons|keys|bosses|runes|gems`); update tracking only if asked. Read-only, explicit path only; runes/gems use Noxde editor offset-based parsing.

## CLI commands

```text
uv run --script <skill-dir>/scripts/cli.py fresh
uv run --script <skill-dir>/scripts/cli.py softcaps
uv run --script <skill-dir>/scripts/cli.py origins [quality|str|skl|blt|arc]
uv run --script <skill-dir>/scripts/cli.py upgrade <1-10>
uv run --script <skill-dir>/scripts/cli.py weapons "<known weapon name>"
uv run --script <skill-dir>/scripts/cli.py calc "<weapon>" <str> <skl> <blt> <arc>
uv run --script <skill-dir>/scripts/cli.py echo-cost <current-level> <target-level>
uv run --script <skill-dir>/scripts/cli.py insight [current]
uv run --script <skill-dir>/scripts/cli.py runes
uv run --script <skill-dir>/scripts/cli.py gems
uv run --script <skill-dir>/scripts/cli.py farm <echoes|vials|twins|chunks|gems>
uv run --script <skill-dir>/scripts/cli.py build [quality|strength|skill|bloodtinge|arcane] [--level N]
uv run --script <skill-dir>/scripts/cli.py compare "<weapon A>" "<weapon B>" --str N --skl N [--blt N] [--arc N]
uv run --script <skill-dir>/scripts/cli.py areas [--phase start|evening|night|blood-moon|nightmare|dlc] [--spoilers]
uv run --script <skill-dir>/scripts/cli.py bosses [--area <area>] [--required] [--spoilers]
uv run --script <skill-dir>/scripts/cli.py items <name words> [--spoilers]
uv run --script <skill-dir>/scripts/cli.py checklist <area> [--spoilers]
uv run --script <skill-dir>/scripts/cli.py route [--defeated boss-id,boss-id] [--spoilers]
uv run --script <skill-dir>/scripts/cli.py audit [--sources]
uv run --script <skill-dir>/scripts/cli.py track [summary|stats|gear|next] --path <tracking-file>
uv run --script <skill-dir>/scripts/cli.py recommend --path <tracking-file>
uv run --script <skill-dir>/scripts/cli.py sources list
uv run --script <skill-dir>/scripts/cli.py save <savefile> [summary|stats|materials|weapons|keys|bosses|runes|gems]
uv run --script <skill-dir>/scripts/cli.py sources status
uv run --script <skill-dir>/scripts/cli.py sources refresh [source-key ...] [--force]
```

`audit` after changing static data or refreshing references; add `--sources` only when the generic source cache was intentionally refreshed and must be fresh. `track`/`recommend` require explicit `--path <tracking-file>` or `BLOODBORNE_TRACKING_FILE`; never assume a filename. `save <path>` requires an explicitly supplied savefile; read-only/stateless. Prefer filtered `weapons "<known weapon>"`; bare `weapons` lists starter-safe weapons unless `--spoilers`. In spoiler-sensitive flows avoid `areas --spoilers`, `bosses --spoilers`, `items --spoilers` because they list late/DLC names. For first-pass “what next?”, use `route` with explicit defeated IDs or parsed save/tracking context. Use `sources status` before source-backed answers; use `sources refresh --force` only when bypassing the 24-hour cache is explicitly useful.

## Spoiler policy

Allowed: mechanics (stats, softcaps, weapon scaling, upgrade materials, durability, Insight thresholds, gems, runes, rally/parry/visceral, controls, combat fundamentals); names, locations, bosses, NPCs, and items already supplied by the user or active local tracking.

Forbidden unless already introduced by user/tracking: future boss/area names, NPC identities or quest outcomes, item locations, story/lore reveals, endings, DLC boss/area names, and chalice-dungeon specifics.

When uncertain, say “the next boss”, “that optional area”, “the current route”, or “the item you found”.

## Savefile analysis

The CLI parses shadPS4/decrypted Bloodborne userdata read-only:
```text
uv run --script <skill-dir>/scripts/cli.py save <savefile> summary
uv run --script <skill-dir>/scripts/cli.py save <savefile> stats
uv run --script <skill-dir>/scripts/cli.py save <savefile> materials
uv run --script <skill-dir>/scripts/cli.py save <savefile> bosses
```

Static resources come from `Noxde/Bloodborne-save-editor` (GPL-3.0): `offsets.json`, `bosses.json`, `items.json`, `weapons.json`, `armors.json`, `upgrades.json`. Parser NEVER mutates saves, creates backups, edits stats/items/boss flags, teleports, re-encrypts, or repairs files. Default `save summary` hides unknown future boss names; future names in resource files remain internal parser data unless the user explicitly permits spoilers.

## Tracking boundary

This skill does not own tracking. A caller-defined local tracking file may contain current stats, gear, lamps, bosses, route state, and priorities. If explicitly supplied by path or environment, treat it as active-run context; update only when the user asks or repository instructions require it.

Without tracking, answer generic mechanics from CLI/reference data; ask for current stats/progress only when materially necessary.

## Sources and cache

Curated live-research registry:
- `bloodborne-wiki.com`: primary public source for scaling, weapon stats, gems, runes, and Insight; page revision metadata; CC BY-SA 3.0.
- `soulsmods/DSMapStudio` Paramdex: safest licensed Bloodborne PARAM-field schema (MIT); no weapon rows.
- Unlicensed calculators/repos: reference-only; NEVER copy their code/data into the skill, only cross-check formulas.

Cache: user-local `~/.cache/bloodborne-companion`, or `BLOODBORNE_CACHE_DIR`. Cached pages include URL, license, fetch time, byte count, SHA-256, and 24-hour TTL. Revision metadata remains in cached HTML unless a future parser extracts it. Runtime remains stateless regarding playthrough progress.

## Required follow-up reads

| Need | Read | When |
| --- | --- | --- |
| Save-resource provenance | `scripts/resources/bloodborne_save/SOURCES.md` | Before replacing parser data or changing supported save claims |

## Live research fallback

Use web/Brave/Reddit when CLI lacks coverage or the user asks for source-backed corroboration. Keep queries spoiler-safe; avoid future proper nouns unless the user already named them. Examples:
```text
Bloodborne Insight thresholds effects
Bloodborne Moon Eye Beast rune effects
Bloodborne Blood Gem physical attack up elemental conversion
Bloodborne echo farm current progress no spoilers
Bloodborne weapon durability threshold at risk
```
Separate researched facts from recommendations; cite sources when the user requested live corroboration.
