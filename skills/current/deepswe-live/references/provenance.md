# Provenance and value status

Use this reference whenever a result is cited, cached, compared, or labeled. Provenance is part of the JSON contract, not optional explanatory prose.

## Canonical sources

The only supported artifact base is:

```text
https://deepswe.datacurve.ai/artifacts/{benchmark_version}/
```

Allowed files:

- `leaderboard-live.json`: canonical published aggregate and the default `fetch` target;
- `trials.json`: optional raw trial input, fetched only with explicit `--trials`

Do not download task, exercise, release, or trial-artifact files. Do not infer a version from a homepage or combine files from different version paths.

For each source, retain:

```json
{
  "url": "https://deepswe.datacurve.ai/artifacts/v1.1/leaderboard-live.json",
  "fetched_at": "<RFC-3339 timestamp>",
  "generated_at": "<source timestamp when supplied>",
  "etag": "<header value when supplied>",
  "last_modified": "<header value when supplied>"
}
```

The exact key casing used by the CLI is authoritative; preserve both the fact and the original header value. Never synthesize `generated_at`, ETag, or Last-Modified.

## Version identity

`latest` resolves through one central default: `DEEPSWE_DEFAULT_VERSION`, or configured `v1.1` if unset. Explicit semantic versions `v1.1+` are future-release compatible. Reject major-only `v1`/`1`, and never fetch legacy v1. The resolved version MUST agree with the URL path and every source artifact in a response.

A mixed-version source set is invalid even if its JSON shape appears compatible. Return an error rather than silently selecting one version.

## Cache and freshness

Conditional requests use cached ETag and/or Last-Modified values. A valid `304 Not Modified` means the exact cached artifact may be reused; retain the cache's content and update revalidation metadata without relabeling its source. A 304 with no usable cache is an error.

Network errors, non-success HTTP statuses, malformed JSON, schema failures, validator failures, and path/version mismatches are visible errors. A failed refresh MUST NOT fall back to a last-good artifact. Only explicit `--allow-stale` or `--snapshot` authorizes old local data; mark the result stale/historical and preserve original provenance. “Fresh” is not inferred from a file's existence.

## Value status labels

Use exactly one label at the relevant scope:

- `published`: copied from `leaderboard-live.json`; never recomputed;
- `published_raw`: copied from `trials.json` or another unaggregated published row after explicit filtering;
- `derived`: calculated by the skill from source values

Derived values belong below `derived` and never replace source fields. In particular, `ci_width = ci_hi - ci_lo` is derived even when both bounds are published. Raw extrema and recommendations are separate sections; an extremum is not automatically a recommendation.

## Filters and visibility

Raw-trial default filters are `source='deep-swe'`, `eval_scope='full'`, and `included_in_score=true`. Record defaults and overrides in `scope.filters_applied`. Raw `trials.json` has broader scope, so never describe the complete file as only full DeepSWE. A row excluded by an explicit quality/sample threshold must remain distinguishable from a row absent from the source.

## Citation checklist

Before presenting a metric, verify:

1. `scope.benchmark` is `DeepSWE` and `scope.benchmark_version` is resolved;
2. its `value_status` is explicit;
3. `provenance.url` and `provenance.fetched_at` are present;
4. `generated_at` and validators are retained when supplied;
5. filters, stale/snapshot state, and explicit thresholds are stated;
6. configuration identity is complete and null metrics were not imputed

## Additive metric evidence

For every emitted numeric value that has source support, retain an additive
evidence projection with:

```json
{
  "raw_value": "75%",
  "normalized_value": 0.75,
  "unit": "ratio",
  "normalization": "percentage_to_ratio",
  "source_path": "$.rows[0].pass_at_1",
  "parser": "deepswe.normalization.parse_numeric",
  "parser_version": "1",
  "artifact_sha256": "<sha256>",
  "raw_bytes_ref": "artifacts/<sha256>.raw",
  "value_status": "published",
  "metric_semantics_status": "known",
  "comparison_eligibility": "eligible"
}
```

`published`, `published_raw`, and `derived` are value-status labels, not
confidence claims. Missing, placeholder, malformed, non-finite, out-of-range,
unknown, and ambiguous values remain visible with null normalized values and
explicit `blocked_reasons`; they are never silently treated as zero. Derived CI width and efficiency carry formulas/input paths under `derived` and never replace source fields.

Consumers reading legacy rows directly can retain their existing field paths:
evidence is additive. Consumers ranking arbitrary custom metrics should inspect
`metric_semantics_status` and `comparison_eligibility` or opt into
`--strict-semantics`. `compare --strict-compare` proves artifact schema and
metric unit/scope/denominator compatibility before eligible deltas. Duplicate
identities use all four fields; identical duplicates warn/use the first row,
while conflicting duplicates warn in legacy mode and block strict compare/rank.

## Cache, manifests, and release authority

Cache provenance includes canonical URL, concrete benchmark version, validator
headers, parser/version, SHA-256 of exact bytes, byte length, and an immutable
raw-byte reference. Manifests are immutable snapshots of source-index
provenance and do not replace the bytes. A legacy version-addressed file may be
promoted into the content-addressed cache with `legacy_unverified: true`;
promotion is non-destructive and leaves the caller's file untouched.

`latest` uses only `DEEPSWE_DEFAULT_VERSION` or configured default `v1.1`.
There is no release discovery from a homepage, directory, or unconfigured
manifest. An explicitly configured authoritative manifest may be used only
after exact version, canonical path, and hash agreement. Same-version proof is
mandatory for compare. `--allow-stale` and `--snapshot` are explicit choices;
stale or historical provenance must remain visible after either.

When no source-observed dependency claims exist, report `dependencies: []` and
`independence_class: "unknown"`. Exact explicit canonical component+release
collisions may warn, but similar names do not trigger fuzzy overlap or score
adjustment. Diagnostics are stable, deduplicated, and redacted; one-object
errors remain on stdout while human diagnostics stay on stderr.
