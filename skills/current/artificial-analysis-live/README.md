# artificial-analysis

Read this file when `SKILL.md` omits a required command or flag.

This tool extracts data from the Artificial Analysis model catalog and provider endpoint matrix. It emits deterministic JSON envelopes without human prose.

## Contents

- [Fetch credentials](#fetch-credentials)
- [Entry point](#entry-point)
- [CLI mode](#cli-mode-default)
- [Stats](#stats)
- [Diff](#diff)
- [Compare releases and efforts](#compare-releases-and-efforts)
- [Dedicated evaluation pages](#dedicated-evaluation-pages)
- [Query](#query-modelprovider-benchmark-questions)
- [QA](#qa-minimum-natural-language-command)
- [Schema](#schema)
- [RPC mode](#rpc-mode-jsonl)
- [Contracts and recovery](#contracts-and-recovery)
- [Released additive contracts](#released-additive-contracts)
- [Lightweight tests](#lightweight-tests)

Live `fetch` combines two required sources:

- Provider endpoints from `https://artificialanalysis.ai/leaderboards/providers` with header `RSC: 1`
- Canonical models from `https://artificialanalysis.ai/api/v2/data/llms/models`

## Fetch credentials

Only `fetch` requires `ARTIFICIAL_ANALYSIS_API_KEY`. Commands reading existing snapshots run without credentials. Use a process environment variable, or set `ARTIFICIAL_ANALYSIS_ENV_FILE` to a restricted file path (such as file mode `0600`) outside the skill directory. Do not pass API keys as CLI or RPC arguments.

Do not copy `.env.example` into the skill tree or into a generated tool home. It is a tracked template. Store credentials outside the skill tree. The loader applies process environment variables first, then reads the explicitly configured environment file. Transitional compatibility may inspect ancestor directories for `.env` in older installations, but new setups MUST NOT rely on ancestor discovery or an `AA_LEGACY_DOTENV` environment switch.

Asset sync processes MUST exclude `.env` and other secret files from generated tool directories. `.gitignore` controls Git tracking only; sync exclusion rules must be configured in your deployment scripts.

Compatibility features:

- Match key aliases and structural heuristics during upstream schema drift.
- Cache ETag metadata and reuse payloads on HTTP 304.
- Support last-good fallback with `--stale-policy allow-last-good` or `--allow-stale` (default is `--strict`, which aliases `error`).
- Enforce minimum sanity thresholds with `--min-endpoints` and `--min-providers`.

## Entry point

Run commands through `uv`:

```text
uv run --script <skill-dir>/scripts/cli.py ...
```

## CLI mode (default)

The CLI runs `fetch` by default when no subcommand is specified.

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

Cache and ETag behavior:

- Stores metadata and payload in `~/.cache/artificial-analysis` or `--cache-dir`.
- Sends `If-None-Match` when an ETag exists.
- Reuses cached payload on HTTP 304 responses.
- Fails under the default `error` policy when parsing or sanity checks fail. Opt into fallback with `--stale-policy allow-last-good` or `--allow-stale`. `--strict` aliases `error`.
- Rejects snapshots older than 24 hours when reading the default `<temp-dir>/artifacts/artificial-analysis/full-data.json`. Run `fetch` again or pass an explicit historical snapshot path.

### Snapshot schema v2

`models` is the canonical unique model table. `hosts_models` contains provider and endpoint observations, joining each record to `models` using `model_slug` without repeating model metrics. Model identity, official evaluations, and the official API pricing object belong to canonical models. Provider speed, latency, context, features, classification, and RSC pricing belong to endpoints.

The official API uses a 3:1 model pricing blend. The RSC endpoint feed uses a 7:2:1 endpoint pricing blend. Retain both blends: model pricing applies to the canonical model, and endpoint pricing applies to the provider endpoint.

## Stats

```bash
uv run --script <skill-dir>/scripts/cli.py stats
uv run --script <skill-dir>/scripts/cli.py stats <temp-dir>/artifacts/artificial-analysis/full-data.json --top 20
```

Returns total counts and the top providers sorted by endpoint count.

## Diff

```bash
uv run --script <skill-dir>/scripts/cli.py diff old.json new.json
uv run --script <skill-dir>/scripts/cli.py diff old.json new.json --schema-aware
```

The default output includes legacy endpoint and provider keys. `--schema-aware` adds `schema_diff` with deterministic model and endpoint identities, field and metric changes, evidence, status, freshness, parser, and schema changes, diagnostics, duplicate records, and possible renames. Stable IDs match first. Possible renames set `merge:false` and never merge automatically.

Returns:

- added endpoint slugs
- removed endpoint slugs
- provider endpoint deltas

## Compare releases and efforts

```bash
uv run --script <skill-dir>/scripts/cli.py fetch
uv run --script <skill-dir>/scripts/cli.py compare \
  --select "Muse Spark 1.3" --select "Astra:low,non-reasoning"
```

`compare [snapshot]` reads canonical models from the snapshot. It skips provider endpoint rows. Repeat `--select` for each release. Omit the effort suffix to include every variant published in the source. Add `:effort,effort` to restrict that release.

Release matching uses published names and slugs, preferring exact matches, then unambiguous whole-token substrings. The command fails on missing or ambiguous releases, and on missing requested efforts. It does not return partial comparisons. Effort labels come directly from source data. Non-reasoning models require an explicit false reasoning flag in the source; missing effort metadata does not imply a non-reasoning model.

Rows preserve original model data and unknown fields. Keep published metric units and source scopes distinct. Model token prices measure raw token rates, while benchmark metrics measure task cost. The term all variants refers to models in the fetched catalog.

Translate natural language comparison requests into explicit `--select` arguments. Use `compare` for multi-model comparisons; `qa` handles single-model and single-provider lookups only.

## Dedicated evaluation pages

Use `evaluation` for standalone public benchmark pages. The parser processes standard RSC responses and embedded Next.js Flight payloads without assuming a benchmark-specific row schema:

```bash
uv run --script <skill-dir>/scripts/cli.py evaluation \
  https://artificialanalysis.ai/evaluations/<benchmark-slug> \
  --sort-by score --order desc --limit 25 \
  --output-json <temp-dir>/benchmark.json
```

Replay a saved page response:

```bash
uv run --script <skill-dir>/scripts/cli.py evaluation \
  --input <temp-dir>/evaluation.html
```

The result preserves source metadata and unknown row fields. Page rows contain published values, while sorting, limiting, and summary arithmetic are derived. Generic evaluation extraction depends on upstream page structure and may not parse unsupported page layouts.

Live pages with a public catalog manifest load the full model population. Saved HTML replay runs offline and marks output as initial coverage. The manifest decoder uses `cryptography`, installed in the PEP 723 script environment.

Check benchmark population, task count, repeat counts, test harness details, and metric scope before combining a dedicated evaluation score with official model snapshot metrics. See `references/evaluation-pages.md` for routing and comparability rules.

## Query (model/provider benchmark questions)

```bash
# model across providers
uv run --script <skill-dir>/scripts/cli.py query --model claude-opus-4-7 --sort-by price_blended --order asc --limit 10

# provider view
uv run --script <skill-dir>/scripts/cli.py query --provider deepinfra --sort-by intelligence --order desc --limit 20
```

Returns provider endpoint rows joined to canonical model metrics, including endpoint pricing, speed, latency, and context window limits.

## QA (minimum natural-language command)

```bash
# model + metric inferred from question
uv run --script <skill-dir>/scripts/cli.py qa "best provider for claude opus 4.7 by speed top 3"

# provider + cheapest inferred
uv run --script <skill-dir>/scripts/cli.py qa "cheapest deepinfra top 5"
```

Returns parsed intent and delegated `query` output in one JSON object. Use `compare` when questions compare multiple models or use words such as versus or against.

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
- `evaluation`
- `query`
- `compare`
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

- `references/command-routing.md`
- `references/evaluation-pages.md`
- `references/output-contract.md`
- `references/troubleshooting.md`

## Released additive contracts

### Freshness and evidence

Fetch and reader payloads use explicit freshness modes:

- `fresh`: HTTP 200 response with parsed live data.
- `cache-revalidated`: HTTP 304 response reusing cached payload.
- `stale-last-good`: Outage fallback setting `stale:true` and `fallback:true`, preserving existing cache without overwriting.
- `snapshot`: Explicit local input file setting `historical:true`.

Machine-readable metrics may include additive `metric_evidence` containing raw and normalized values, unit and normalization metadata, source path, parser version, artifact hash, `value_status`, `metric_semantics_status`, and `comparison_eligibility`. When values are missing, placeholder, malformed, boolean, non-finite, out of range, semantically unknown, or conflicting duplicates, the extractor leaves them visible and blocked from ranking. It does not synthesize replacement values.

### Diagnostics, errors, and artifacts

`diagnose [snapshot] --cache-dir <dir>` runs offline without network requests. It reports redacted health status for snapshot, cache, schema, parser, freshness, artifact, and diagnostic components. In RPC mode, `diagnose` returns one response per input line.

CLI success output follows protocol v1: `{"ok":true,"version":"1","command":...,"data":...}`. Pass `--json-errors` to emit one compact redacted error object on stdout. Omit `--json-errors` or pass `--legacy-errors` to emit human-readable error messages on stderr. RPC mode emits one response per non-empty line with structured error codes.

Raw source bytes are content addressed under `<cache>/artifacts/<sha256>.raw` alongside redacted metadata sidecars. Immutable manifests are written atomically under `<cache>/manifests/<sha256>.json`. Legacy mutable cache files serve as fallback inputs and receive an unverified status label when promoted.

### Filter and URL boundaries

`filter_agent_models.py` reads canonical v2 `models` first, joins endpoint observations on `model_slug`, and emits diagnostics for missing joins. JSON and source artifacts preserve unknown fields. Markdown and TSV formats provide fixed named views. Public `evaluation` URLs require HTTPS and strip query parameters containing credentials. Use `--input` for deterministic local HTML or RSC replay.

## Lightweight tests

```bash
uv run --with pytest pytest -q tests
```
