# Drift and catalog diff

Treat upstream additions as data. Discovery accepts new benchmark slugs, labels, industries, versions, tasks, model variants, score fields, metadata and table columns without a production allow-list. Preserve every unknown value and issue `SCHEMA_DRIFT`, `UNKNOWN_CATEGORY`, `UNKNOWN_SCORE_SEMANTICS`, or `PARTIAL_EXTRACTION` as appropriate.

`catalog-diff` matches exact non-empty source ID first, then normalized canonical URL, then a source-defined stable slug/path. Display-name similarity only produces `possible_renames`; it never silently merges entries. A stable ID with a changed label is `renamed`; URL, task count, version, release, category, definition and methodology changes are separate `changed_metadata`. Added/removed fields are `schema_changes`.

Duplicate model-variant identities remain visible. Byte-identical duplicates produce a warning and are collapsed only for ranking. Conflicting duplicates are comparison blockers and fail when no usable rows remain. Different provider/variant/harness values are distinct identities; provider is never inferred from a model name.

One output partition uses one exact release/version. A mixed row set is `MIXED_RELEASE` and is not repaired by selecting an older release. A source page update date, ETag, Last-Modified, Vercel cache marker, or cache-busting token is transport metadata, not a benchmark release.

Partial results are valid only when usable rows/fields are separated from missing/unparsed values and warnings. Empty success is not a substitute for a broken source.
