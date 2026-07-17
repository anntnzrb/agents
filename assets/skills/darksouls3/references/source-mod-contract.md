# Dark Souls 3 source and mod contract

Read this for current claims, cache/source operations, mods, resource replacement, or provenance-sensitive work.

## Source and evidence rules

- Use deterministic CLI output for supported mechanics.
- Use validated read-only parser output only for mapped save fields.
- Use live research or a fresh targeted source cache for exact locations, route steps, NPC quests, contested facts, and mod compatibility.
- Bundled catalogs are operational scaffolds, not authoritative guide prose.
- Cache files are transport receipts, not canonical truth or citations.
- Final source-backed answers cite URLs and separate observed facts from inference.
- Keep live queries spoiler-safe unless the user permits spoilers.

Source ranking, licenses, copyability, and embedded-data provenance live in `../REFERENCES.md`. Read it before replacing resources.

## PC mod boundaries

- Mod Engine 1: passive `dinput8.dll` proxy; works with cracked and legitimate copies; uses `mod/`.
- Mod Engine 3 / ME3: injection launcher; legitimate Steam only; can collide with modified executables.
- Proper PC Experience: passive `d3d11.dll` proxy for FPS, refresh, FoV, and intro fixes.
- FromStutterFix: `dinput8` chain-loaded frame-pacing fix.
- Blue Sentinel: online protection, overlay, and backups; legitimate Steam only.
- Camera Fix: ME3-native camera auto-center fix.

Run `mods --current` first. MUST live-check release/version and compatibility claims. NEVER promise online or anti-cheat safety. NEVER provide DRM, anti-cheat, platform-protection, or license-check bypass instructions.

## Resource roles

- Parser-required: `resources/event_flags.json`, `resources/bonfire_flags.json`.
- Mechanic-invariant: `resources/game_data.json`, `resources/achievement_checklist.json`, `resources/completion_categories.json`.
- Thin catalogs: `resources/weapons.json`, `resources/armor.json`, `resources/rings.json`, `resources/goods_magic.json`.
- Incomplete scaffold: `resources/area_checklists.json`; missing data means unknown.
- Provenance/source policy: `resources/source_registry.json`.
- Local guide corpus: `resources/guides/ds3_plat_guide/`; source PDF is not tracked.
- Eval fixture: `evals/evals.json`.

Thin catalogs resolve inventory IDs only. NEVER treat them as complete gameplay-stat, route, or location tables.

## Runtime source registry

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
alfizari-save-editor  https://github.com/alfizari/Dark-Souls-3-Save-Editor-PS4-PC
tga-ct                 https://github.com/The-Grand-Archives/Dark-Souls-III-CT-TGA
paramdex-bonfire      https://raw.githubusercontent.com/soulsmods/Paramdex/master/DS3/Defs/BONFIRE_WARP_PARAM_ST.xml
soulsmodding-flags    https://soulsmodding.com/doku.php?id=ds3-refmat:event-flag-list
modengine1            https://github.com/katalash/ModEngine
me3                   https://github.com/garyttierney/me3
```

Use:

```text
sources list
sources status
sources policy
sources explain <source-key>
sources refresh [source-key ...] [--force]
```

The cache defaults to `~/.cache/darksouls3-companion`; override with `DS3_CACHE_DIR=<path>`. Entries record fetch timestamp `ts`, raw `content`, and `meta.url`/`meta.sha256`; staleness uses a 24-hour TTL. Runtime remains stateless for playthrough progress.

Use `--force` only when bypassing the normal freshness window is material. Local/introspection-only sources MUST NOT be fetched.

## Live fallback

Use web/Brave/Reddit/read URLs when CLI coverage is missing, cache is stale, or the claim is current, contested, route/location/NPC-specific, or citation-sensitive. Cite URLs in the final answer and label inference.
