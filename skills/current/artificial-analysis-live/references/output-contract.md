# artificial-analysis output contract

All command outputs: JSON.

## CLI

```json
{"ok":true,"version":"1","command":"fetch|stats|diff|diagnose|harness|coding|evaluation|reasoning|query|qa|schema","data":{...}}
```

One documented CLI entry point; omitted command → `fetch`. Add flags or commands only; retain `fetch`, `stats`, `diff`, `diagnose`, `harness`, `coding`, `evaluation`, `reasoning`, `query`, `qa`, `schema`; never rename/remove the entry point or a command. Success MUST retain `ok: true`, string `version: "1"`, `command`, `data` and their types; additions MUST NOT rename, remove, or retype them.

Default artifacts: `<temp-dir>/artifacts/artificial-analysis/{full-data.json,endpoints.txt,full-url.txt}`. Preserve these paths; custom output paths opt-in.

Snapshot v2: `meta.schema_version: 2`; top-level `models`, `hosts`, `hosts_models`; `hosts_models` slim and joined by `model_slug`. Add fields/projections only; preserve v2 keys and join.

Pricing scopes stay distinct: model/API `price_1m_blended_3_to_1`; endpoint/RSC `price_1m_blended_7_to_2_to_1`. Never merge, rename, or reinterpret them.

Malformed source envelopes/rows remain rejected. `fetch --strict`: no-fallback mode. Preserve rejection/fallback semantics; reconciliation MUST be versioned and additive.

### Freshness

Every refresh/reader result distinguishes these modes:

- `fresh`: successful current source response; `stale:false`, `historical:false`.
- `cache-revalidated`: validated 304/body reuse; `stale:false`; never outage-stale.
- `stale-last-good`: explicit `--allow-stale` or `--stale-policy allow-last-good` fallback; `stale:true`, `fallback:true`.
- `snapshot`: explicit local input; `historical:true`, `stale:false`.

Default refresh policy: `error`; `--strict` remains its compatibility alias. Default output snapshot retains its 24-hour reader guard. Stale fallback NEVER overwrites current cache bytes. Explicitly named old paths are historical snapshots, not stale outage fallbacks.

## RPC

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

## Fetch credentials and secrets

Only `fetch` requires `ARTIFICIAL_ANALYSIS_API_KEY`. Prefer a process-injected key, or `ARTIFICIAL_ANALYSIS_ENV_FILE` pointing to a permissions-restricted dotenv file (e.g. mode `0600`) outside the skill tree. The key is never a CLI/RPC argument.

NEVER copy `.env.example` into the skill tree or generated tool home: it is a tracked template, not a secret store. Precedence: process values, then explicitly supplied external env file. Skill-root/ancestor `.env` discovery is transitional compatibility only and unsupported for new setups. This release has no `AA_LEGACY_DOTENV`; do not rely on it.

Asset-sync owner MUST exclude `.env` and other secret files from generated tool homes. `.gitignore` controls Git tracking only; it CANNOT enforce sync exclusion.

## Snapshot JSON v2

Top-level keys: `meta`, `models`, `hosts`, `hosts_models`.

`meta`: `schema_version: 2`, `counts`, `sources`. `sources.rsc` and `sources.official_api`: source URL, status code, fetched-at timestamp, supplied ETag, and applicable `reused_cached_payload`; never credentials or raw response bodies. `counts`: unique canonical `models`, `hosts`, endpoint `hosts_models`, plus available endpoint/provider sanity counts.

`models` is the only model projection: exactly one canonical row per `slug`; official API identity, evaluations, and API pricing belong here. `hosts_models` is a slim provider-endpoint table: each row has `model_slug` joining the canonical model and retains endpoint/provider pricing, speed, latency, context, features, and classifications; it MUST NOT embed a `model` object.

The model API's 3:1 blend and RSC endpoint's 7:2:1 blend intentionally coexist: model and provider-endpoint scopes, not duplicate prices.

## Evidence, statuses, eligibility

Named scalar fields remain stable. Additive `metric_evidence.<metric>` records: `raw_value`, `normalized_value`, `unit`, `normalization`, `source_path`, `source_field`, `value_status`, `metric_semantics_status`, `comparison_eligibility`, `blocked_reasons`, `parser`, `parser_version`, and available `artifact_id`/`sha256`.

`value_status`: `published|derived|missing|unparsed`. `metric_semantics_status`: `known|unknown|ambiguous`. `comparison_eligibility`: `eligible|blocked`.

Placeholders, booleans, non-finite/malformed/out-of-range values, unknown semantics, unit/scope/release mismatches, and conflicting duplicates remain visible with reasons; they MUST NOT become fake zeroes or eligible comparisons. Derived fields retain formulas and input paths and never replace published values. Unknown source keys survive under `raw_fields`/`raw_metadata`.

## Diagnostics, diff, errors

`diagnose`: explicit local snapshot/cache paths only; NEVER fetches. Report: redacted schema/parser/freshness/source/cache/artifact health and diagnostics.

`diff --schema-aware` or RPC `schema_aware:true`: add `schema_diff` while preserving every legacy endpoint/provider key. Stable IDs match first; possible rename suggestions carry `merge:false`.

CLI success remains protocol v1. RPC emits one response per non-empty input line with existing error codes. During staged migration, `--json-errors` emits one compact redacted CLI error object on stdout; `--legacy-errors` retains human-readable stderr. Neither form contains credentials.

## Immutable artifacts and URL policy

Raw source bytes: content-addressed under `<cache>/artifacts/`, with redacted metadata sidecars. Immutable manifests: atomically written under `<cache>/manifests/`. Legacy mutable cache inputs promoted as `legacy_unverified`.

`evaluation <url>`: HTTPS only; redact credential query parameters. Local/deterministic replay: `evaluation --input <file>`.

## QA and query

`qa` returns `question`, `parsed_intent` (`model`, `provider`, `sort_by`, `order`, `limit`), and full `query` payload.

Each `query` row MAY contain nulls for upstream-unprovided metrics. High-signal fields:

- identity: `endpoint_slug`, `model_slug`, `provider_slug`
- quality: `intelligence`, `coding`, `math`, `gpqa`, `mmlu_pro`, `ifbench`, `scicode`, `tau2`
- economics: `price_input`, `price_output`, `price_blended`
- speed/latency: `speed`, `ttfc`, `e2e`
- context: `context_window_tokens`, `host_api_id`

## Coding

`coding` returns Coding capability-page model rows under the CLI/RPC envelopes. Extraction tolerates both shapes:

- legacy: `slug`, `coding_index`, `tokenCounts`, `evalCost`
- current client-rendered RSC: `slug`, `headlineValue`, `modelCreator`, `shortName`, `isReasoning`, `releaseDate`, `isOpenWeights`, `outputTokensPerTask`, `costPerTask`, `evalCost`, `timePerTaskSeconds`

Retain Coding Index when present even if optional task metrics are absent. Missing optional evidence → `null` or omitted key; do not discard rows for missing token/cost/time evidence. Existing row keys remain compatible; `coding_task_metrics` additive.

### Coding Index scope

- `coding`: Coding Index score (`headlineValue` current, `coding_index` legacy).
- Scope: Coding Index evaluation, Terminal-Bench v2.1 and SciCode. Component scores pass through only; never synthesize missing components.
- Legacy `coding_token_counts`/`coding_eval_cost`, when present, remain Coding-evaluation values, not global Intelligence Index values.

### Optional task metrics

When current source provides them, `coding_task_metrics` contains observed evidence only:

- `output_tokens_per_task`: derived from `outputTokensPerTask`; `output_tokens`, `answer_tokens`, `reasoning_tokens`, each token count **per benchmark task**. Never infer input-token counts.
- `cost_per_task_usd`: derived from `costPerTask`; `total_cost`, `input_cost`, `non_cache_input_cost`, `cache_read_cost`, `cache_write_cost`, `output_cost`, `reasoning_cost`, `answer_cost`, each **Coding evaluation/API USD per benchmark task**.
- `time_per_task_seconds`: derived from `timePerTaskSeconds`; weighted decode time in **seconds per benchmark task**.

These are Coding evaluation/API USD measurements, not ChatGPT/Codex subscription-plan quota, allowance, or billing values; imply no plan-quota equivalence or conversion.

## Dedicated evaluation

`evaluation` reads a public dedicated evaluation page or saved HTML/RSC response and returns:

- `source`: URL/path, HTTP status, fetch timestamp, content type
- `filters_applied`: minimum rows, optional sort path/order, limit
- `counts`: parsed frames, matched rows, returned rows
- `rows`: largest recognizable list of model-identity + numeric-score rows

Rows preserve source fields and use `value_status=published`. Sorting, limiting, and post-extraction arithmetic are derived. Preserve unknown fields; benchmark-specific normalization stays outside this generic extractor.

## Reasoning

`reasoning` returns one row per unique model:

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
