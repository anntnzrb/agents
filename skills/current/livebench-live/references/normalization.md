# Normalization

## Dynamic catalogs
Selected-release category JSON → category keys, ordered subtask arrays; CSV → score headers. New categories, task keys, model rows, variants, and columns flow into output maps/lists; no production allow-lists. Category absent from release → absent/null, NEVER zero.

Model identity: `livebench:model:<slug>` + structured provider/variant identity. Organization map: display metadata only; provider/API routing null unless explicitly published. Preserve unknown model rows even when the current UI hides them.

## Value status and evidence
- `published`: copied from source cell, including unknown semantics.
- `derived`: computed value with formula and input paths under `derived`.
- `missing`: source-absent or placeholder value with reason.
- `unparsed`: fetched value unsafe to parse.

Every numeric object preserves `raw_value`, `normalized_value` or null, `unit`, `normalization`, `source_path`, `value_status`, `metric_semantics_status`, and source evidence. Bare numeric values lacking source unit/definition remain visible but comparison-blocked. Explicit percent signs/ratio metadata control conversion; malformed/non-finite values are never coerced; declared out-of-range values are never clamped. `N/A`, em dash, dash, empty/loading values, and source-marked `0.0%` placeholders → missing, not zero.

## Score formulas
Observed table publishes subtask cells only. Per category, adapter derives `mean_available_subtask_values` from available mapped subtask values. Overall is separate derived `mean_of_category_averages`. Retain UI definition evidence `Overall; mean of category averages`. Never rename a source value to a generic pass metric.

## Cost formulas
Published `cost_per_question` and `cost_per_successful_task` remain unchanged under `cost.published`, retaining CSV paths and denominator identity. When all task cost and `nq_<task>` inputs plus a selected score are available, selected-scope recomputation is separate under `cost.derived`:

`(sum cost / sum questions / selected score) * 100`

NEVER reconstruct it from token prices, list prices, Artificial Analysis, DeepSWE, or another release.
