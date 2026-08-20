---
name: darksouls
description: "Use for Dark Souls Remastered builds, mechanics, routes, mods, saves, or spoiler-safe help."
license: AGPL-3.0-or-later
metadata:
  author: anntnzrb

---

# Dark Souls Remastered Companion

Give conservative, spoiler-safe DSR help. The skill is stateless: it does not own a playthrough, silently write tracking files, or mutate saves. Use deterministic local commands for mechanics and catalog calculations; use source-cache/live research for current, route, location, NPC, mod, or contested claims.

## Entry point and operating loop

Run the one public entry point:

```text
uv run --script <skill-dir>/scripts/cli.py ...
```

Use the directory containing this file (normally `C:/Users/Nil/.config/agents/skills/current/darksouls`). Do not require a PATH alias, executable bit, shell profile, or ask the user to install a second CLI.

1. Classify the request: deterministic mechanic/catalog, current/save state, route/guide, achievement, source-backed/current, or mod support
2. Run the narrowest applicable CLI command first. `ds1_core.py` owns mechanics, spoiler gates, source/cache, and guide-search interfaces; `ds1_catalog.py` owns item lookup and deterministic AR/compare helpers; `ds1_save.py` is read-only and must report unsupported categories explicitly; `cli.py` composes these APIs
3. Use `sources status` before source-backed/current claims. Refresh only the needed key when the cache is absent or stale, then use live research when the claim is not covered
4. Treat bundled catalogs and transformed guide chunks as operational lookup aids, not copied encyclopedia prose or proof of save state
5. Apply the spoiler policy before showing names. Answer with the actionable result, then command/source evidence and uncertainty

## Natural-language routing

| Intent | First action | Follow-up and boundary |
|---|---|---|
| Stats, level, current class, or verified save identity | `save auto summary` / `save auto stats` | Use explicit save path if auto-detect fails; only verified fields are facts. |
| Starting class or build direction | `origins`, `softcaps`, `build` | Ask for goals/current stats; compare tradeoffs rather than prescribing. |
| AR, scaling, weapon choice | `weapons`, `calc`, `compare` | Use only known catalog rows; state approximation and upgrade path. |
| Upgrade route/materials | `upgrade`, `farm` | Source-cache/live-check exact locations; keep future names hidden by default. |
| Rings, goods, and farming | `rings`, `goods`, `farm` | Save ownership only when parser resolves it; location prose needs source evidence. |
| “Where next?”, areas, bosses, NPCs | `save auto summary` only for verified fields, then `areas`/`route`/`bosses` | Use generic placeholders until spoilers are permitted; unsupported save progress means unknown. |
| Platinum/achievement cleanup | `achievements`; `guide search` for the local corpus | Separate static checklist from save-backed completion; cite guide/source and warn about spoilers. |
| Exact guide phrase or checklist row | `guide search` then `guide get` | Transform/summarize; never paste raw PDF or imply authority. |
| Latest/current PC, mod, or compatibility question | `sources status` | Refresh/live research and cite the dated source; no unsupported compatibility guarantee. |
| Source-backed or contested mechanic | deterministic CLI first, then `sources explain/status` | Refresh/live-check and distinguish observed fact, source claim, and recommendation. |

## Spoiler policy

Default output MUST omit future proper names. It may include mechanics and names that the user supplied, that appear in an explicitly supplied save/tracking context, or that the user explicitly permits. Without permission, do not reveal future boss/area/NPC/item names, exact locations, quest outcomes, endings, lore/story reveals, or DLC/late-game identities. Use “the next required boss”, “the optional area”, “a key upgrade material”, or “that NPC” instead. `--spoilers` is an explicit opt-in for CLI output; it does not override a user’s stated no-spoiler request.

Mechanics that are normally safe include stats, softcaps, scaling, reinforcement rules, durability, equip load, poise, parry/riposte/backstab, kindling/Estus mechanics, controls, and general combat fundamentals. Even safe mechanics must not smuggle in a future location or quest outcome.

## Evidence and source hierarchy

1. **Observed deterministic output** from the current CLI/kernel for supported mechanics or catalog rows
2. **Validated read-only parser output** for fields whose DSR offsets/IDs are explicitly sourced and tested by the save implementation
3. **Official/primary sources** for product/platform facts and published requirements
4. **Fresh cached/live community sources** for routes, locations, NPC steps, farming, calculators, and current mod status
5. **Local transformed guide chunks** only for targeted walkthrough lookup, with provenance and spoiler warning
6. **Local Dadbod transcript chunks** only for narrowly requested transcript lookup, with provenance and the transcript warning; they are never mechanics/save/parser/route truth

Label claims as observed, source-backed, calculated, or recommendation. If sources disagree, show the disagreement and avoid false precision. Cache metadata is a fetch receipt, not a citation; cite the source URL/source key.

## Mod guidance boundaries

DSR mod advice is PC-native and version-sensitive. Describe loader/tool names only when supported by the registry, distinguish legitimate Steam from other distributions, recommend backups and offline testing, and separate cosmetic/QoL risk from gameplay/save changes. Do not promise online safety, anti-cheat safety, multiplayer compatibility, or support for cracked copies. Do not give instructions that circumvent DRM, platform protections, anti-cheat, or license checks. Current claims require live verification.

## Required follow-up reads

| Need | Read | When |
| --- | --- | --- |
| Exact CLI and save contract | `references/cli-save-contract.md` | Before unfamiliar commands, frame scanning, corpus lookup, source operations, tracking, or save actions |
| Provenance and high-risk boundaries | `REFERENCES.md` | Before source/cache refresh, corpus use, frame extraction, save claims, mods, citations, or resource replacement |
