# Dark Souls Remastered CLI and save contract

Read this before unfamiliar commands, frame scanning, guide/transcript lookup, source operations, tracking, or save actions.

## CLI contract

All commands have this form:

```text
uv run --script <skill-dir>/scripts/cli.py <command> [args...]
```
### Mechanics, origins, builds, and math

```text
fresh
softcaps
origins [filter]
build [quality|strength|dexterity|sorcerer|sorcery|pyromancer|cleric|miracle|dragon] [--level N]
soul-cost <current-level> <target-level>
equip-load [--endurance N] [--havels | --favor]
```

Use these for stat breakpoints, starting-class tradeoffs, target-stat sketches, level-cost math, and roll/equip-load calculations. A build is a conditional example, not a prescription for an unspecified player. Do not invent a formula, breakpoint, class, or result absent from deterministic output; label approximations.
Equip-load roll boundaries are inclusive in the CLI: fast roll at or below 25%, mid roll at or below 50%, and fat roll at or below 100% of maximum load. `--havels` and `--favor` cannot be combined.

### Weapons, upgrades, and catalog lookup

```text
weapons [<name>] [--limit N] [--json] [--spoilers]
calc "<weapon>" <str> <dex> [--int N] [--fth N] [--json]
compare "<weapon A>" "<weapon B>" [--str N --dex N --int N --fth N] [--json]
upgrade <level> [--type normal|unique|dragon]
rings [<name>] [--limit N] [--json] [--spoilers]
goods [<name>] [--limit N] [--json] [--spoilers]
```
Catalog results are deterministic only for rows present in the bundled resources. Without `--spoilers`, catalog output must not reveal future item names or locations beyond a name the user supplied; use generic redaction where required. `--json` preserves the command's machine-readable schema while applying the same spoiler gate. `calc`/`compare` produce approximate AR for known rows; they must say when a weapon or path is unknown and never extrapolate AR from a similarly named item. Exact acquisition locations are separate source-backed claims and may be spoiler-filtered.

### Local DSR animation-frame scanner

```text
frames --install PATH [QUERY] [--kind all|weapon|item] [--limit N] [--json] [--spoilers]
```

`--install PATH` is required and must be an explicit local DSR installation path. The scanner is read-only: it must never write the installation, use a Steam/default/environment fallback, create a cache, or retain output files. Extracted frame JSON, game assets, names/parameter tables, raw payload bytes, and absolute local paths are not bundled or retained; output exists only in the current response. `--json` uses schema `dsr-frame-scan.v1`.

JSON views expose `schema_version`, `frame_rate`, `summary`, `counts`, and `records`; selected views may add `spoilers`, `kind`, and `query`. The `item` kind means equipped goods, not spells. Without a query or spoiler opt-in, `records` is empty.

With no query and no `--spoilers`, return summary/counts only. A query or explicit `--spoilers` opt-in may reveal selected names and timing; the normal skill spoiler policy still applies, and `--spoilers` never overrides a user’s explicit no-spoiler request.

The scanner covers canonical visible base weapon roots excluding shields and ammunition, plus equipped goods with a real nonzero use animation; sentinel animation value `254` is excluded. Spells, spellcasting animations, armor, rings, shields, ammunition, and other equipment-specific timing are out of scope. Player-facing weapon move labels remain unresolved.

Label frame evidence explicitly: `exact` preserves the local float32 timing windows and derived 30-FPS frames. Weapon timing is exact only when Event Type `1` `BehaviorJudgeID` joins a selector-matched `BehaviorParam_PC` row. Goods use-animation variation is `representative` while candidates remain unresolved; it may be labeled exact only when a sole local candidate exists. Exact extraction does not turn an unresolved move label into a named move.

### Progression, areas, bosses, farming, and achievements

```text
areas [--spoilers]
bosses [--area <area>] [--spoilers]
route [--defeated <id,id,...>] [--spoilers]
farm [souls|titanite|humanity|moss] [--spoilers]
estus [max|shards|souls|kindling]
achievements [--missable] [--spoilers]
```

The default is a safe overview. Pass `--spoilers` only after the user permits future names or names are already in context. `--havels` and `--favor` are mutually exclusive equip-load choices; do not combine them. Exact routes, item locations, NPC steps, farming spots, and missable cleanup require the source-cache/live path; do not convert an incomplete checklist into a claim that an area is clear.

### Local platinum-guide corpus

```text
guide info [--spoilers]
guide kinds [--spoilers]
guide headings [--spoilers]
guide search <query...> [--kind <kind>] [--heading <text>] [--limit N] [--json] [--spoilers]
guide get <row-number> [--json] [--spoilers]
```

These commands search only the transformed, user-provided PSNProfiles DSR platinum-guide corpus at:

```text
resources/guides/dsr_plat_guide/dsr-plat-guide.manifest.json
resources/guides/dsr_plat_guide/dsr-plat-guide.chunks.jsonl
```

Raw chunk rows use `{ "h": string[], "k": string, "t": string }`; search results add a row number/snippet for lookup. Guide output is redacted by default and `--json` changes representation only, not the spoiler gate. Every guide answer must carry this warning:

> Local guide lookup: transformed from the user-provided PSNProfiles platinum-guide PDF; spoiler-heavy, non-authoritative, not save/parser truth, and not permission to republish the PDF or its text.

The manifest reports `title`, `authors`, `url`, source-PDF identity/hash, transformation metadata, and provenance/usage constraints; do not substitute undocumented keys such as `author`, `updated`, or `source`. The source PDF is not tracked or bundled, and raw PDF text must never be copied into the repository. Summarize only the minimum text needed. The corpus is produced by `uv run --script scripts/preprocess_dsr_plat_guide.py [pdf] [outdir]`; keep only the manifest/chunks outputs.

### Local DSR Dadbod transcript corpus

```text
transcript [info|list|search [QUERY ...]|get VIDEO_INDEX CHUNK_INDEX] [--video-index N] [--limit N] [--json] [--spoilers]
```

These commands search only the separate transformed corpus at:

```text
resources/guides/dsr_dadbod_transcripts/dsr-dadbod-transcripts.manifest.json
resources/guides/dsr_dadbod_transcripts/dsr-dadbod-transcripts.chunks.jsonl
```

The corpus contains 30 user-provided Dadbod video transcripts. It is a local, deterministic transformation of English `en-orig` automatic captions (source SHA-256 `99bfdb067225d0290c66520ec468f04a50643d541b8a9c37344c274eadbfd5f3`). Rights are unknown and `copyable` is false: retain only the transformed manifest/chunks and do not redistribute the source JSON or long transcript text. Preserve the exact source video IDs, URLs, caption tracks, and cue counts recorded in the manifest/chunks; do not invent titles or timestamps.

Transcript text is spoiler-heavy, non-authoritative, potentially inaccurate, and **never mechanics, save, parser, or route truth**. Every transcript result must carry this warning:

> Local Dadbod transcript lookup: user-provided English automatic captions; spoiler-heavy, non-authoritative, potentially inaccurate, rights unknown/copyable=false, and never mechanics/save/parser/route truth.

Output is redacted by default: without `--spoilers`, `transcript info`/`list` expose metadata without titles or names, and `transcript search`/`get` expose no transcript text, identifiers, URLs, headings, or names. `--json` changes representation only and never bypasses the spoiler gate. To reveal transcript chunks, `transcript search` requires a non-empty query together with `--spoilers`; queryless search is summary-only to prevent a dump. `get` uses zero-based video/chunk indexes and rejects out-of-range indexes. Keep this corpus separate from the PSNProfiles guide corpus and from mechanics/catalog/save APIs.


### Sources, mods, and audit

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

`sources refresh` is for registered remote HTTP(S) sources; local registry entries are introspection-only and must not be fetched. Use the source registry/cache and live research for current loader/tool information; this is discovery and risk guidance, not a compatibility guarantee.

### Read-only saves

```text
save [PATH=auto] [ACTION=summary|stats|name|level|currency|inventory|owned|bosses|bonfires|progress|completion|achievements|checklist|missed] [--spoilers] [--json]
```

`summary`, `stats`, `name`, and `level` may report validated DSR container/slot identity, character name, level, class, and stats when AES/MD5/name-copy/range checks pass. The `achievements` action returns the static checklist plus an explicitly unsupported save-backed unlock state; it does not read platform ownership. `currency`, `inventory`, `owned`, `bosses`, `bonfires`, `progress`, `completion`, `checklist`, and `missed` remain explicit unsupported results until their DSR mappings are validated. Unsupported JSON requests must remain JSON objects; never turn them into prose.

Default save output must redact character/progression names, locations, bosses, bonfires, and requirements unless the user has permitted spoilers; `--json` preserves the schema while applying the same gate. `save auto` checks only the documented Windows DSR location and selects the newest candidate that passes full validation and contains a nonempty valid character slot; malformed, empty, or unreadable newer files are skipped. Use an explicit `.sl2` path for backups or non-default installs.

Save support is read-only: never write, repair, decrypt, convert, or recommend an editor. Unknown IDs, unvalidated offsets, and unsupported categories remain unknown—not zero, absent, or complete. Do not advertise exact quest state, every key item, gestures, covenant rank, bonfire flags, inventory ownership, or achievement completion as save-backed. A static checklist is not save state; a save may be stale, transferred, edited, a different character, or a different game build.
