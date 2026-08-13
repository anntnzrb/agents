# Source discovery

## Seeds

Use only first-party Vals entry points:

- `https://www.vals.ai/benchmarks`
- `https://www.vals.ai/models`
- `https://www.vals.ai/methodology`
- Same-origin benchmark/model/detail URLs discovered from those pages.

A seed is an entry point, not a complete catalog. Discovery retains the source URL, final URL, discovery URL, canonical URL, source ID, slug, display label, category, status, update/version metadata, methodology link, task/model count and raw metadata.

## Separate populations

Vals pages can expose distinct populations. Keep `active_selector_entries`, `all_detail_anchors`, `version_selector_entries`, and model rows separate. Archived, noindex, and non-canonical pages remain visible, but are not silently included in the active comparison population. A count carries its population and kind (`detail_models`, `global_models`, `task_keys`, or `task_instances`) rather than an unqualified denominator.

## Identity

Prefer a source-provided `benchmark_id` or model ID, then a canonicalized official URL, then a source path/slug only when the source identifies it. Display labels are not identities. Preserve original and canonical URLs. A Vals page without a source-defined release/version gets `source_release_id:null` and `snapshot:sha256:<hash>` identity; an update date is metadata, not a release.

## Selectors

Selectors resolve exact source ID, exact canonical/original URL, exact slug, or exact display label after runtime discovery. A miss is `BENCHMARK_NOT_FOUND` or `MODEL_NOT_FOUND`; never synthesize an ID from an unrecognized string.

## Static runtime boundary

The implementation does not launch a browser or execute page JavaScript. Empty Astro/client shells and model expansions unavailable in the static artifact return `REQUIRES_RENDERED_SOURCE` (or `SOURCE_UNAVAILABLE`) with attempted URL and delivery details. It does not use screenshots, OCR, search snippets, chart pixels, or remembered values.
