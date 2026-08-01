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

## Scope and provenance

Every successful metrics response includes `data.scope` and `data.provenance`.

`scope` MUST include:

- `benchmark`: exactly `DeepSWE`;
- `benchmark_version`: the resolved semantic version (never an unqualified `latest`);
- `filters_applied`: an object or list describing every default and explicit filter;
- `value_status`: exactly `published`, `published_raw`, or `derived`.

`provenance` MUST include:

- `url`: the artifact URL used;
- `fetched_at`: when the client obtained or revalidated the artifact.

When present in the source, preserve `generated_at`. Preserve `etag`/`ETag` and `last_modified`/`Last-Modified` when available; do not manufacture validators. Snapshot and stale reads MUST expose their local/freshness status and original source metadata rather than appearing current.

Do not cite a value without carrying its status and provenance. A result that combines artifacts MUST prove one benchmark version; otherwise it is an error.

## Published versus derived values

- `published`: a value copied from the canonical `leaderboard-live.json` aggregate. Published leaderboard rows are authoritative and MUST NOT be re-aggregated.
- `published_raw`: a value copied from raw `trials.json` or an unaggregated source row after the documented filter. Raw scope is broader than full DeepSWE.
- `derived`: a calculation made by the skill from published or raw values. Put it under `derived`; never overwrite a published field.

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
- efficiency fields such as `mean_output_tokens`, `mean_cost_usd`, and `mean_agent_steps`.

The skill may add `derived.ci_width`, defined exactly as `ci_hi - ci_lo`. “Confidence” in prose means CI width only; it is not a correctness probability.

## Report and ranking sections

`report` keeps recommendations distinct from raw extrema and exposes a Pareto section. Names may be additive, but the semantic sections are:

- recommendations/ranked rows: decision candidates and their counts/CIs;
- raw extrema: independently best/worst observed values, not silently filtered recommendations;
- Pareto rows: maximize `pass_at_1` and minimize `mean_output_tokens`, `mean_cost_usd`, and `mean_agent_steps`.

Pareto dominance excludes any row with a null comparison metric. Do not impute nulls or create an arbitrary composite score. Low-n/incomplete rows remain visible by default; only explicit `--min-attempted`, `--min-tasks`, or `--min-pass-at-1` may exclude them.

## Trial filters

The published-trial default is:

```json
{"source":"deep-swe","eval_scope":"full","included_in_score":true}
```

`trials` MUST expose `filters_applied` on every success, including explicit overrides. An override can widen visibility, but the output must still identify the selected scope. Do not claim `trials.json` contains only full DeepSWE trials.

## Error semantics

Return an error envelope for invalid versions, unsupported commands/options, HTTP/network failures, non-JSON payloads, schema failures, endpoint/path version mismatches, mixed-version source sets, or unusable cache validators. Never replace a failed refresh with a last-good artifact. Old local data is valid only after explicit `--allow-stale` or `--snapshot`, with freshness metadata preserved.
