# Normalization

## Dynamic catalogs

Category keys and ordered subtask arrays come from the selected release's category JSON. Score headers come from the CSV. New categories, task keys, model rows, variants, and columns flow into output maps/lists without production allow-lists. A category absent from a release is absent/null, never a zero.

Model identity is `livebench:model:<slug>` plus a structured provider/variant identity. The app's organization map is display metadata; provider/API routing remains null unless explicitly published. Unknown model rows are preserved even if the current UI would hide them.

## Value status and evidence

- `published`: copied from a source cell, including unknown semantics;
- `derived`: computed value with formula and input paths under `derived`;
- `missing`: source-absent or placeholder value with reason;
- `unparsed`: fetched value that is unsafe to parse.

Every numeric object preserves `raw_value`, `normalized_value` or null, `unit`, `normalization`, `source_path`, `value_status`, `metric_semantics_status`, and source evidence. Bare numeric values without source unit/definition remain visible but comparison-blocked. Explicit percent signs/ratio metadata control conversion; malformed/non-finite values are never coerced, and declared out-of-range values are never clamped. `N/A`, em dash, dash, empty/loading values, and source-marked `0.0%` placeholders are missing, not zero.

## Score formulas

The observed table publishes subtask cells only. For each category, the adapter derives:

`mean_available_subtask_values`

using available mapped subtask values. Overall is a separate derived value:

`mean_of_category_averages`

The UI definition evidence is retained as `Overall — mean of category averages`. No source value is renamed to a generic pass metric.

## Cost formulas

Published `cost_per_question` and `cost_per_successful_task` remain unchanged under `cost.published` and retain their CSV paths and denominator identity. A selected-scope recomputation, when all task cost and `nq_<task>` inputs plus a selected score are available, is separate under `cost.derived`:

`(sum cost / sum questions / selected score) * 100`

It is never reconstructed from token prices, list prices, Artificial Analysis, DeepSWE, or another release.
