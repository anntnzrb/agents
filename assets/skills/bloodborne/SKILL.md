---
name: bloodborne
description: "Generic spoiler-safe Bloodborne companion/reference skill. Use for Bloodborne gameplay questions: stats, builds, origins, weapons, upgrades, echoes/vials, Insight, Caryll runes, Blood Gems, combat mechanics, routing, farming, controls, item mechanics, and no-spoiler guidance. Use local tracking only if the active workspace provides it; the skill itself stores no playthrough state."
license: GPL-3.0-or-later
metadata:
  author: anntnzrb
allowed-tools: "Read, Bash, WebSearch"
---

# Bloodborne Companion

Provide spoiler-safe Bloodborne help using the bundled deterministic CLI first, then live research when needed. The skill is generic and stateless: it does not store player progress, tone preferences, or local workspace paths.

## Entry point

Agents run the single bundled CLI entry point:
```text
uv run --script <skill-dir>/scripts/cli.py ...
```

No other Bloodborne CLI is required. Do not ask the user to run commands manually.

Local tracking files are workspace state, not skill state. The CLI may read a caller-supplied tracking file for `track` and `recommend`, but it never owns or persists playthrough state.

## Workflow

1. If the active workspace has a local tracking file and the question depends on current build/progress/gear/location, read it before answering.
2. Use the CLI for deterministic mechanics, math, summaries, savefile reads, source status/cache refreshes, and first-pass recommendations.
3. Use live web research only when CLI/save/static data cannot answer, cached source data is stale/missing, or the user explicitly asks for corroboration.
4. Filter spoilers before replying. Do not paste raw web/CLI output that contains unintroduced names.
5. Answer with the actionable result first, then the reason.


## Natural-language routing

Route user questions by intent, not by exact wording:

| User asks about | First source | Then | Notes |
|---|---|---|---|
| current stats, exact inventory, defeated bosses, materials, key items | `save <path> summary` if a save path is provided | caller-supplied tracking file if no save path | Save parser is factual; tracking is contextual. |
| where to allocate levels, build direction, weapon choice | `track`/`recommend` or `save` stats | `calc`, `softcaps`, `weapons` | Use current stats before generic advice. |
| weapon AR, scaling, stat breakpoints | `calc`, `weapons`, `softcaps` | `sources status bb-wiki-scaling`; refresh if stale and source-backed answer requested | Do not guess AR. |
| upgrade materials and upgrade order | `upgrade <level>` | `save materials` if a save exists | Main weapon first unless user explicitly pivots. |
| Insight, runes, gems, farming, durability, consumables | `insight`, `runes`, `gems`, `farm` | source registry/live research when exact thresholds or shop unlocks matter | Keep thresholds spoiler-filtered. |
| route planning / “what next?” | caller-supplied tracking file + save boss/key state | live research if exact route/item checklist requested | Never reveal future proper nouns unless user permits spoilers. |
| source-backed or latest-data request | `sources status` | `sources refresh <keys>` and web research | Cite source URLs in final. |
| shadPS4/decrypted save analysis | `save <path> ...` | update local tracking only if user asks | Read-only; explicit path only. |

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
uv run --script <skill-dir>/scripts/cli.py farm [echoes|vials|twins|chunks|gems]
uv run --script <skill-dir>/scripts/cli.py track [summary|stats|gear|next] --path <tracking-file>
uv run --script <skill-dir>/scripts/cli.py recommend --path <tracking-file>
uv run --script <skill-dir>/scripts/cli.py save <savefile> [summary|stats|materials|weapons|keys|bosses]
uv run --script <skill-dir>/scripts/cli.py sources list
uv run --script <skill-dir>/scripts/cli.py sources status
uv run --script <skill-dir>/scripts/cli.py sources refresh [source-key ...]
```

Use `track` and `recommend` only with an explicit `--path <tracking-file>` or `BLOODBORNE_TRACKING_FILE`; the skill does not assume a filename. Use `save <path>` only for explicit savefiles supplied by the user; it is read-only and stateless. Prefer filtered `weapons "<known weapon>"`; avoid bare `weapons` in spoiler-sensitive flows because it lists late/DLC names. Use `sources status` before source-backed answers; use `sources refresh` when the relevant cache is older than 24 hours or missing.

## Spoiler policy

Allowed:

- Mechanics: stats, softcaps, weapon scaling, upgrade materials, durability, Insight thresholds, gems, runes, rally/parry/visceral, controls, and combat fundamentals.
- Names, locations, bosses, NPCs, and items already provided by the user or present in an active local tracking file.

Forbidden unless already introduced by the user/tracking:

- Future boss names, future area names, NPC identities or quest outcomes, item locations, story/lore reveals, endings, DLC boss/area names, and chalice dungeon specifics.

When uncertain, use generic terms: “the next boss”, “that optional area”, “the current route”, “the item you found”.

## Savefile analysis

The CLI can parse shadPS4 / decrypted Bloodborne userdata files read-only:

```text
uv run --script <skill-dir>/scripts/cli.py save <savefile> summary
uv run --script <skill-dir>/scripts/cli.py save <savefile> stats
uv run --script <skill-dir>/scripts/cli.py save <savefile> materials
uv run --script <skill-dir>/scripts/cli.py save <savefile> bosses
```

Save parsing uses static resources from `Noxde/Bloodborne-save-editor` (GPL-3.0): `offsets.json`, `bosses.json`, `items.json`, `weapons.json`, `armors.json`, `upgrades.json`. The parser does not mutate saves, create backups, edit stats/items/boss flags, teleport, re-encrypt, or repair files.

Default `save summary` output hides unknown future boss names. Treat future names from resource files as internal parser data unless the user explicitly permits spoilers.

## Tracking boundary

This skill does not own tracking. Local projects may provide a caller-defined tracking file with current stats, gear, lamps, bosses, route state, and priorities. If present and explicitly supplied by path or environment, treat it as local context for the active run. Update it only when the user explicitly asks or local repository instructions require it.

The skill should remain useful without tracking: answer generic mechanics questions from CLI/reference data, and ask for current stats/progress only when the answer materially depends on them.

## Source registry and cache

The CLI has a curated source registry from live research:

- `bloodborne-wiki.com` pages are the primary public data source for scaling, weapon stats, gems, runes, and Insight. They expose page revision metadata and CC BY-SA 3.0 licensing.
- `soulsmods/DSMapStudio` Paramdex is the safest licensed schema reference for Bloodborne PARAM field names (MIT), but it does not provide weapon rows.
- Unlicensed calculators/repos are reference-only. Do not copy their code or data into the skill; use them only to cross-check formulas.

The cache is user-local at `~/.cache/bloodborne-companion` unless `BLOODBORNE_CACHE_DIR` is set. Cached source pages include URL, license, fetch time, byte count, SHA-256, and a 24-hour TTL. Runtime remains stateless with respect to playthrough progress.

## Live research fallback

Use web/Brave/Reddit when the CLI lacks coverage or the user asks for source-backed corroboration. Keep queries spoiler-safe by avoiding future proper nouns unless the user already named them.

Examples:

```text
Bloodborne Insight thresholds effects
Bloodborne Moon Eye Beast rune effects
Bloodborne Blood Gem physical attack up elemental conversion
Bloodborne echo farm current progress no spoilers
Bloodborne weapon durability threshold at risk
```

Separate researched facts from recommendations and cite sources when the user requested live corroboration.
