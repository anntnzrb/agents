---
name: valo
description: "Use when checking Valorant meta: tier list, win or pick rates, patch notes, map balance, or agents to abuse or avoid."
license: AGPL-3.0-or-later
metadata:
  author: anntnzrb
---

# Valorant meta: live stats, never embedded

Live Valorant meta data from valking.gg. Nothing is embedded in this skill:
every answer is fetched fresh at runtime, so the data can never go stale by
construction. Sources are JS-rendered Next.js pages; plain curl gets empty
shells, so fetching goes through the sibling firecrawl skill (scrape to
markdown) and parsing works on the markdown.

## Public entrypoint

```text
uv run --script <skill-dir>/scripts/cli.py <command>
```

Every command prints exactly one JSON object to stdout: `ok:true` with data,
or `ok:false` with a stable uppercase error code under `error.code`.

## Common calls

- `agents`: the tier list table. Per agent: rank, name, role, winrate,
  wr_delta_7d, pickrate, pr_delta_7d, kda, tier, plus the patch version.
- `patch`: latest patch highlights. Version, release date, changes tagged
  BUFF/NERF/NEUTRAL/REWORK/NEW with target and text, detail-page change
  counts, biggest movers, and the official playvalorant.com link.
- `maps`: per-map attack/defense round win percentages. The maps page renders
  one map at a time and the competitive pool rotates, so coverage is
  uncertain; the output carries a note saying so.
- `snapshot`: the composed answer for "what do I play this patch". Fetches
  agents, patches, and maps concurrently, then derives abuse picks (meta and
  niche buckets), avoid picks, biggest movers, and patch context. Derivation
  thresholds are embedded in the output so the user can judge them.
- `doctor`: probe every registry source live and report per-source health:
  ok/broken, latency, shape fingerprint status against the state file, and
  consecutive failures. Run this first when output looks wrong.
- `sources`: dump the source registry plus per-source tracker health.
- `discover`: search for new Valorant stats sources through the sibling
  parallel skill and list candidate domains not yet in the registry.

## The degradation contract

Parsers are strict. When a source changes shape, commands fail with explicit
JSON errors (`PARSE_FAILED`, `FETCH_FAILED`) instead of emitting garbage.
When a parse still works but the shape fingerprint moved, output carries a
`warnings` array naming the drift. When a secondary source fails (patch
detail, maps inside snapshot), the affected section is null plus a warning,
never silently absent. If output looks wrong: run `doctor`, read the
fingerprint status and consecutive failures, then follow the repair workflow
in `references/sources.md`.

## Sibling dependency contract

Fetching subprocesses the sibling skill CLIs; this skill never reimplements
their APIs. Resolution order per tool (`firecrawl`, `parallel`):

1. Environment override `VALO_FIRECRAWL_CLI` or
   `VALO_PARALLEL_CLI`, a full path to the sibling `cli.py`.
2. The sibling of this skill's own install: `<skills-dir>/<tool>/scripts/cli.py`.

A missing sibling produces a `MISSING_DEPENDENCY` error naming the dependency
and the override variable. `FIRECRAWL_API_KEY` and `PARALLEL_API_KEY` must be
set for live fetching, as those skills document.

## Source health tracking

Every fetch and parse is recorded in
`${XDG_STATE_HOME:-~/.local/state}/valo/state.json` per source key:
last fetch, last success, shape fingerprint, consecutive failures. The
fingerprint is a hash of structural keys plus a row-count bucket; a mismatch
against a fresh parse means the source shape drifted.

## Follow-up reads

| Need | Read | When |
| --- | --- | --- |
| Abuse/avoid/mover heuristics and their rationale | `references/derivation.md` | Questioning or tuning what snapshot derives |
| Add or vet a source, manual fallback when firecrawl fails, fingerprint-drift repair | `references/sources.md` | doctor reports breakage or drift, or discover finds a candidate |
