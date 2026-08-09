# artificial-analysis output contract

All command outputs are JSON.

Read this before consuming CLI/RPC envelopes, snapshot fields, coding evidence, or reasoning metrics.

## CLI envelope

```json
{"ok":true,"version":"1","command":"fetch|stats|diff|query|qa|coding|evaluation|schema","data":{...}}
```

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

Only `fetch` requires `ARTIFICIAL_ANALYSIS_API_KEY`. Set it in a skill-local
`.env` copied from `.env.example`; it is never a CLI or RPC argument. An existing
process value wins, otherwise dotenv lookup is: `ARTIFICIAL_ANALYSIS_ENV_FILE`,
`<skill-root>/.env`, `$SKILLS_DIR/artificial-analysis-live/.env`, then the first
ancestor containing `skills/artificial-analysis-live/.env`.

Generic asset sync intentionally copies dotfiles into every generated tool home,
so a skill-local `.env` is replicated to those managed targets by design.

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
