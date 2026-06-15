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
uv run --script ~/.config/agents/assets/skills/bloodborne/scripts/cli.py ...
```

No other Bloodborne CLI is required. Do not ask the user to run commands manually.

Local `tracking.md` files are workspace state, not skill state. The CLI may read a workspace `tracking.md` for `track` and `recommend`, but it never owns or persists playthrough state.

## Workflow

1. If the active workspace has `tracking.md` and the question depends on current build/progress/gear/location, read it before answering.
2. Use the CLI for deterministic mechanics, math, summaries, source status/cache refreshes, and first-pass recommendations.
3. Use live web research only when CLI data cannot answer, cached source data is stale/missing, or the user explicitly asks for corroboration.
4. Filter spoilers before replying. Do not paste raw web/CLI output that contains unintroduced names.
5. Answer with the actionable result first, then the reason.

## CLI commands

```text
uv run --script ~/.config/agents/assets/skills/bloodborne/scripts/cli.py fresh
uv run --script ~/.config/agents/assets/skills/bloodborne/scripts/cli.py softcaps
uv run --script ~/.config/agents/assets/skills/bloodborne/scripts/cli.py origins [quality|str|skl|blt|arc]
uv run --script ~/.config/agents/assets/skills/bloodborne/scripts/cli.py upgrade <1-10>
uv run --script ~/.config/agents/assets/skills/bloodborne/scripts/cli.py weapons "<known weapon name>"
uv run --script ~/.config/agents/assets/skills/bloodborne/scripts/cli.py calc "<weapon>" <str> <skl> <blt> <arc>
uv run --script ~/.config/agents/assets/skills/bloodborne/scripts/cli.py echo-cost <current-level> <target-level>
uv run --script ~/.config/agents/assets/skills/bloodborne/scripts/cli.py insight [current]
uv run --script ~/.config/agents/assets/skills/bloodborne/scripts/cli.py runes
uv run --script ~/.config/agents/assets/skills/bloodborne/scripts/cli.py gems
uv run --script ~/.config/agents/assets/skills/bloodborne/scripts/cli.py farm [echoes|vials|twins|chunks|gems]
uv run --script ~/.config/agents/assets/skills/bloodborne/scripts/cli.py track [summary|stats|gear|next]
uv run --script ~/.config/agents/assets/skills/bloodborne/scripts/cli.py recommend
uv run --script ~/.config/agents/assets/skills/bloodborne/scripts/cli.py sources list
uv run --script ~/.config/agents/assets/skills/bloodborne/scripts/cli.py sources status
uv run --script ~/.config/agents/assets/skills/bloodborne/scripts/cli.py sources refresh [source-key ...]
```

Use `track` and `recommend` only when the active workspace has a relevant `tracking.md`. Prefer filtered `weapons "<known weapon>"`; avoid bare `weapons` in spoiler-sensitive flows because it lists late/DLC names. Use `sources status` before source-backed answers; use `sources refresh` when the relevant cache is older than 24 hours or missing.

## Spoiler policy

Allowed:

- Mechanics: stats, softcaps, weapon scaling, upgrade materials, durability, Insight thresholds, gems, runes, rally/parry/visceral, controls, and combat fundamentals.
- Names, locations, bosses, NPCs, and items already provided by the user or present in an active local tracking file.

Forbidden unless already introduced by the user/tracking:

- Future boss names, future area names, NPC identities or quest outcomes, item locations, story/lore reveals, endings, DLC boss/area names, and chalice dungeon specifics.

When uncertain, use generic terms: “the next boss”, “that optional area”, “the current route”, “the item you found”.

## Tracking boundary

This skill does not own tracking. Local projects may provide a `tracking.md` with current stats, gear, lamps, bosses, route state, and priorities. If present, treat it as local context for the active run. Update it only when the user explicitly asks or local repository instructions require it.

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
