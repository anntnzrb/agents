# Drift and failure handling

A release is accepted only when its required table/category assets parse and agree on one release identity. Mixed filenames, embedded IDs, or artifact metadata produce `MIXED_RELEASE`; no rows are combined and no older release is selected.

Required diagnostics include `SOURCE_UNAVAILABLE`, `SOURCE_AUTH_REQUIRED`, `REQUIRES_RENDERED_SOURCE`, `RELEASE_NOT_FOUND`, `MIXED_RELEASE`, `STALE_DATA`, `RELEASE_DISCOVERY_LIMITED`, `CACHE_MISSING`, `CACHE_VALIDATOR_INVALID`, `MALFORMED_PAYLOAD`, `SCHEMA_DRIFT`, `UNKNOWN_SCORE_SEMANTICS`, `UNKNOWN_CATEGORY`, `PLACEHOLDER_VALUE`, `NUMERIC_AMBIGUITY`, `OUT_OF_RANGE`, `DUPLICATE_MODEL_VARIANT`, `MISSING_REQUIRED_IDENTITY`, `PARTIAL_EXTRACTION`, `SNAPSHOT_INVALID`, `MODEL_NOT_FOUND`, `COMPARISON_INCOMPARABLE`, and `OVERLAP_DOUBLE_COUNTING_RISK`.

Unknown columns/metrics/categories remain visible under `raw_fields` or `raw_metadata`. Unknown semantics are `published` when copied safely but comparison-blocked with `UNKNOWN_SCORE_SEMANTICS`; missing and unparsed values are not equivalent. Unmapped score columns are retained as unknown subtasks with `UNKNOWN_CATEGORY`.

Duplicate model/provider/variant identities remain inspectable. Byte-identical duplicates are visible and collapsed only for ranking with a warning. Conflicting duplicates are excluded from ranking and produce a blocker; if no usable rows remain, the command fails. A partial result is `ok:true` only when usable records and field-level warnings are separated. Empty/fully broken tables are failures, never successful empty leaderboards.

`catalog-diff` matches stable source IDs/category keys conservatively, reporting added, removed, renamed, metadata, schema, and possible-rename changes without fuzzy merges or invented zero values.
