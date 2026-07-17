# Dark Souls 3 Skill References

This file ranks the sources used by the DS3 companion skill and defines what each source is allowed to support. It is an operator/reference document, not user-facing gameplay advice.

Read this before replacing embedded resources or making provenance-sensitive parser/source claims.

## Source priority

| Rank | Source | Use for | Do not use for | License / provenance |
|---:|---|---|---|---|
| 1 | `alfizari/Dark-Souls-3-Save-Editor-PS4-PC` | DS30000 save layout, read-only event-byte offsets, and boss byte values | Mutation/editing behavior, UI code, unsafely writing saves | MIT; repo: <https://github.com/alfizari/Dark-Souls-3-Save-Editor-PS4-PC> |
| 2 | bundled deterministic kernel | Save parser maps, CLI routing, spoiler gates, stable mechanics, eval fixtures, and conservative inventory ID resolution | User-facing guide prose, exact route/location/quest claims, current mod/tool claims, or any claim beyond the source-backed row purpose | GPL skill resources with per-file provenance below; local data is operational scaffold, not encyclopedia content |
| 3 | The Grand Archives DS3 Cheat Table | Reference-only event flag and `SprjEventFlagMan` bit cross-checks, including tracked bonfire bits | Bulk copying, online cheat guidance, license-sensitive embedded data without transformation/attribution | No license observed; reference-only: <https://github.com/The-Grand-Archives/Dark-Souls-III-CT-TGA> |
| 4 | SoulsMods / Paramdex | PARAM schema names and modding/toolchain concepts, especially `BONFIRE_WARP_PARAM_ST` field semantics | DS30000 save offsets, full gameplay row data, copied datasets unless license is confirmed | License varies/unclear by repo/file; reference URL: <https://raw.githubusercontent.com/soulsmods/Paramdex/master/DS3/Defs/BONFIRE_WARP_PARAM_ST.xml> |
| 5 | SoulsModding event flag references | Event flag semantic cross-checks | Save-byte offsets; event IDs are not DS30000 offsets | Community wiki; DS3 page/license must be rechecked before embedding: <https://soulsmodding.com/doku.php?id=ds3-refmat:event-flag-list> |
| 6 | Wikidot | Secondary stat/mechanics cross-checks | Save state, embedded bulk tables without checking page license/scope | CC BY-SA-style wiki source: <https://darksouls3.wikidot.com/stats> |
| 7 | Fextralife | Live, cited gameplay prose: routes, item locations, broad mechanics, NPCs, farm descriptions | Canonical embedded save/progress/event data; bulk GPL resource imports | Registry treats as CC BY-NC-SA; use live/cited summaries: <https://darksouls3.wiki.fextralife.com/> |
| 8 | DS3 Cheat Sheet | Checklist/platinum cross-checks if repository license covers the specific data | Save-backed ownership/progress | Registry treats as MIT; verify before bulk replacement: <https://zkjellberg.github.io/dark-souls-3-cheat-sheet> |
| 9 | PCGamingWiki | Current PC compatibility/fixes and modding-risk guidance | Gameplay/save/event facts | CC BY-NC-SA: <https://www.pcgamingwiki.com/wiki/Dark_Souls_III> |
| 10 | MugenMonkey / SoulsPlanner | Calculator parity and AR/build sanity checks | Embedded formulas/data unless license is found | No license observed; reference-only: <https://mugenmonkey.com/darksouls3>, <https://soulsplanner.com/darksouls3> |

## Embedded resource provenance

| File | Role | Primary source | Transformation / validation |
|---|---|---|---|
| `resources/event_flags.json` | parser-required boss event-byte offsets | alfizari save editor, cross-checked with TGA/SoulsModding flag semantics | Names normalized to current skill display names; validated against the current local DS30000 save where available |
| `resources/bonfire_flags.json` | parser-required per-bonfire offsets + bits | TGA `SprjEventFlagMan` binary records, mapped into DS30000 save bytes and cross-checked against alfizari-derived masks during construction | Non-bonfire event rows filtered out (`Coiled Sword embed`, `Enable Warp to High Wall`). Reads use `base = event_start - 0x12` and `base + tga_offset + 0x6F` |
| `resources/area_checklists.json` | area-checklist scaffold; spoiler-filtered hints only | local curated data, live wiki/checklist cross-checks as needed | Incomplete by design; missing checklist means unknown, not clear |
| `resources/game_data.json` | mechanic-invariant area graph and totals | local curated data, cross-checked with current save behavior | Only areas with supported checklist/progress data should be added |
| `resources/achievement_checklist.json` | mechanic-invariant achievement category lists | local curated data; DS3 Cheat Sheet/Fextralife/Wikidot are cross-check candidates | Save-backed categories must stay separated from static checklist categories |
| `resources/completion_categories.json` | parser/eval contract for save-backed vs static support | local parser contract | Do not mark gestures/infusions save-backed until offsets are sourced |
| `resources/weapons.json`, `resources/armor.json`, `resources/rings.json`, `resources/goods_magic.json` | thin-catalog inventory ID resolution | local extracted/curated maps | Resolver data is not an authoritative gameplay stat table; unresolved IDs must remain unknown |
| `resources/guides/ds3_plat_guide/ds3-plat-guide.manifest.json` | source/export/hash/schema receipt for the local DS3 platinum guide corpus consumed by `guide` CLI lookup commands | user-provided PSNProfiles PDF export (`ds3-plat-guide.pdf`, not tracked) | Generated by `scripts/preprocess_ds3_plat_guide.py`; records source URL, source PDF filename, hash, processing flags, and non-authoritative/non-save-backed/non-parser-truth constraints |
| `resources/guides/ds3_plat_guide/ds3-plat-guide.chunks.jsonl` | local agent lookup corpus for `guide search` and `guide get` platinum walkthrough routing | user-provided PSNProfiles PDF export (`ds3-plat-guide.pdf`, not tracked) | Generated minimal JSONL chunks (`h`, `k`, `t`) with PDF boilerplate/page numbers/browser glyphs normalized out; for spoiler-heavy local lookup and transformed/cited answers only, not parser truth |

## Replacement policy

- Prefer **licensed, machine-readable, save/parser-specific sources** for embedded facts.
- Keep unlicensed reverse-engineering sources as **reference-only** unless the embedded rows are transformed, attributed, and independently validated.
- Keep Fextralife/PCGamingWiki as **live/cited** references for prose and current guidance; avoid increasing embedded dependency on noncommercial wiki text.
- Do not replace working local resources with broader but lower-quality tables just because they are larger.
- Do not claim save-backed status for categories without sourced offsets. Current unsupported categories include gestures and infusions.
- Prefer live retrieval or fresh cache for exact locations, route steps, NPC quest details, current PC/mod compatibility, and contested gameplay facts.
- Local resource growth is allowed only when the data is required for parser correctness, deterministic CLI computation, spoiler safety, source provenance, or eval repeatability.
- Do not add copied wiki prose, full walkthroughs, full questlines, boss strategy pages, lore descriptions, or bulk item-location text to bundled JSON resources.
- Exception: `resources/guides/ds3_plat_guide/` may contain only the generated processed files `ds3-plat-guide.manifest.json` and `ds3-plat-guide.chunks.jsonl` for **PSNProfiles Dark Souls III - Platinum Walkthrough** because the user explicitly requested a tracked local corpus. The source PDF (`ds3-plat-guide.pdf`) must remain untracked and is ignored by `.gitignore`. The corpus remains non-authoritative, non-save-backed, spoiler-heavy, not relicensable, and not parser truth; consume it through `guide search` / `guide get` for local lookup and transformed/cited answers only, not general embedded source data.
- Cache files are fetch receipts/transports, not canonical data sources; final answers should cite source URLs/source keys, not cache filenames.

## Verification requirements after source/resource changes

Run these commands after changing source, save, or resource files:

```text
uv run --script scripts/cli.py audit
uv run --script scripts/cli.py sources policy
uv run --script scripts/cli.py sources explain alfizari-save-editor
uv run --script scripts/cli.py save auto summary
uv run --script scripts/cli.py save auto bosses
uv run --script scripts/cli.py save auto bonfires
uv run --script scripts/cli.py save auto checklist
uvx ruff check --select E9,F63,F7,F82 scripts/ds3_save.py scripts/cli.py scripts/ds3_core.py scripts/ds3_catalog.py scripts/cli_catalog.py
```

If `save auto` cannot find a local save, run the non-save gates and validate with an explicit `.sl2` path before changing save-backed claims.
