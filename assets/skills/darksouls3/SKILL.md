---
name: darksouls3
description: "Spoiler-safe Dark Souls 3 companion/reference skill. Use for DS3 gameplay questions: stats, builds, classes, weapons, infusions, upgrades, titanite, souls, Estus, covenants, combat mechanics, routing, farming, controls, item mechanics, achievements, mods, and no-spoiler guidance. Covers base game + DLCs. PC-native: no emulation. Mod-aware: supports Mod Engine 1 (dinput8 proxy / passive) and Mod Engine 3 (ME3 / injection-based for legit Steam)."
license: GPL-3.0-or-later
metadata:
  author: anntnzrb
allowed-tools: "Read, Bash, WebSearch"
---

# Dark Souls 3 Companion

Provide spoiler-safe DS3 help using the bundled deterministic CLI first, then live research when needed. The skill is generic and stateless: it does not store player progress, tone preferences, or local workspace paths.

## Entry point

Agents run the single bundled CLI entry point:
```text
uv run --script <skill-dir>/scripts/cli.py ...
```

No other DS3 CLI is required. Do not ask the user to run commands manually.

Local tracking files are workspace state, not skill state. The CLI may read a caller-supplied tracking file for `track` and `recommend`, but it never owns or persists playthrough state.

## Workflow

1. If the active workspace has a local tracking file and the question depends on current build/progress/gear/location, read it before answering.
2. Use the CLI for deterministic mechanics, math, summaries, and first-pass recommendations.
3. Use live web research only when CLI/static data cannot answer, cached source data is stale/missing, or the user explicitly asks for corroboration.
4. Filter spoilers before replying. Do not paste raw web/CLI output that contains unintroduced names.
5. Answer with the actionable result first, then the reason.

## Natural-language routing

Route user questions by intent, not by exact wording:

| User asks about | First source | Then | Notes |
|---|---|---|---|
| current stats, exact inventory, soul level | tracking file if path provided | `origins` for base comparison | No savefile parser (encrypted .sl2). |
| where to allocate levels, build direction, weapon choice | `build`, `softcaps`, `origins` | `calc`, `compare`, `weapons`, `infusions` | Use current stats from tracking before generic advice. |
| weapon AR, scaling, stat breakpoints, infusion effects | `calc`, `compare`, `weapons`, `softcaps`, `infusions` | `sources status`; refresh if stale | Do not guess AR. |
| upgrade materials and upgrade paths | `upgrade <level>` | `farm <material>` | Main weapon to max first. |
| titanite types, farming locations | `farm <shards|chunks|slabs|twinkling|scales>` | source registry / live research | Keep farming locations generic (no boss names). |
| Estus shards, bone shards, flask allotment | `estus` | tracking file if present | 11 shards, 10 bone shards, max 15 uses. |
| soul cost to level up | `soul-cost <current> <target>` | — | DS3 uses cumulative polynomial formula. |
| equip load, roll types, fat-rolling | `equip-load [--vitality N]` | `softcaps` for VIT breakpoints | <30% fast, 30-70% medium, 70-100% fat. |
| infusions, which infusion for my build | `infusions [<weapon>]` | `build` for context | 15 infusion types. |
| covenants, covenant rewards, farming | `covenants [<id>]` | `farm <covenant-item>` | Offline farming takes 6-10 hours for hardest. |
| areas, bosses, key items, "what did I miss?" | `areas`, `bosses`, `route` | live research for full checklists | Default commands use safe names where possible. |
| route planning / "what next?" | `route` with explicit defeated IDs or tracking | live research if exact route needed | Never reveal future proper nouns unless user permits spoilers. |
| achievements, plat route, missable content | `achievements [--missable]` | live research for full guides | 43 achievements, base game only. |
| mods, mod engine, FPS unlock, stutter fix | `mods` | live research for latest versions | Mod Engine 1 (passive), ME3 (injection, legit only). |
| source-backed or latest-data request | `sources status` | `sources refresh <keys>` and web research | Cite source URLs in final. |

## CLI commands

```text
uv run --script <skill-dir>/scripts/cli.py fresh
uv run --script <skill-dir>/scripts/cli.py softcaps
uv run --script <skill-dir>/scripts/cli.py origins [quality|str|dex|int|fth|pyro|luck]
uv run --script <skill-dir>/scripts/cli.py upgrade <1-10>
uv run --script <skill-dir>/scripts/cli.py weapons "<known weapon name>"
uv run --script <skill-dir>/scripts/cli.py calc "<weapon>" <str> <dex> <int> <fth>
uv run --script <skill-dir>/scripts/cli.py soul-cost <current-level> <target-level>
uv run --script <skill-dir>/scripts/cli.py estus [shards|bones|allotment]
uv run --script <skill-dir>/scripts/cli.py infusions [<weapon-name>]
uv run --script <skill-dir>/scripts/cli.py equip-load [--vitality N] [--havels | --favor | --both]
uv run --script <skill-dir>/scripts/cli.py covenants [<covenant-id>]
uv run --script <skill-dir>/scripts/cli.py farm <shards|large-shards|chunks|slabs|twinkling|scales|proofs|shackles|medals|grass|dregs>
uv run --script <skill-dir>/scripts/cli.py build [quality|strength|dexterity|sorcerer|pyromancer|cleric|luck] [--level N]
uv run --script <skill-dir>/scripts/cli.py compare "<weapon A>" "<weapon B>" --str N --dex N [--int N] [--fth N]
uv run --script <skill-dir>/scripts/cli.py areas [--phase early|mid|late|dlc] [--spoilers]
uv run --script <skill-dir>/scripts/cli.py bosses [--area <area>] [--required] [--spoilers]
uv run --script <skill-dir>/scripts/cli.py route [--defeated boss-id,boss-id] [--spoilers]
uv run --script <skill-dir>/scripts/cli.py achievements [--missable] [--plat-route]
uv run --script <skill-dir>/scripts/cli.py mods [--current]
uv run --script <skill-dir>/scripts/cli.py audit [--sources]
uv run --script <skill-dir>/scripts/cli.py track [summary|stats|gear|next] --path <tracking-file>
uv run --script <skill-dir>/scripts/cli.py recommend --path <tracking-file>
uv run --script <skill-dir>/scripts/cli.py sources list
uv run --script <skill-dir>/scripts/cli.py sources status
uv run --script <skill-dir>/scripts/cli.py sources refresh [source-key ...] [--force]
```

Use `audit` after changing static data or refreshing references. Use `track` and `recommend` only with explicit `--path`. Prefer filtered `weapons`; bare `weapons` lists only starter-safe weapons. Use `areas --spoilers`, `bosses --spoilers` only when the user permits spoilers. Use `route` with explicit defeated IDs for "what next?" answers.

## Spoiler policy

Allowed:
- Mechanics: stats, softcaps, weapon scaling, upgrade materials, durability, infusions, equip load, poise/hyperarmor, parry/riposte/backstab, weapon arts, FP, Estus, covenants (mechanics only), controls, and combat fundamentals.
- Names, locations, bosses, NPCs, and items already provided by the user or present in an active local tracking file.

Forbidden unless already introduced by the user/tracking:
- Future boss names, future area names, NPC identities or quest outcomes, item locations, story/lore reveals, endings, DLC boss/area names.

When uncertain, use generic terms: "the next boss", "that optional area", "the current route", "the item you found".

## Mod awareness

The skill is PC-native and mod-aware. Key mods:

- Mod Engine 1 (passive dinput8.dll proxy): works with cracked and legit copies. No injection, no detection. Mods in `mod/` folder.
- Mod Engine 3 / ME3 (injection-based launcher): works with legit Steam only. Faster loading (boot_boost), logo skip, arxan disable. Hook collision with cracked exes.
- Proper PC Experience (d3d11.dll proxy): FPS unlock, refresh rate, FoV, skip intro. Works passively with any setup.
- FromStutterFix (dinput8 chain-loaded): frame-pacing micro-stutter fix. Universal.
- Blue Sentinel (dinput8.dll, anti-cheat): online protection, player overlay, save backups. Legit Steam only.
- Camera Fix (ME3-native DLL): disables auto-center camera rotation. Requires ME3 or Mod Engine 2.

Use `mods` command for current recommendations based on legit/cracked status.

## Tracking boundary

This skill does not own tracking. Local projects may provide a caller-defined tracking file with current stats, gear, bonfires, bosses, route state, and priorities. If present and explicitly supplied by path or environment, treat it as local context for the active run. Update it only when the user explicitly asks.

The skill should remain useful without tracking: answer generic mechanics questions from CLI/reference data, and ask for current stats/progress only when the answer materially depends on them.

## Source registry and cache

The CLI has a curated source registry from live research:

- `darksouls3.wiki.fextralife.com` — primary public data source for stats, weapons, infusions, upgrades, areas, bosses, covenants. CC BY-NC-SA. Updated June 2026.
- `darksouls3.wikidot.com` — secondary reference. CC BY-SA 3.0. Less frequently updated but license is more permissive.
- `mugenmonkey.com/darksouls3` — AR calculator and class planner for formula cross-checking.
- `soulsplanner.com/darksouls3` — build planner reference.
- `zkjellberg.github.io/dark-souls-3-cheat-sheet` — interactive checklist/tracker. MIT.
- `www.pcgamingwiki.com/wiki/Dark_Souls_III` — technical fixes and PC-specific issues.
- `github.com/soulsmods` — modding tools (DSMapStudio, SoulsFormats, UXM, WitchyBND). MIT/GPL.
- `github.com/katalash/ModEngine` — Mod Engine 1 source (dinput8 proxy).
- `github.com/garyttierney/me3` — Mod Engine 3 source.

The cache is user-local at `~/.cache/darksouls3-companion` unless `DS3_CACHE_DIR` is set. Cached source pages include URL, license, fetch time, byte count, SHA-256, and a 24-hour TTL. Runtime remains stateless with respect to playthrough progress.

## Live research fallback

Use web/Brave/Reddit when the CLI lacks coverage or the user asks for source-backed corroboration. Keep queries spoiler-safe.

Examples:
```text
Dark Souls 3 Vigor HP per level softcap
Dark Souls 3 proof of concord kept farming offline
Dark Souls 3 weapon AR calculator heavy infusion
Dark Souls 3 equip load thresholds fast roll
Dark Souls 3 estus shard locations no spoilers
```
