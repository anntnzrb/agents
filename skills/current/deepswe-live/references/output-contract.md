# JSON output contract

The CLI contract is intentionally small and additive. Parse JSON only; do not scrape human text. A result may add fields in future releases, but these keys and meanings remain stable for schema version `1`.

## Envelopes

Success is one compact object:

```json
{"ok":true,"schema_version":1,"command":"report","data":{}}
```

Failure is one compact object:

```json
{"ok":false,"schema_version":1,"command":"report","error":{"code":"...","message":"..."}}
```

`ok` controls the branch. `command` is the invoked command, including on errors. Diagnostics, tracebacks, and progress never belong on stdout.

## Command compatibility matrix

Every command emits exactly one compact JSON result object. The success and
failure envelope keeps integer `schema_version: 1`; successful results retain
their `scope` and `provenance` metadata.

| Command | Input and freshness policy | Stable v1 result data |
| --- | --- | --- |
| `fetch` | Versioned `leaderboard-live.json`; `--trials` opts into `trials.json`; `--allow-stale` is explicit. | Artifact metadata, `scope`, and `provenance` (payload bodies are not dumped). |
| `report` | Fetches the leaderboard, or uses explicit `--snapshot PATH`; `--allow-stale` is explicit for refreshes. | Recommendations, `raw_extrema`, `pareto`, counts/filters, and additive derived row fields. |
| `rank` | Ranks the fetched leaderboard, or explicit `--snapshot PATH`; `--allow-stale` is explicit. | Rows/count/filters with the full configuration identity tuple. |
| `trials` | Uses the raw trials artifact, or explicit `--snapshot PATH`; `--allow-stale` is explicit. | Filtered rows/counts and the applied trial filters. |
| `stats` | Summarizes the leaderboard (or opt-in `--trials`), or explicit `--snapshot PATH`; `--allow-stale` is explicit. | `row_count`, `fields`, `missing`, and `numeric_ranges`. |
| `schema` | Offline introspection; `latest` uses the configured default only. No runtime release discovery. | Command list, envelope, scope, provenance, and compatibility metadata. |
| `diagnose` | Offline artifact shape/provenance inspection; explicit `--snapshot` is local and no rows/task content are emitted. | Summary, stable diagnostics, duplicate/cache/schema facts, and scope/provenance. |
| `compare` | Exactly two local snapshots (`--snapshot LEFT --snapshot RIGHT` or paths); both must prove one concrete same version. | `changes` with stable `config`, `before`, `after`, and `delta` fields. |

`latest` resolves through `DEEPSWE_DEFAULT_VERSION`, then the configured code
fallback `v1.1`; it never discovers releases from a manifest, homepage, or
directory listing. `--snapshot` and `--allow-stale` remain explicit historical
or stale-data choices, respectively.

## Legacy v1 compatibility

`schema_version` is the integer `1`, not the string `"1"`. Consumers that parse
legacy v1 results MUST continue to accept the existing envelope keys, command
names, identity tuple (`model + reasoning_effort + harness + config`), rows,
changes, and report sections. Future fields are additive: consumers MUST ignore
unknown fields and no existing field is renamed or repurposed.

## Additive evidence and migration table

| Contract area | Legacy v1 behavior | Hardened additive behavior |
| --- | --- | --- |
| Envelope | Integer `schema_version: 1`; one success/error object | Same keys and integer; `diagnostics` and evidence are additive |
| Rows | Raw source fields and four-field identity remain at the same paths | `metrics` evidence and `derived` fields are additive; raw fields are never moved |
| Evidence | Not required for legacy snapshots | Known numeric values may carry `raw_value`, `normalized_value`, `unit`, `normalization`, `source_path`, `parser`, `parser_version`, hash/raw-byte reference |
| Value status | Scope uses `published`, `published_raw`, `derived` | Value-level missing/unparsed values remain visible; `value_status`, `metric_semantics_status`, `comparison_eligibility`, and `blocked_reasons` explain eligibility |
| Schema absence | Structurally valid legacy payloads may omit artifact schema | Strict compare treats schema presence/absence mismatch as `schema_mismatch`; no schema is inferred from shape |
| Commands | `fetch`, `report`, `rank`, `trials`, `stats`, `schema`, `compare` | `diagnose` is additive; strict flags are opt-in and do not rename commands |
| Errors | Stable lower-case `error.code` and message envelope | Same one-object error shape; diagnostics are ordered/redacted and remain out of stdout |

Consumers parsing `rows` directly can keep reading the existing raw fields and
should ignore unknown additive keys. Consumers that rank arbitrary custom
fields should opt into `--strict-semantics` or inspect
`comparison_eligibility`; blocked, ambiguous, missing, malformed, and unknown
values must not be treated as zero. `compare --strict-compare` is the
migration path for schema/semantic compatibility and duplicate conflict
blocking. `rank --strict-rank` (alias `--strict-duplicates`) is the migration
path for strict duplicate handling.

Duplicate identities use the complete JSON tuple
`[model, reasoning_effort, harness, config]`. Identical duplicates warn and
select the first source row deterministically. Conflicting duplicates warn in
legacy mode and block strict compare/rank; there is no last-write-wins merge.

## Scope and provenance

Every successful metrics response includes `data.scope` and `data.provenance`.

`scope` MUST include:

- `benchmark`: exactly `DeepSWE`;
- `benchmark_version`: the resolved semantic version (never an unqualified `latest`);
- `filters_applied`: an object or list describing every default and explicit filter;
- `value_status`: exactly `published`, `published_raw`, or `derived`
- `dependencies`: `[]` when DeepSWE publishes no dependency claims;
- `independence_class`: `"unknown"` when no explicit claims are available.

`provenance` MUST include:

- `url`: the artifact URL used;
- `fetched_at`: when the client obtained or revalidated the artifact

When present in the source, preserve `generated_at`. Preserve `etag`/`ETag` and `last_modified`/`Last-Modified` when available; do not manufacture validators. Snapshot and stale reads MUST expose their local/freshness status and original source metadata rather than appearing current.

Do not cite a value without carrying its status and provenance. A result that combines artifacts MUST prove one benchmark version; otherwise it is an error.

## Published versus derived values

- `published`: a value copied from the canonical `leaderboard-live.json` aggregate. Published leaderboard rows are authoritative and MUST NOT be re-aggregated
- `published_raw`: a value copied from raw `trials.json` or an unaggregated source row after the documented filter. Raw scope is broader than full DeepSWE
- `derived`: a calculation made by the skill from published or raw values. Put it under `derived`; never overwrite a published field

A response can contain rows with published fields and a `derived` object. Label each row/value at the nearest useful scope. Do not call a derived confidence interval a published benchmark result.

## Rows and identity

A configuration is the tuple:

```text
model + reasoning_effort + harness + config
```

Rows with different reasoning effort, harness, or config remain separate even when `model` matches. Preserve nulls: null means unavailable, not zero.

Ranked/report rows should carry, when supplied by the source:

- identity fields above;
- score/pass fields, including `pass_at_1` when available;
- `n_attempted` and `n_tasks_attempted` when available;
- `ci_lo`, `ci_hi`, `ci_half`;
- efficiency fields such as `mean_output_tokens`, `mean_cost_usd`, and `mean_agent_steps`

The skill may add `derived.ci_width`, defined exactly as `ci_hi - ci_lo`. “Confidence” in prose means CI width only; it is not a correctness probability.

## Report and ranking sections

`report` keeps recommendations distinct from raw extrema and exposes a Pareto section. Names may be additive, but the semantic sections are:

- recommendations/ranked rows: decision candidates and their counts/CIs;
- raw extrema: independently best/worst observed values, not silently filtered recommendations;
- Pareto rows: default maximizes `pass_at_1` and minimizes `mean_output_tokens`, `mean_cost_usd`, and `mean_agent_steps`;
- optional `pareto_axes`: explicit `{metric, order}` metadata when `--pareto-axis` is supplied;
- optional `efficiency`: explicit numerator/denominator ratios under each copied row's `derived` object

Pareto dominance excludes any row with a null comparison metric. Custom axes use `min`/`asc` or `max`/`desc`; do not impute nulls or create an arbitrary composite score. Low-n/incomplete rows remain visible by default; only explicit `--min-attempted`, `--min-tasks`, or `--min-pass-at-1` may exclude them. Efficiency division never emits infinity: zero denominators and invalid inputs remain null with a reason.

## Trial filters

The published-trial default is:

```json
{"source":"deep-swe","eval_scope":"full","included_in_score":true}
```

`trials` MUST expose `filters_applied` on every success, including explicit overrides. An override can widen visibility, but the output must still identify the selected scope. Do not claim `trials.json` contains only full DeepSWE trials.

## Error semantics

Return an error envelope for invalid versions, unsupported commands/options,
HTTP/network failures, non-JSON payloads, schema failures, endpoint/path
version mismatches, mixed-version source sets, or unusable cache validators.
Never replace a failed refresh with a last-good artifact. Old local data is
valid only after explicit `--allow-stale` or `--snapshot`, with freshness
metadata preserved.

## Numeric evidence and diagnostics

Known numeric metrics may carry an additive evidence object with
`raw_value`, `normalized_value`, `unit`, `normalization`, `source_path`,
`parser`, `parser_version`, `artifact_sha256`/`sha256`, and `raw_bytes_ref`.
The evidence also records `value_status`, `metric_semantics_status`,
`comparison_eligibility`, and `blocked_reasons`. Missing, placeholder,
malformed, non-finite, out-of-range, ambiguous, and unknown values remain
visible with null normalized values or explicit reasons; none is silently
coerced to zero.

`diagnostics` are stable, deduplicated, redacted objects ordered by `code`,
severity, stage, path, and details. `diagnose` reports these facts from local
snapshots without fetching or returning rows/task content.
`--strict-semantics` blocks unknown metric semantics. `compare
--strict-compare` blocks incompatible artifact schema/metric unit, scope, or
denominator and conflicting duplicate identities. Identical duplicate
identities warn and use the first row deterministically; strict conflict
blocking never silently overwrites source rows.

`latest` follows only the configured default and never performs release
discovery. Immutable cache manifests and sidecars retain concrete source URL,
version, validators, parser identity, hash, and raw-byte reference. Legacy
cache promotion is non-destructive.
