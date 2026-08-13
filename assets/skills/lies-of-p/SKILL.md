---
name: lies-of-p
description: Deterministic Lies of P 1.12.0.0 and Overture platinum companion with spoiler-safe routes.
license: AGPL-3.0-or-later
---

# Lies of P companion

Use the CLI as the public entry point:
`uv run --script <skill-dir>/scripts/cli.py COMMAND`

- Build planning, leveling, or defaults: `fresh`, then `build`; ask level only when needed
- Enemy matchup: `weaknesses [query]`; read `game_data.json` when a result needs context
- Boss or area route: `bosses [query]`; add `--spoilers` only after explicit consent
- Chapter progression: `route --chapter N`; use `--dlc` for Overture and `--spoilers` explicitly
- Trophy completion: `trophies [query]`; use `checklist --chapter N` for actionable chapter work
- Farming: `farm [stage]`; avoid consumable/throwable-dependent strategies
- Meta, preferences, and community consensus: `community [query]`; add `--spoilers` only after explicit consent
- Displayed AR or inventory candidate comparison: `compare --candidate 'NAME,PHYSICAL,ELEMENTAL,CRIT_PERCENT,WEIGHT'` (repeat candidates)
- Provenance: `sources list|status|explain`; `audit` for schema/source integrity

Default to Legendary Stalker, no Specters or summons, and spoiler-safe output. Difficulty does not alter trophy requirements. Never infer missing data: report the CLI error and request the required follow-up read. Preserve version, source, and confidence fields when presenting records. `--json` changes formatting only and never disables spoiler filtering.

Comparison is a deterministic displayed-AR aid, not hidden damage or DPS: displayed AR is physical + elemental; optional motion, retained lanes, and critical multiplier adjust a hit estimate. Enemy defense, hidden scaling/saturation, animation DPS, status buildup, and Fable effects are excluded. Community preferences are sentiment, not mechanics; dissent and confidence remain visible. Never claim exact hidden AR, scaling, or DPS.
## Required follow-up reads
|Need|Read|When|
|---|---|---|
|Combat loop, weapon assembly, and stat lane|`references/combat.md`|Any build or matchup advice|
|Chapter route and weapon acquisition timing|`references/progression.md`|Any route or chapter question|
|Trophy, ending, and collectible requirements|`references/platinum.md`|Any completion or trophy question|
|Evaluation coverage and spoiler boundaries|`references/eval-coverage.md`|When validating an answer or route|
|CLI commands, arguments, and output contract|`references/cli-contract.md`|Before invoking or describing the CLI|
|Structured weapon, boss, and weakness records|`resources/game_data.json`|When CLI output needs record context|
|Source provenance and confidence|`resources/source_registry.json`|When citing or auditing a record|
|Community sentiment and calculator evidence|`resources/community.json`|When `community` output or comparison context needs record context|
|Trophy and chapter checklist records|`resources/platinum.json`|When trophy output needs record context|
