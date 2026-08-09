---
name: vals-live
description: Discover and compare official Vals benchmarks, model variants, scores, quality, cost/test, latency, and uncertainty.
---

# Vals Live

Use this skill when a request names Vals, `vals.ai`, Vals Index, Vals benchmarks, model comparisons, Code Migration, Vibe Code Bench, SWE-bench, Terminal-Bench, cost/test, latency/test, benchmark versions, or newly discovered Vals metrics.

## Purpose

`vals-live` reads official Vals source pages and emits one machine-readable JSON object. Catalog contents are discovered at runtime; no current benchmark or model list is embedded in this skill. Unknown fields remain visible and unknown metric semantics are never ranked as familiar scores.

## Invocation

```text
uv run --script assets/skills/vals-live/scripts/cli.py <command> [options]
```

Canonical commands:

- `catalog` — discover active, archived, and version-linked benchmark entries.
- `models` — discover model/provider/variant records.
- `model --model <id-or-name>` — project one exact model.
- `benchmark --benchmark <id-or-url>` — project one exact benchmark/version.
- `compare --models <a,b,...> [--benchmarks <x,y,...>]` — compare only compatible rows.
- `catalog-diff --left <snapshot> --right <snapshot>` — conservatively classify changes.
- `diagnose` — expose extraction, transport, drift, and value diagnostics.
- `schema` — return the stable contract without network access.
- `refresh` — fetch and retain immutable source bytes.
- `snapshot --snapshot <path>` — materialize/read an explicit historical source snapshot.

`catalog` is the only listing command; there is no `benchmarks` alias. Selectors must resolve to discovered source IDs, exact labels, or official URLs.

## Source and freshness rules

Official seeds are `https://www.vals.ai/benchmarks`, `https://www.vals.ai/models`, and Vals methodology/detail links discovered from them. Extraction precedence is official JSON/asset, tabular asset, embedded HTML JSON/Astro props, RSC frames, JSON-LD, semantic HTML tables, data attributes, then plain text. Static JavaScript shells return `REQUIRES_RENDERED_SOURCE`; this skill has no browser dependency.

Every refresh uses ETag and Last-Modified when available and stores exact immutable content-addressed bytes. The default cache follows platform/XDG conventions; override it with `--cache-dir` or `VALS_CACHE_DIR`. A failed refresh is an error by default. `--allow-stale` explicitly permits matching cache bytes and marks `stale:true`, `freshness.mode:"stale-cache"`. `--snapshot` is historical (`historical:true`, `stale:false`, `freshness.mode:"snapshot"`). No older release, benchmark version, or last-good artifact is selected implicitly.

## Output contract

Stdout contains exactly one compact JSON object, including failures. Logs belong on stderr. Every success has `ok:true`, `schema_version:"1"`, `command`, and `data`; metric data has `scope`, `rows`, `warnings`, `provenance`, and nearest-scope `value_status`. Failures have `ok:false` and an error object with stable uppercase `code`, `message`, and object `details`. `null` means unavailable or unsafe to interpret, never zero.

Numeric observations retain raw and normalized values, unit, normalization note, source path, source/release identity, status, and per-value provenance. Bare numeric scales/units are ambiguous and blocked. `0.0%`, `N/A`, dashes, loading markers, malformed, non-finite, and out-of-range values never become measurements. Unknown fields are retained under `raw_fields`/`raw_metadata`. Published values remain separate from derived values.

Comparisons require exact source benchmark/version or snapshot, release, metric definition/family, unit/scale, scope/denominator, task set, fallback state, and model variant/harness identity. Correctness, code quality, uncertainty, cost/test, and latency/test are separate. Index methodology is preserved; it is not reconstructed from incomplete inputs. Overlap metadata uses `requirements_claim` when not observed and never invents overlap.

## Required follow-up reads

| Need | Read | When |
|---|---|---|
| Runtime source routing | `references/source-discovery.md` | Before selecting a seed or selector |
| Extraction precedence | `references/extraction.md` | When HTML/island/RSC/table data differs |
| Values and semantic gates | `references/normalization.md` | Before reporting or ranking a metric |
| Cache and field lineage | `references/provenance.md` | When using refresh, stale, or snapshots |
| Drift and catalog diff | `references/drift-handling.md` | When a catalog/page changes |
| Dependencies and overlap | `references/overlap-model.md` | When comparing composites or coding benchmarks |
| Fixture/eval expectations | `references/eval-notes.md` | When extending tests or source fixtures |
