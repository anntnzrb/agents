# artificial-analysis output contract

All command outputs are JSON.

Read this before consuming CLI/RPC envelopes, snapshot fields, coding evidence, or reasoning metrics.

## CLI envelope

```json
{"ok":true,"version":"1","command":"fetch|stats|diff|diagnose|harness|coding|evaluation|reasoning|query|qa|schema","data":{...}}
```

## Compatibility freeze

| Surface | Frozen contract | Additive migration boundary |
| --- | --- | --- |
| Entry point | One documented CLI entry point; an omitted command resolves to `fetch` | Add flags or commands only; do not rename or remove the entry point |
| CLI commands | `fetch`, `stats`, `diff`, `diagnose`, `harness`, `coding`, `evaluation`, `reasoning`, `query`, `qa`, `schema` | Keep every existing name; new commands are additive |
| CLI success | `ok: true`, string `version: "1"`, `command`, and `data` | Preserve these keys and types; additions must not rename, remove, or retype them |
| Artifact defaults | `<temp-dir>/artifacts/artificial-analysis/{full-data.json,endpoints.txt,full-url.txt}` | Preserve these paths; custom output paths remain opt-in |
| Snapshot v2 | `meta.schema_version: 2` with top-level `models`, `hosts`, and slim `hosts_models` joined by `model_slug` | Add fields or projections only; keep v2 keys and the join stable |
| Pricing scope | Model/API `price_1m_blended_3_to_1` and endpoint/RSC `price_1m_blended_7_to_2_to_1` remain distinct | Do not merge, rename, or reinterpret either scope |
| Strict parsing | Malformed source envelopes/rows remain rejected; `fetch --strict` remains the no-fallback mode | Preserve rejection and fallback semantics; any reconciliation is versioned and additive |

### Freshness modes

Every refresh/reader result distinguishes these modes:

- `fresh`: successful current source response (`stale:false`, `historical:false`);
- `cache-revalidated`: validated 304/body reuse (`stale:false`), never outage-stale;
- `stale-last-good`: explicit `--allow-stale` or
  `--stale-policy allow-last-good` fallback (`stale:true`, `fallback:true`);
- `snapshot`: explicit local input (`historical:true`, `stale:false`).

The default refresh policy is `error`; `--strict` remains its compatibility alias.
The default output snapshot still enforces its 24-hour reader guard. A stale
fallback never overwrites current cache bytes. Explicitly named old paths are
historical snapshots, not stale outage fallbacks.

## RPC envelope

Success:

```json
{"id":"...","type":"response","command":"...","success":true,"data":{...}}
```

Error:

```json
{
  "id": "...",
  "type": "response",
  "command": "...",
  "success": false,
  "error": { "code": "...", "message": "..." }
}
```

## Fetch credentials

Only `fetch` requires `ARTIFICIAL_ANALYSIS_API_KEY`. Prefer a process-injected
key, or set `ARTIFICIAL_ANALYSIS_ENV_FILE` to a permissions-restricted dotenv
file (for example, mode `0600`) outside the skill tree. It is never a CLI or RPC
argument.

Do not copy `.env.example` into the skill tree or a generated tool home. It is a
tracked template, not a secret store. Process values win, then the explicitly
supplied external env file is read. Older installations may discover a skill-root
or ancestor `.env`; that lookup is transitional compatibility only and is not
supported for new setups. This release does not expose an `AA_LEGACY_DOTENV`
switch, so do not rely on one.

The asset-sync owner MUST exclude `.env` and other secret files from generated
tool homes. `.gitignore` only controls Git tracking; it cannot enforce sync
exclusion.

## Snapshot JSON structure (schema v2)

Top-level keys:

- `meta`
- `models`
- `hosts`
- `hosts_models`

`meta` includes `schema_version: 2`, `counts`, and `sources`. `sources.rsc` and
`sources.official_api` each expose source URL, status code, fetched-at timestamp,
ETag when supplied, and `reused_cached_payload` when applicable. Source metadata
does not include credentials or raw response bodies.

`counts` includes unique canonical `models`, `hosts`, and endpoint
`hosts_models` (plus endpoint/provider sanity counts where available).

`models` is the only model projection: exactly one canonical row per
`slug`. Official API model identity, evaluations, and API pricing belong here.
`hosts_models` is a slim provider-endpoint table; each row has `model_slug` and
joins to that canonical model, while retaining endpoint/provider fields such as
pricing, speed, latency, context, features, and classifications. It does not
embed a `model` object.

The model API's 3:1 pricing blend and RSC endpoint's 7:2:1 pricing blend are
intentionally both present. They have model and provider-endpoint scope,
respectively, and are not duplicate prices.

## Evidence, statuses, and eligibility

Named scalar fields remain stable; additive `metric_evidence.<metric>` records
`raw_value`, `normalized_value`, `unit`, `normalization`, `source_path`,
`source_field`, `value_status`, `metric_semantics_status`,
`comparison_eligibility`, `blocked_reasons`, `parser`, `parser_version`, and
`artifact_id`/`sha256` when available.

- `value_status`: `published`, `derived`, `missing`, or `unparsed`;
- `metric_semantics_status`: `known`, `unknown`, or `ambiguous`;
- `comparison_eligibility`: `eligible` or `blocked`.

Placeholders, booleans, non-finite/malformed/out-of-range values, unknown
semantics, unit/scope/release mismatches, and conflicting duplicates remain
visible with reasons and cannot become fake zeroes or eligible comparisons.
Derived fields retain formulas and input paths; they never replace published
source values. Unknown source keys survive under `raw_fields`/`raw_metadata`.

## Diagnostics, diff, and error migration

`diagnose` inspects explicit local snapshot/cache paths only; it never fetches.
Its report includes redacted schema/parser/freshness/source/cache/artifact health
and diagnostics. `diff --schema-aware` (or RPC `schema_aware:true`) adds
`schema_diff` while preserving every legacy endpoint/provider key. Stable IDs
match first; possible rename suggestions carry `merge:false`.

CLI success remains protocol v1 and RPC emits one response per non-empty input
line with existing error codes. During staged migration, `--json-errors` emits
one compact redacted CLI error object on stdout; `--legacy-errors` keeps the
human-readable stderr path. No credential appears in either form.

## Immutable artifacts and URL policy

Raw source bytes are content-addressed under `<cache>/artifacts/` with redacted
metadata sidecars; immutable manifests are under `<cache>/manifests/` and are
atomically written. Legacy mutable cache inputs are marked
`legacy_unverified` when promoted. `evaluation <url>` permits HTTPS only and
redacts credential query parameters; use `evaluation --input <file>` for local
or deterministic replay.

## QA payload

`qa` returns:

- `question`
- `parsed_intent` (`model`, `provider`, `sort_by`, `order`, `limit`)
- `query` (full query payload)

## Query rows

Each `query` row may include nulls when upstream does not provide a metric.

High-signal fields:

- identity: `endpoint_slug`, `model_slug`, `provider_slug`
- quality: `intelligence`, `coding`, `math`, `gpqa`, `mmlu_pro`, `ifbench`, `scicode`, `tau2`
- economics: `price_input`, `price_output`, `price_blended`
- speed/latency: `speed`, `ttfc`, `e2e`
- context: `context_window_tokens`, `host_api_id`


## Coding rows

`coding` returns model rows from the Coding capability page while preserving the
CLI/RPC envelopes above. Extraction tolerates both observed source shapes:

- legacy rows: `slug`, `coding_index`, `tokenCounts`, `evalCost`
- current client-rendered RSC rows: `slug`, `headlineValue`, `modelCreator`,
  `shortName`, `isReasoning`, `releaseDate`, `isOpenWeights`,
  `outputTokensPerTask`, `costPerTask`, `evalCost`, `timePerTaskSeconds`

The row's Coding Index score is retained when present even if optional task
metrics are absent. Missing optional evidence is represented by `null` or an
omitted key; rows are not discarded merely because token, cost, or time
evidence is missing. Existing row keys remain compatible; the
`coding_task_metrics` object is additive.

### Coding Index scope

- `coding` is the Coding Index score (`headlineValue` in current rows,
  `coding_index` in legacy rows).
- The score is scoped to the Coding Index evaluation: Terminal-Bench v2.1 and
  SciCode. Component scores are pass-through evidence only; missing component
  scores are not synthesized.
- `coding_token_counts` and `coding_eval_cost`, when present from legacy
  evidence, remain Coding-evaluation values rather than global Intelligence
  Index values.

### Optional task metrics

When the current source provides them, `coding_task_metrics` contains only
observed evidence:

- `output_tokens_per_task`: object derived from `outputTokensPerTask`, with
  `output_tokens`, `answer_tokens`, and `reasoning_tokens`, each a token count
  **per benchmark task**. Input-token counts are not inferred.
- `cost_per_task_usd`: object derived from `costPerTask`, with `total_cost`,
  `input_cost`, `non_cache_input_cost`, `cache_read_cost`,
  `cache_write_cost`, `output_cost`, `reasoning_cost`, and `answer_cost`, each
  **Coding evaluation/API USD per benchmark task**.
- `time_per_task_seconds`: scalar derived from `timePerTaskSeconds`; weighted
  decode time in **seconds per benchmark task**.

These costs are Coding evaluation/API USD measurements, not ChatGPT or Codex
subscription-plan quota, allowance, or billing values; no plan-quota
equivalence or conversion is implied.

## Dedicated evaluation rows

`evaluation` reads a public dedicated evaluation page or a saved HTML/RSC
response. It returns:

- `source`: URL/path, HTTP status, fetch timestamp, and content type;
- `filters_applied`: minimum rows, optional sort path/order, and limit;
- `counts`: parsed frames, matched rows, and returned rows;
- `rows`: the largest recognizable list of model identity + numeric score rows

Rows preserve source fields and have `value_status=published`. Sorting, limiting,
and arithmetic performed after extraction are derived operations. Unknown fields
are retained; benchmark-specific normalization belongs outside this generic
extractor.

## Reasoning rows

`reasoning` rows per unique model:

```json
[
  {
    "rank": 1,
    "model_slug": "minimax-m3",
    "model_name": "MiniMax-M3",
    "creator": "MiniMax",
    "reasoning_model": true,
    "is_open_weights": true,
    "release_date": "2026-06-01",
    "context_window_tokens": 1000000,
    "intelligence": 44.44,
    "agentic": 68.62,
    "coding": 43.41,
    "harness": 56.01,
    "reasoning_profile": {
      "reasoning_floor": 0.001,
      "reasoning_floor_benchmark": "briefcase",
      "reasoning_ceiling": 0.978,
      "reasoning_ceiling_benchmark": "hle",
      "selectivity_score": 0.977,
      "weighted_reasoning_share": 0.8928,
      "classification": "selective_extreme",
      "benchmark_count": 13
    }
  }
]
```

With `--benchmarks`, each row also includes `per_benchmark`:

```json
"per_benchmark": [
  {"benchmark": "briefcase", "answer_tokens": 7448234, "reasoning_tokens": 4416, "output_tokens": 7452650, "reasoning_share": 0.0006},
  {"benchmark": "terminalbench_hard", "answer_tokens": 761966, "reasoning_tokens": 33713, "output_tokens": 795679, "reasoning_share": 0.0424}
]
```

Classifications:
- `selective_extreme`: floor < 10% and range > 75pp
- `selective`: floor < 25% and range > 60pp
- `moderate`: 25% ≤ floor < 50%
- `uniform_heavy`: floor ≥ 50% and weighted ≥ 80%
- `hard_uniform_heavy`: floor ≥ 60% and weighted ≥ 85%
