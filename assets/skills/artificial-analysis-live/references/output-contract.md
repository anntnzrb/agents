# artificial-analysis output contract

All command outputs are JSON.

## CLI envelope

```json
{"ok":true,"version":"1","command":"fetch|stats|diff|query|qa|coding|schema","data":{...}}
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

## Snapshot JSON structure

Top-level keys:

- `meta`
- `models`
- `hosts`
- `hosts_models`

`meta` includes:

- `schema_version`
- `source_url`
- `source_mode`
- `fetched_at`
- `status_code`
- `etag`
- `counts`

`counts` includes:

- `models`
- `hosts`
- `hosts_models`
- `endpoint_slugs`
- `providers_by_prefix`
- `providers`
- `frames`

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