---
name: vals-live
description: "Use when the user asks to discover or compare official Vals benchmarks, model scores, cost, latency, or uncertainty."
license: AGPL-3.0-or-later
---

# Vals Live

Use when request names Vals, `vals.ai`, Vals Index, Vals benchmarks, model comparisons, Code Migration, Vibe Code Bench, SWE-bench, Terminal-Bench, cost/test, latency/test, benchmark versions, or newly discovered Vals metrics.

## Purpose

`vals-live` reads official Vals source pages → one machine-readable JSON object. Catalog contents are runtime-discovered; no current benchmark/model list is embedded. Unknown fields remain visible; unknown metric semantics are never ranked as familiar scores.

## Invocation

```text
uv run --script skills/current/vals-live/scripts/cli.py <command> [options]
```

Canonical commands:
- `catalog`: discover active, archived, version-linked benchmark entries; only listing command (no `benchmarks` alias).
- `models`: discover model/provider/variant records.
- `model --model <id-or-name>`: project one exact model.
- `benchmark --benchmark <id-or-url>`: project one exact benchmark/version.
- `compare --models <a,b,...> [--benchmarks <x,y,...>]`: compare compatible rows only.
- `catalog-diff --left <snapshot> --right <snapshot>`: conservatively classify changes.
- `diagnose`: expose extraction, transport, drift, value diagnostics.
- `schema`: return stable contract without network access.
- `refresh`: fetch and retain immutable source bytes.
- `snapshot --snapshot <path>`: materialize/read explicit historical source snapshot.
Selectors MUST resolve to discovered source IDs, exact labels, or official URLs.

## Source and freshness

Official seeds: `https://www.vals.ai/benchmarks`, `https://www.vals.ai/models`, plus Vals methodology/detail links discovered from them. Extraction precedence: official JSON/asset > tabular asset > embedded HTML JSON/Astro props > RSC frames > JSON-LD > semantic HTML tables > data attributes > plain text. Static JavaScript shells return `REQUIRES_RENDERED_SOURCE`; no browser dependency.

Every refresh uses ETag and Last-Modified when available and stores exact immutable content-addressed bytes. Default cache follows platform/XDG conventions; override with `--cache-dir` or `VALS_CACHE_DIR`. Failed refresh errors by default. `--allow-stale` explicitly permits matching cache bytes and marks `stale:true`, `freshness.mode:"stale-cache"`. `--snapshot` is historical (`historical:true`, `stale:false`, `freshness.mode:"snapshot"`). No older release, benchmark version, or last-good artifact is selected implicitly.

## Output contract

Stdout contains exactly one compact JSON object, including failures; logs go to stderr. Every success has `ok:true`, `schema_version:"1"`, `command`, and `data`; metric data has `scope`, `rows`, `warnings`, `provenance`, and nearest-scope `value_status`. Failures have `ok:false` and an error object with stable uppercase `code`, `message`, and object `details`. `null` means unavailable or unsafe to interpret, never zero.

Numeric observations retain raw and normalized values, unit, normalization note, source path, source/release identity, status, and per-value provenance. Bare numeric scales/units are ambiguous and blocked. `0.0%`, `N/A`, dashes, loading markers, malformed, non-finite, and out-of-range values never become measurements. Unknown fields stay under `raw_fields`/`raw_metadata`; published values remain separate from derived values.

Comparisons require exact source benchmark/version or snapshot, release, metric definition/family, unit/scale, scope/denominator, task set, fallback state, and model variant/harness identity. Correctness, code quality, uncertainty, cost/test, and latency/test remain separate. Preserve Index methodology; do not reconstruct it from incomplete inputs. Overlap metadata uses `requirements_claim` when not observed; never invent overlap.

## Required follow-up reads

- Runtime source routing: `references/source-discovery.md`; before selecting a seed or selector.
- Extraction precedence: `references/extraction.md`; when HTML/island/RSC/table data differs.
- Values and semantic gates: `references/normalization.md`; before reporting or ranking a metric.
- Cache and field lineage: `references/provenance.md`; when using refresh, stale, or snapshots.
- Drift and catalog diff: `references/drift-handling.md`; when a catalog/page changes.
- Dependencies and overlap: `references/overlap-model.md`; when comparing composites or coding benchmarks.
- Fixture/eval expectations: `references/eval-notes.md`; when extending tests or source fixtures.
