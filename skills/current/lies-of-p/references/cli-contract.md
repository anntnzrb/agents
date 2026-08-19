# CLI contract

Run: `uv run --script <skill-dir>/scripts/cli.py [--json] COMMAND`; from this skill directory: `uv run --script scripts/cli.py COMMAND`.

Commands: `fresh`; `build [--level N]`; `weaknesses [query]`; `bosses [query] [--spoilers]`; `route --chapter N [--dlc] [--spoilers]`; `trophies [query] [--dlc] [--spoilers]`; `checklist --chapter N [--dlc] [--spoilers]`; `farm [stage]`; `community [query] [--spoilers]`; `compare --candidate 'NAME,PHYSICAL,ELEMENTAL,CRIT_PERCENT,WEIGHT'` (repeatable); `sources [list|status|explain]`; `audit`.

Output: deterministic UTF-8 text. `--json`: compact sorted-key JSON, formatting only; never bypasses spoiler filtering. Missing/malformed resources or invalid arguments: error to stderr, status 2.

`community`: reads `resources/community.json`; returns versioned, sourced weapon, amulet, and boss-wall records. Separates verified facts from sentiment, dissent, recommendation, context, and confidence; preferences ≠ mechanics. Without `--spoilers`, filters spoiler/DLC records.

`compare`: accepts ≥1 candidate. Physical, elemental, and weight stats, plus `--motion`, MUST be nonnegative; `crit_percent`: 0-100; `--critical-multiplier`: ≥1; retained physical/elemental factors: 0-1. Invalid input → status 2.

`displayed_ar = physical + elemental`  
`adjusted_hit = (physical × physical_retained + elemental × elemental_retained) × motion`

With a critical multiplier: `expected_hit = adjusted_hit × (1 + crit_percent/100 × (critical_multiplier − 1))`. Rank by `expected_hit` when available; otherwise `adjusted_hit`.

Comparator scope: deterministic displayed-AR arithmetic only. Excludes enemy defense, hidden scaling/saturation, animation DPS, status buildup, and Fable effects; makes no claim of exact hidden AR, scaling, or DPS.

`fresh`: displays version, difficulty, complete build object.  
`build`: displays the same build object; `--level N` adds `level`. Weapon fields describe the Technique lane: Path of the Bastard or Wintry Rapier start → Booster Glaive handle in Chapter 3 → Bone-Cutting Sawblade acquisition in Chapter 5's Malum District → Sawblade + Booster assembly.

Without `--spoilers`, `bosses` returns aggregate count/type guidance; a named query returns only that base-game boss's name and generic guidance, never future names, areas, or plans. `--spoilers` returns full rows.

`audit`: checks required top-level schemas, normalized source-registry fields (`url`, `title`, `kind`, `checked`, `version_scope`, `confidence`, `license_or_terms`, `notes`), deterministic collection counts, and required 43 base/11 Overture trophy counts.
