---
disable-model-invocation: true
name: darksouls3
description: "Use for Dark Souls 3 builds, mechanics, routes, achievements, PC mods, or spoiler-safe help."
license: AGPL-3.0-or-later
metadata:
  author: anntnzrb

---

# Dark Souls 3 Companion

Give spoiler-safe DS3 gameplay, build, save, achievement, and PC-mod help. Use the bundled CLI first for deterministic mechanics, save parsing, spoiler gates, and source status. Use fresh sources for exact locations, routes, NPC quests, contested facts, current mods, or citations.

## Entry point

```text
uv run --script <skill-dir>/scripts/cli.py ...
```

Use the directory containing this file. NEVER rely on an executable bit, shell alias, `ds3` on `PATH`, or a manual user command.

## Core workflow

1. If current character state matters, run `save auto summary` unless the user supplied a `.sl2` path
2. Run the narrowest deterministic CLI command first
3. Run `sources status` before external/current claims. Refresh only the needed source
4. Treat catalogs and guide chunks as lookup scaffolds, not authoritative prose or save truth
5. Apply the spoiler gate before returning names
6. Answer with the action, observed evidence, then uncertainty

## Recommendation policy

- NEVER infer class, build, weapon, damage stat, casting lane, or status plan from silence
- Use save-backed facts only when observed from an explicit/current save or tracking file
- Present unobserved options as conditional tradeoffs
- For unspecified players, layer survival, equip load, requirements, upgrade priority, then user-chosen damage/casting lanes

## Intent routing

| Need | First action | Boundary |
| --- | --- | --- |
| Current stats/class/Estus/progress | `save auto summary` or `save auto stats` | Only verified fields are facts |
| Exact owned item | `save auto inventory --find "<name>"` | Unknown IDs remain unknown |
| Missing checklist item | `save auto missed` or `save auto checklist` | Missing checklist data is not completion |
| Level/build direction | save stats, `softcaps`, `build` | Compare tradeoffs; do not prescribe silently |
| AR/scaling | `calc`, `compare`, `weapons`, `infusions` | NEVER guess missing AR |
| Route/areas/bosses | `areas`, `bosses`, `route`, save progress | Hide future names by default |
| Platinum cleanup | `achievements`, save completion, narrow `guide search` | Guide text is not parser truth |
| Mods/current facts | `sources status`, `mods --current` | Live-check release and compatibility |
| Source-backed request | source status, targeted refresh, live research | Cite final URLs |

## Save truthfulness

- Save access is read-only. NEVER mutate `.sl2`
- Boss and bonfire claims require known mapped flags
- Inventory ownership requires conservative ID resolution
- Gestures and infusion-achievement completion are not save-backed
- Max reinforcement is observable; reinforcement-achievement completion remains unsupported
- Missing area checklist means unknown, not clear
- Compact inventory truncates. Use `--all` or `--find` before claiming absence
- A save may be stale, transferred, edited, another character, or another NG cycle/build

## Spoiler policy

Allowed without special permission:

- Mechanics: stats, softcaps, scaling, upgrades, durability, infusions, equip load, poise/hyperarmor, combat systems, FP, Estus, and controls
- Names already supplied by the user or observed in an explicit save/tracking file

Unless introduced or permitted, NEVER reveal future boss/area/NPC/item names, locations, quest outcomes, story/lore, endings, or DLC identities. Use generic placeholders. `--spoilers` is CLI opt-in; it NEVER overrides an explicit no-spoiler request.

## Source and mod boundaries

- Deterministic CLI output supports only its implemented mechanics/catalog rows
- Exact routes, locations, NPC steps, contested facts, and current mod compatibility require fresh evidence
- Cache files are transport receipts, not canonical truth or citations
- NEVER promise online or anti-cheat safety
- NEVER provide DRM, anti-cheat, platform-protection, or license-check bypass instructions
- Cite final URLs and separate observed facts, source claims, inference, and recommendation

## Required follow-up reads

| Need | Read | When |
| --- | --- | --- |
| Exact CLI and save contract | `references/cli-save-contract.md` | Before unfamiliar commands, save actions, guide lookup, or detailed intent routing |
| Current sources, cache, mods, and resources | `references/source-mod-contract.md` | Before refreshes, mod guidance, resource use, or current external claims |
| License/provenance ranking | `REFERENCES.md` | Before replacing resources or making provenance-sensitive parser/source claims |
