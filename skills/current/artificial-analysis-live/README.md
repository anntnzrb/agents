# artificial-analysis

Read this when the `SKILL.md` fast path omits a required command or flag.

AI-only extractor for the Artificial Analysis model catalog and provider-endpoint
matrix.

No human prose output. JSON only. Deterministic envelopes.

Live `fetch` combines two required sources:

- provider endpoints from `https://artificialanalysis.ai/leaderboards/providers`
  with header `RSC: 1`
- canonical models from `https://artificialanalysis.ai/api/v2/data/llms/models`

## Fetch credentials

Only `fetch` requires `ARTIFICIAL_ANALYSIS_API_KEY`; commands that read an existing
snapshot do not. Prefer a process-injected key, or set
`ARTIFICIAL_ANALYSIS_ENV_FILE` to a permissions-restricted dotenv file (for
example, mode `0600`) outside the skill tree. Do not pass keys as CLI or RPC
arguments.

Do not copy `.env.example` into the skill tree or a generated tool home. It is a
tracked template, not a secret store. Process values win, then the explicitly
supplied external env file is read. Older installations may discover a skill-root
or ancestor `.env`; that lookup is transitional compatibility only and is not
supported for new setups. This release does not expose an `AA_LEGACY_DOTENV`
switch, so do not rely on one.

The asset-sync owner MUST exclude `.env` and other secret files from generated
tool homes. `.gitignore` only controls Git tracking; it cannot enforce sync
exclusion.

Compatibility hardening:

- key aliases + structural heuristics for upstream schema drift
- ETag cache + 304 reuse
- last-good fallback (opt-in with `--stale-policy allow-last-good` or
  `--allow-stale`; `--strict` aliases `error`)
- sanity thresholds (`min_endpoints`, `min_providers`)

## Entry point

Cross-platform:

```text
uv run --script <skill-dir>/scripts/cli.py ...
```

## CLI mode (default)

Default command is `fetch` when omitted.

```bash
uv run --script <skill-dir>/scripts/cli.py
uv run --script <skill-dir>/scripts/cli.py fetch
```

Returns one JSON envelope on stdout and writes:

- `<temp-dir>/artifacts/artificial-analysis/full-data.json`
- `<temp-dir>/artifacts/artificial-analysis/endpoints.txt`
- `<temp-dir>/artifacts/artificial-analysis/full-url.txt`

### Fetch flags

```bash
uv run --script <skill-dir>/scripts/cli.py fetch \
  --output-json <temp-dir>/full-data.json \
  --output-endpoints <temp-dir>/endpoints.txt \
  --output-url <temp-dir>/full-url.txt \
  --cache-dir <temp-dir>/aa-cache \
  --timeout-seconds 60 \
  --min-endpoints 700 \
  --min-providers 40 \
  --strict
```

Cache/ETag behavior:

- stores metadata + payload in `~/.cache/artificial-analysis` (or `--cache-dir`)
- sends `If-None-Match` when ETag exists
- on `304`, reuses cached payload
- when fresh parsing or sanity checks fail, the default `error` policy fails;
  `--stale-policy allow-last-good` or `--allow-stale` explicitly enables a
  `stale-last-good` fallback, while `--strict` remains the `error` alias
- default `<temp-dir>/artifacts/artificial-analysis/full-data.json` readers reject snapshots older than 24h; run `fetch` again or pass an explicit historical snapshot path

### Snapshot schema v2

`models` is the sole canonical, unique model table. `hosts_models` contains
provider/endpoint observations and joins each one to `models` through
`model_slug`; it does not repeat model metrics. Model identity, official
evaluations, and the official API pricing object belong to canonical models.
Provider speed, latency, context, feature, classification, and RSC pricing belong
to endpoints.

The official API's 3:1 model-pricing blend and RSC's 7:2:1 endpoint-pricing blend
are both retained deliberately: one is model-scoped and the other is
provider-endpoint-scoped.

## Stats

```bash
uv run --script <skill-dir>/scripts/cli.py stats
uv run --script <skill-dir>/scripts/cli.py stats <temp-dir>/artifacts/artificial-analysis/full-data.json --top 20
```

Returns counts + top providers by endpoint count.

## Diff

```bash
uv run --script <skill-dir>/scripts/cli.py diff old.json new.json
uv run --script <skill-dir>/scripts/cli.py diff old.json new.json --schema-aware
```

The default keeps the legacy endpoint/provider keys. `--schema-aware` adds
`schema_diff` with deterministic model and endpoint identities, field/metric
changes, evidence/status/freshness/parser/schema changes, diagnostics, duplicate
records, and possible renames. Stable IDs match first; a possible rename has
`merge:false` and is never merged.

Returns:

- added endpoint slugs
- removed endpoint slugs
- provider endpoint deltas

`type` supports:

- `ping`
- `get_schema` (alias: `schema`)
- `fetch`
- `stats`
- `diff` (`schema_aware:true` is additive)
- `diagnose` (offline snapshot/cache health)
- `harness`
- `coding`
- `evaluation`
- `query`
- `qa`

## Harness

Rank unique models by Harness, a coding-agent score that avoids Intelligence Index benchmark soup:

```text
Harness = 0.5 * Agentic Index + 0.5 * Coding Index
Execution Gap = Agentic Index - Coding Index
```

```bash
uv run --script <skill-dir>/scripts/cli.py harness --limit 25
uv run --script <skill-dir>/scripts/cli.py harness --creator anthropic --limit 10
uv run --script <skill-dir>/scripts/cli.py harness --open-weights-only --limit 25
uv run --script <skill-dir>/scripts/cli.py query --sort-by harness --order desc --limit 20
```

Use `Harness` for model picking. Use `Execution Gap` as a risk flag: large positive gaps mean the model may pursue tasks well but have weaker executable/code precision.

## Coding Index token composition

Fetches `https://artificialanalysis.ai/models/capabilities/coding` directly. No long `models=` URL required.

```bash
uv run --script <skill-dir>/scripts/cli.py coding --limit 25
uv run --script <skill-dir>/scripts/cli.py coding --model gpt-5-5 --include-benchmark-counts
uv run --script <skill-dir>/scripts/cli.py coding --sort-by output_tokens --order desc --limit 10
```

Returns unique model rows with `coding_token_counts`:

- scope: `coding_index_only`
- `input_tokens`
- `answer_tokens`
- `reasoning_tokens`
- `output_tokens = answer_tokens + reasoning_tokens`
- answer/reasoning output shares

Important: these counts are tied to the Coding Index capability evaluation, not global `intelligence_index_token_counts`. The current Coding Index components are Terminal-Bench Hard and SciCode; pass `--include-benchmark-counts` to include each component's token counts.

## Dedicated evaluation pages

Use `evaluation` for a standalone public benchmark page. It parses standard RSC
responses and embedded Next.js Flight payloads without assuming a benchmark-specific
row schema:

```bash
uv run --script <skill-dir>/scripts/cli.py evaluation \
  https://artificialanalysis.ai/evaluations/terminalbench-v2-1 \
  --sort-by score --order desc --limit 25 \
  --output-json <temp-dir>/terminalbench.json
```

Replay a saved page response:

```bash
uv run --script <skill-dir>/scripts/cli.py evaluation \
  --input <temp-dir>/evaluation.html
```

The result preserves source metadata and unknown row fields. Page rows are
published values; sorting, limiting, and arithmetic are derived. Do not merge a
dedicated evaluation score with the Coding Index or Coding Agent Index without
checking benchmark population, task count, repeats, harness, and metric scope.
See `references/evaluation-pages.md` for routing and comparability rules.

## Query (model/provider benchmark questions)

```bash
# model across providers
uv run --script <skill-dir>/scripts/cli.py query --model claude-opus-4-7 --sort-by price_blended --order asc --limit 10

# provider view
uv run --script <skill-dir>/scripts/cli.py query --provider deepinfra --sort-by intelligence --order desc --limit 20
```

Returns provider-endpoint rows joined to canonical model metrics, with endpoint
pricing, speed/latency, and context.

## QA (minimum natural-language command)

```bash
# model + metric inferred from question
uv run --script <skill-dir>/scripts/cli.py qa "best provider for claude opus 4.7 by speed top 3"

# provider + cheapest inferred
uv run --script <skill-dir>/scripts/cli.py qa "cheapest deepinfra top 5"
```

It returns parsed intent + delegated `query` result in one JSON object.

## Schema

```bash
uv run --script <skill-dir>/scripts/cli.py schema
```

## RPC mode (JSONL)

Start loop:

```bash
uv run --script <skill-dir>/scripts/cli.py --mode rpc
```

### Request format

```json
{ "id": "1", "type": "fetch", "args": { "strict": false } }
```

`type` supports:
- `ping`
- `get_schema` (alias: `schema`)
- `fetch`
- `stats`
- `diff` (`schema_aware:true` is additive)
- `diagnose` (offline snapshot/cache health)
- `harness`
- `coding`
- `evaluation`
- `query`
- `qa`

### Response format

Success:

```json
{"id":"1","type":"response","command":"fetch","success":true,"data":{...}}
```

Error:

```json
{
  "id": "1",
  "type": "response",
  "command": "fetch",
  "success": false,
  "error": { "code": "...", "message": "..." }
}
```

### RPC example

```bash
printf '%s\n' \
  '{"id":"1","type":"ping"}' \
  '{"id":"2","type":"fetch","args":{"min_endpoints":700,"min_providers":40}}' \
  '{"id":"3","type":"stats","args":{"top":5}}' \
  '{"id":"4","type":"query","args":{"model":"claude-opus-4-7","sort_by":"price_blended","order":"asc","limit":5}}' \
  '{"id":"5","type":"qa","args":{"question":"best provider for claude opus 4.7 by speed top 3"}}' \
  | uv run --script <skill-dir>/scripts/cli.py --mode rpc
```

## Contracts and recovery

- `references/output-contract.md`
- `references/troubleshooting.md`

## Released additive contracts

### Freshness and evidence

Fetch and reader payloads use explicit freshness modes:

- `fresh`: successful 200 response;
- `cache-revalidated`: validated 304/body reuse, not stale;
- `stale-last-good`: explicit outage fallback with `stale:true`, `fallback:true`,
  source/reason/hash metadata, and no cache overwrite;
- `snapshot`: explicit local input with `historical:true`, not outage-stale.

Machine-readable metrics may retain additive `metric_evidence` with raw and
normalized values, unit/normalization, source path/field, parser/version,
artifact hash, `value_status`, `metric_semantics_status`, and
`comparison_eligibility`. Missing, placeholder, malformed, boolean, non-finite,
out-of-range, unknown-semantics, or conflicting-duplicate values remain visible
and blocked rather than synthesized.

### Diagnostics, errors, and artifacts

`diagnose [snapshot] --cache-dir <dir>` is offline and never fetches. It reports
redacted snapshot/cache/schema/parser/freshness/artifact/diagnostic health.
RPC diagnose returns one response per input line.

CLI success remains protocol v1:
`{"ok":true,"version":"1","command":...,"data":...}`. During error migration,
`--json-errors` emits exactly one compact redacted object on stdout; omit it (or
pass `--legacy-errors`) for human-readable stderr compatibility. RPC preserves
one response per non-empty line and its existing error codes.

Raw source bytes are content-addressed under `<cache>/artifacts/<sha256>.raw`
with redacted metadata sidecars; immutable manifests live under
`<cache>/manifests/<sha256>.json` and are atomically written. Legacy mutable
cache files are compatibility inputs and are marked unverified when promoted.

### Filter and URL boundaries

`filter_agent_models.py` reads canonical v2 `models` first, joins endpoint
observations through `model_slug`, and emits diagnostics for missing joins.
JSON/source artifacts preserve unknown fields; Markdown and TSV are fixed named
views. Public `evaluation` URLs require HTTPS and redact credential query
parameters; use `--input` for deterministic local HTML/RSC replay.

## Lightweight tests

```bash
uv run --with pytest pytest -q tests
```
