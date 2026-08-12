# Dark Souls Remastered CLI/save contract

Read before unfamiliar commands, frame scanning, guide/transcript lookup, source operations, tracking, or saves.

## CLI

All commands:

```text
uv run --script <skill-dir>/scripts/cli.py <command> [args...]
```

### Mechanics, builds, math

```text
fresh
softcaps
origins [filter]
build [quality|strength|dexterity|sorcerer|sorcery|pyromancer|cleric|miracle|dragon] [--level N]
soul-cost <current-level> <target-level>
equip-load [--endurance N] [--havels | --favor]
```

Use for stat breakpoints, starting-class tradeoffs, target-stat sketches, level-cost math, and roll/equip-load calculations. Builds are conditional examples, not prescriptions for unspecified players. Do not invent formulas, breakpoints, classes, or results absent from deterministic output; label approximations. Roll boundaries are inclusive: fast ≤25%, mid ≤50%, fat ≤100% maximum load. `--havels` and `--favor` are mutually exclusive.

### Weapons, upgrades, catalogs

```text
weapons [<name>] [--limit N] [--json] [--spoilers]
calc "<weapon>" <str> <dex> [--int N] [--fth N] [--json]
compare "<weapon A>" "<weapon B>" [--str N --dex N --int N --fth N] [--json]
upgrade <level> [--type normal|unique|dragon]
rings [<name>] [--limit N] [--json] [--spoilers]
goods [<name>] [--limit N] [--json] [--spoilers]
```

Catalog results are deterministic only for rows in bundled resources. Without `--spoilers`, do not reveal future item names/locations beyond a user-supplied name; generically redact as needed. `--json` preserves the schema but not a spoiler bypass. `calc`/`compare` give approximate AR only for known rows; identify unknown weapons/paths and never extrapolate from similarly named items. Exact acquisition locations are separate source-backed, spoiler-filterable claims.

### Local animation-frame scanner

```text
frames --install PATH [QUERY] [--kind all|weapon|item] [--limit N] [--json] [--spoilers]
```

`--install PATH` MUST be an explicit local DSR installation path. Scanner read-only: NEVER write the installation, use Steam/default/environment fallback, create a cache, or retain output files. Do not bundle/retain extracted frame JSON, assets, names/parameter tables, raw payload bytes, or absolute local paths; output exists only in the current response. `--json` schema `dsr-frame-scan.v1`.

JSON views expose `schema_version`, `frame_rate`, `summary`, `counts`, and `records`; selected views may add `spoilers`, `kind`, and `query`. `item` means equipped goods, not spells. No query AND no spoiler opt-in → `records` empty and summary/counts only. A query or explicit `--spoilers` may reveal selected names/timing; normal spoiler policy still applies, and `--spoilers` never overrides an explicit no-spoiler request.

Coverage: canonical visible base weapon roots excluding shields/ammunition; equipped goods with a real nonzero use animation; sentinel animation `254` excluded. Out of scope: spells, spellcasting animations, armor, rings, shields, ammunition, and other equipment-specific timing. Player-facing weapon move labels unresolved.

Evidence labels: `exact` preserves local float32 timing windows and derived 30-FPS frames. Weapon timing is exact only when Event Type `1` `BehaviorJudgeID` joins a selector-matched `BehaviorParam_PC` row. Goods use-animation variation is `representative` while candidates unresolved; `exact` only with a sole local candidate. Exact extraction does not name an unresolved move.

### Progression, areas, bosses, farming, achievements

```text
areas [--spoilers]
bosses [--area <area>] [--spoilers]
route [--defeated <id,id,...>] [--spoilers]
farm [souls|titanite|humanity|moss] [--spoilers]
estus [max|shards|souls|kindling]
achievements [--missable] [--spoilers]
```

Default output is a safe overview. Pass `--spoilers` only after permission for future names or when names are already in context; never override an explicit no-spoiler request. Exact routes, item locations, NPC steps, farming spots, and missable cleanup require source-cache/live path. An incomplete checklist is not proof an area is clear. (`--havels`/`--favor` remain mutually exclusive.)

### Local platinum-guide corpus

```text
guide info [--spoilers]
guide kinds [--spoilers]
guide headings [--spoilers]
guide search <query...> [--kind <kind>] [--heading <text>] [--limit N] [--json] [--spoilers]
guide get <row-number> [--json] [--spoilers]
```

Search only the transformed, user-provided PSNProfiles DSR platinum-guide corpus:

```text
resources/guides/dsr_plat_guide/dsr-plat-guide.manifest.json
resources/guides/dsr_plat_guide/dsr-plat-guide.chunks.jsonl
```

Raw rows:

```text
{ "h": string[], "k": string, "t": string }
```

Search results add row number/snippet. Output is redacted by default; `--json` changes representation, not the spoiler gate. Every guide answer MUST carry:

> Local guide lookup: transformed from the user-provided PSNProfiles platinum-guide PDF; spoiler-heavy, non-authoritative, not save/parser truth, and not permission to republish the PDF or its text.

Manifest keys include `title`, `authors`, `url`, source-PDF identity/hash, transformation metadata, and provenance/usage constraints. Do not substitute undocumented `author`, `updated`, or `source`. Source PDF is not tracked/bundled; NEVER copy raw PDF text into the repository. Summarize the minimum needed. Corpus generation:

```text
uv run --script scripts/preprocess_dsr_plat_guide.py [pdf] [outdir]
```

Keep only manifest/chunks outputs.

### Local DSR Dadbod transcript corpus

```text
transcript [info|list|search [QUERY ...]|get VIDEO_INDEX CHUNK_INDEX] [--video-index N] [--limit N] [--json] [--spoilers]
```

Search only this separate corpus:

```text
resources/guides/dsr_dadbod_transcripts/dsr-dadbod-transcripts.manifest.json
resources/guides/dsr_dadbod_transcripts/dsr-dadbod-transcripts.chunks.jsonl
```

It contains 30 user-provided Dadbod video transcripts: deterministic transformation of English `en-orig` automatic captions, source SHA-256 `99bfdb067225d0290c66520ec468f04a50643d541b8a9c37344c274eadbfd5f3`. Rights unknown; `copyable` false. Retain only transformed manifest/chunks; do not redistribute source JSON or long transcript text. Preserve exact source video IDs, URLs, caption tracks, and cue counts in manifest/chunks; never invent titles/timestamps.

Transcript text is spoiler-heavy, non-authoritative, potentially inaccurate, and NEVER mechanics, save, parser, or route truth. Every result MUST carry:

> Local Dadbod transcript lookup: user-provided English automatic captions; spoiler-heavy, non-authoritative, potentially inaccurate, rights unknown/copyable=false, and never mechanics/save/parser/route truth.

Default redaction: without `--spoilers`, `info`/`list` expose metadata without titles/names; `search`/`get` expose no transcript text, identifiers, URLs, headings, or names. `--json` never bypasses this gate. Revealing chunks requires `transcript search` with a non-empty query AND `--spoilers`; queryless search is summary-only. `get` uses zero-based video/chunk indexes and rejects out-of-range indexes. Keep this corpus separate from guide, mechanics/catalog, and save APIs.

### Sources, mods, audit

```text
sources list
sources status
sources policy
sources explain <source-key>
sources refresh [<source-key> ...] [--force]
audit
track [section] --path <tracking-json>
recommend --path <tracking-json>
```

`sources refresh` applies only to registered remote HTTP(S) sources; local registry entries are introspection-only and MUST NOT be fetched. Use source registry/cache and live research for current loader/tool information; this is discovery/risk guidance, not a compatibility guarantee.

### Read-only saves

```text
save [PATH=auto] [ACTION=summary|stats|name|level|currency|inventory|owned|bosses|bonfires|progress|completion|achievements|checklist|missed] [--spoilers] [--json]
```

`summary`, `stats`, `name`, `level` may report validated DSR container/slot identity, character name, level, class, and stats only when AES/MD5/name-copy/range checks pass. `achievements` returns the static checklist plus explicitly unsupported save-backed unlock state; it does not read platform ownership. `currency`, `inventory`, `owned`, `bosses`, `bonfires`, `progress`, `completion`, `checklist`, and `missed` remain explicitly unsupported until DSR mappings are validated. Unsupported JSON requests remain JSON objects, never prose.

Default save output redacts character/progression names, locations, bosses, bonfires, and requirements unless spoiler permission exists; `--json` preserves schema and gate. `save auto` checks only the documented Windows DSR location and selects the newest fully validated candidate containing a nonempty valid character slot; skips malformed, empty, or unreadable newer files. Use an explicit `.sl2` path for backups/non-default installs.

Save support is read-only: NEVER write, repair, decrypt, convert, or recommend an editor. Unknown IDs, unvalidated offsets, and unsupported categories remain unknown—not zero, absent, or complete. Do not claim save-backed exact quest state, every key item, gestures, covenant rank, bonfire flags, inventory ownership, or achievement completion. A static checklist is not save state; saves may be stale, transferred, edited, for another character, or for another game build.
