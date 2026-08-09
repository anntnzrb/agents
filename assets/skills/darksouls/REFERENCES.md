# Dark Souls Remastered Skill References

This file is loaded when a response needs provenance, currentness, guide-corpus handling, frame-extraction, or mod/save boundaries. It is an operator reference, not a walkthrough. The public contract is in `SKILL.md`.

## Source hierarchy

Use the narrowest source that can support the claim:

1. **Observed deterministic kernel/catalog/frame-scanner output** — stable formulas, explicit catalog rows, and read-only local frame extraction. Treat unknowns as unknowns
2. **Validated DSR read-only save mapping** — only fields that `ds1_save.py` identifies as supported from a defensible source and validation record
3. **Official or primary sources** — product/platform facts, official manuals, published patch or support statements, and first-party release information
4. **Fresh community references** — mechanics cross-checks, exact route/location/NPC/farming prose, calculators, mod releases, and compatibility pages. Cite the URL and check currentness for time-sensitive claims
5. **Local transformed PSNProfiles guide corpus** — targeted platinum-walkthrough lookup only; spoiler-heavy, non-authoritative, non-save-backed, and not a substitute for source validation

When sources disagree, state which source says what, prefer the higher-ranked source for its allowed purpose, and avoid a confident synthesis that the evidence does not justify.

## Live cache policy

`source_registry.json` is the allowlist and provenance receipt for source use. `sources status` is the first check for any “current”, “latest”, compatibility, or citation request. Use `sources refresh <source-key>` only for the needed remote HTTP(S) source; local `local://` entries are introspection-only and are never fetched. Cache records are keyed by source identity and URL, so changing a registered URL cannot reuse stale content under the same key. Use `--force` only when bypassing the normal freshness window is material. A cache is transport/fetch metadata, not canonical data. Final answers cite the registered URL/source key, not a cache filename.

- Stable mechanics: prefer CLI output; live-check only when the local kernel is missing or contested
- Exact locations, routes, quest steps, farming routes, and checklist details: live-check or use a precisely scoped guide row after spoiler permission
- PC/mod versions, loaders, compatibility, online risk, and platform behavior: always current-check before asserting
- Source pages may contain late-game names even when the user asked for no spoilers. Search and summarize with the spoiler filter; never paste raw page text

## Allowed-use and copyability rules

Each registry entry has `allowed_use`, `not_allowed_for`, `license`, `machine_readable`, and `copyable` fields. “Copyable” means only that a transformation may be embedded within the stated license/scope; it does **not** authorize copying unrelated page prose or bulk tables. For `copyable: false`, use the source as a live/reference citation and write original summaries. A license marked unknown/varies requires file- or repository-level review before any embedding.

Do not embed:

- copied wiki prose, boss strategies, NPC questlines, lore, or broad location walkthroughs;
- untransformed calculator tables, reverse-engineered save layouts, or mod binaries;
- raw text from the user-provided PSNProfiles PDF;
- save offsets or completion categories not validated for DSR

The bundled deterministic resources are a narrow operational scaffold. Their presence is not evidence that every item/location or progression fact is covered.

## Bundled resources and provenance

| Resource | Role | Provenance and constraint |
|---|---|---|
| `resources/game_data.json` | mechanic/route metadata used by CLI gates | Local curated contract; keep spoiler-safe labels and incomplete areas explicit. |
| `resources/achievement_checklist.json` | static achievement/platinum checklist | Curated and cross-checked; not proof of ownership or completion. |
| `resources/weapons.json` | thin name/ID/catalog map | Use for known catalog lookup and conservative inventory resolution only; not a full authoritative parameter dump. |
| `resources/rings.json` | thin ring name/ID map | Same resolver boundary; unresolved IDs stay unknown. |
| `resources/goods_magic.json` | thin goods/spell/miracle/pyromancy map | Same resolver boundary; do not infer acquisition location or ownership from a name match alone. |
| `resources/save_support.json` | parser evidence receipt | Records the DSRSave MIT provenance and the narrow container/name/stats/level/class support boundary; it must not imply inventory, boss, bonfire, quest, or achievement offsets. |
| `resources/source_registry.json` | source allowlist and policy metadata | Keep URLs, license/copyability, allowed uses, prohibited uses, and risk notes truthful. |
| `scripts/ds1_frames.py` | code-only local DSR frame scanner | Reads an explicitly supplied install at runtime; no bundled or retained frame JSON, game assets, extracted names/parameter tables, raw payload bytes, or absolute paths. |
| `resources/guides/dsr_plat_guide/dsr-plat-guide.manifest.json` | corpus receipt | Records user-provided PDF provenance, source URL/name, hash/processing/schema, and non-authoritative constraints. The PDF itself is not tracked. |
| `resources/guides/dsr_plat_guide/dsr-plat-guide.chunks.jsonl` | local search index | Generated transformed rows only (`h`, `k`, `t`); no raw PDF or copied page dump. |
| `resources/guides/dsr_dadbod_transcripts/dsr-dadbod-transcripts.manifest.json` | transcript corpus receipt | Records the exact source hash, 30 video IDs/URLs/tracks/cue counts, transformation/schema, and rights boundary; source JSON is not retained. |
| `resources/guides/dsr_dadbod_transcripts/dsr-dadbod-transcripts.chunks.jsonl` | local transcript search index | Deterministically transformed per-video word chunks only; no cross-video chunks, invented titles/timestamps, or raw transcript dump. |

Catalog output is spoiler-gated at the CLI boundary. A canonical name in a bundled row is not permission to expose a future item or location; default output should redact future names, and `--json` changes representation without bypassing the gate.

## Local DSR frame scanner

`scripts/ds1_frames.py` exposes `scan_install(install: str | Path)`, `select_frame_records(scan, *, kind, query, spoilers, limit)`, and `to_jsonable(view)`, plus `FrameScannerError`, `FrameInstallError`, `FrameFormatError`, and `FrameQueryError`. Its public CLI contract is:

```text
frames --install PATH [QUERY] [--kind all|weapon|item] [--limit N] [--json] [--spoilers]
```

The install path is mandatory and explicit. The scanner is read-only and must not write the install, fall back to Steam/default/environment discovery, create caches or output files, or retain extracted data after the response. It is code-only: do not bundle or retain frame JSON, game assets, extracted names/parameter tables, raw payload bytes, or absolute local paths. JSON output uses schema `dsr-frame-scan.v1`. No query without `--spoilers` returns summary/counts only; queries and explicit spoiler opt-in may reveal selected names and timing, subject to the skill’s no-spoiler policy.

JSON views use `schema_version`, `frame_rate`, `summary`, `counts`, and `records`; selected views may additionally carry `spoilers`, `kind`, and `query`. The `item` kind means equipped goods, not spells. Without a query or spoiler opt-in, `records` remains empty and only summary/counts are exposed.

The extraction scope is canonical visible base weapon roots (excluding shields and ammunition) and equipped goods with a real nonzero use animation (sentinel `254` excluded). Spells, spellcasting animations, armor, rings, shields, ammunition, and other equipment-specific timing are out of scope. Weapon player-facing move labels remain unresolved.

Evidence labels must distinguish `exact` from `representative`. `exact` preserves local float32 timing windows and derived 30-FPS frames; weapon timing receives this label only when Event Type `1` `BehaviorJudgeID` joins a selector-matched `BehaviorParam_PC` row. Goods use-animation timing is `representative` when variation is unresolved and may be `exact` only when a sole local candidate exists. Exact timing extraction does not establish a named player move.

The scanner’s source is local proprietary/user-only installation data, registered as `local-dsr-frame-extraction`. It is non-copyable provenance: use only to produce a transient, selected summary from the user’s explicit install, never as permission to redistribute game data or reconstructed parameter tables.

## Guide-corpus provenance and warning

The corpus is derived from a user-provided PSNProfiles **Dark Souls Remastered platinum guide PDF**. The input PDF is intentionally not stored or tracked. Run `uv run --script scripts/preprocess_dsr_plat_guide.py [pdf] [outdir]`; the script carries inline PyMuPDF dependency metadata and emits only the manifest and JSONL chunks named above. The chunks are a local search aid, not a general reference dataset.

The manifest’s authoritative metadata uses `title`, `authors`, `url`, `source_pdf_name`, `source_pdf_sha256`, `source_type`, `source_pdf_tracked`, `copyable`, `usage`, `constraints`, `provenance`, `extraction`, and `preprocessing`. Do not rely on undocumented aliases such as `author`, `updated`, or `source`.

Every guide CLI result and every user-facing answer based on it must carry or be accompanied by this warning:

> Local guide lookup: transformed from the user-provided PSNProfiles platinum-guide PDF; spoiler-heavy, non-authoritative, not save/parser truth, and not permission to republish the PDF or its text.

Guide output is spoiler-redacted by default; `--json` changes representation only and does not bypass the gate. Use `guide search` to find a narrow heading/term, then `guide get` for a specific row. Summarize the minimum relevant content, preserve uncertainty, and apply the user’s spoiler setting. Never quote long passages or regenerate the PDF from chunks. Do not claim that a guide row proves the user has or has not obtained an item.

## Dadbod transcript provenance and warning

The separate corpus is derived from the user-provided `dsr-dadbod-transcripts.json` source (30 videos, English `en-orig` automatic captions; source SHA-256 `99bfdb067225d0290c66520ec468f04a50643d541b8a9c37344c274eadbfd5f3`). The source JSON is not bundled or deleted in this phase. Rights are unknown and `copyable` is false. Retained artifacts are only the deterministic manifest and JSONL chunks under `resources/guides/dsr_dadbod_transcripts/`.

Transformation is NFKC normalization plus whitespace collapse, split only at word boundaries into per-video chunks targeting approximately 1400 characters (maximum 1800); chunks never cross video boundaries and reconstruct normalized text with single spaces. Preserve exact source video IDs, URLs, caption tracks, and cue counts. Do not invent video titles or timestamps.

Every transcript CLI result and every user-facing answer based on it must carry or be accompanied by this warning:

> Local Dadbod transcript lookup: user-provided English automatic captions; spoiler-heavy, non-authoritative, potentially inaccurate, rights unknown/copyable=false, and never mechanics/save/parser/route truth.

Transcript output is spoiler-redacted by default. `--json` never bypasses redaction; a queryless search is summary-only, while revealing transcript chunks requires both a non-empty query and `--spoilers`; get indexes are bounds-checked. Keep transcript evidence separate from the PSNProfiles guide corpus, deterministic mechanics/catalog output, and read-only save parser output.

## Save-support truthfulness

`ds1_save.py` is read-only and its current evidence is the MIT `Piroshkiv/DSRSave` project, recorded in `resources/save_support.json`. It may report only verified container/slot integrity plus name, stats, level, and class when AES/MD5/name-copy/range checks pass. The `achievements` action may return the static checklist, but its `save_backed` unlock state is explicitly unsupported and platform-account based. Inventory, currency, progress, bosses, bonfires, completion, and achievement ownership remain unsupported until DSR mappings are independently validated. Do not assume DS3 save structures, event bytes, bonfire flags, inventory layouts, achievement offsets, or parser coverage transfer to DSR.

- Unknown raw IDs are not owned items
- An absent mapping is not a defeated boss, missing item, or incomplete achievement
- Static checklist totals are not save-backed completion
- Auto-detection considers only the documented DSR Windows path and skips malformed, empty, unreadable, or invalid candidates before selecting the newest fully validated nonempty save
- Save state can be stale, transferred, edited, a different character, or a different executable/build
- Read operations must not write, repair, decrypt, re-encrypt, or offer mutation instructions

The CLI applies its spoiler gate to default save output and keeps unsupported JSON actions machine-readable; `--spoilers` is explicit opt-in. When save output and user recollection conflict, report the observed file result, identify the parser’s supported scope, and ask for an explicit path or corroborating evidence rather than “fixing” the save.

## Mod and platform boundaries

Use official product/platform references for supported releases and published notices. Use community mod repositories and compatibility wikis only for the allowed discovery/currentness scope in the registry. Check release pages and dates before saying a tool is current. Do not infer compatibility between Prepare to Die Edition, Remastered, console, Steam, Proton, or a particular executable without evidence. Do not promise anti-cheat or online safety, and do not provide DRM, anti-cheat, platform-protection, save-editing, or cracked-copy bypass guidance.

## Citation style

For user-facing source-backed answers, identify the source key and link the registered URL. Distinguish:

- **Observed:** directly returned by the deterministic CLI or validated save parser
- **Calculated:** derived from stated inputs and deterministic helper output
- **Source-backed:** supported by a cited official/community page or a specific local guide row
- **Recommendation:** judgment/tradeoff, not a fact

If a claim is an inference, label it `[INFERENCE]`. Include a checked date for current claims where practical. Keep citations proportional; do not expose internal cache paths or unintroduced spoiler names.

## Resource contract

```text
darksouls/
  SKILL.md
  REFERENCES.md
  scripts/
    cli.py
    ds1_core.py
    ds1_catalog.py
    ds1_save.py
    ds1_frames.py
  resources/
    game_data.json
    source_registry.json
    weapons.json
    rings.json
    goods_magic.json
    achievement_checklist.json
    save_support.json
    guides/dsr_plat_guide/
      dsr-plat-guide.manifest.json
      dsr-plat-guide.chunks.jsonl
    guides/dsr_dadbod_transcripts/
      dsr-dadbod-transcripts.manifest.json
      dsr-dadbod-transcripts.chunks.jsonl
  evals/evals.json
```

`game_data.json` and the checklist are stable, curated contracts; catalogs are intentionally thin and conservative. `ds1_frames.py` is a code-only, read-only scanner: it consumes an explicitly supplied install at runtime and does not bundle or retain frame JSON, game assets, extracted names/parameter tables, raw payload bytes, or absolute paths. Read `REFERENCES.md` when a source, cache, guide-corpus, frame-scanner, or mod boundary matters. Do not add raw PDF text, copied wiki prose, broad location tables, or unlicensed datasets.
