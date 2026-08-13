# Normalization and comparison

Every numeric observation retains `raw_value`, `normalized_value` or null, `unit`, `normalization`, `source_path`, `source_field`, `value_status`, `metric_semantics_status`, candidate interpretations and evidence.

An explicit `%` normalizes to percent points (`72.4%` → `72.4`, `removed_percent_sign`). An explicit ratio/fraction remains a ratio unless source metadata defines conversion. Bare `0.724` and bare `72.4` have no safe scale and become `normalized_value:null`, `metric_semantics_status:"ambiguous"`, `NUMERIC_AMBIGUITY`, and a comparison blocker. Explicit source ranges are checked without clamping. Malformed/non-finite values are `unparsed`; out-of-range values remain raw and blocked.

`N/A`, em dash, dash, empty/loading markers, and source-marked animation/chart `0.0%` are `missing` with `PLACEHOLDER_VALUE`. A real zero is kept only when source metadata proves it. `null` never means zero.

Unknown metric names and fields are retained under `raw_fields`/`raw_metadata`. A successfully copied unknown metric is `published` but `metric_semantics_status:"unknown"` and `UNKNOWN_SCORE_SEMANTICS`; it is not relabeled as accuracy/pass@1 and cannot be ranked. Source-absent values are `missing`; fetched-but-unsafe values are `unparsed`.

Vals correctness/accuracy, code quality, uncertainty (`stderr`), latency/complete response, and cost/test are independent metrics. Field names alone do not establish units, denominators, fallback state, or definitions. Fallback inclusion is part of comparison identity and remains blocked when unknown.

A rank requires one exact source benchmark/version/release (or snapshot), definition, unit/scale, scope/denominator, task set, fallback state, harness and unique model variant. Missing and blocked rows remain visible with `rank:null`. Derived calculations live under `derived` with formula/input paths and never overwrite published source values.
