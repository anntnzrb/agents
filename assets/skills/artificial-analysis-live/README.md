# artificial-analysis

AI-only extractor for the full Artificial Analysis provider-endpoint matrix.

No human prose output. JSON only. Deterministic envelopes.

Compatibility hardening:
- key aliases + structural heuristics for upstream schema drift
- ETag cache + 304 reuse
- last-good fallback (unless `--strict`)
- sanity thresholds (`min_endpoints`, `min_providers`)

Source: `https://artificialanalysis.ai/leaderboards/providers` with header `RSC: 1`.

## CLI mode (default)

Default command is `fetch` when omitted.

```bash
cd artificial-analysis
uv run artificial-analysis
uv run artificial-analysis fetch
```

Returns one JSON envelope on stdout and writes:

- `artifacts/artificial-analysis/full-data.json`
- `artifacts/artificial-analysis/endpoints.txt`
- `artifacts/artificial-analysis/full-url.txt`

### Fetch flags

```bash
uv run artificial-analysis fetch \
  --output-json /tmp/full-data.json \
  --output-endpoints /tmp/endpoints.txt \
  --output-url /tmp/full-url.txt \
  --cache-dir /tmp/aa-cache \
  --timeout-seconds 60 \
  --min-endpoints 700 \
  --min-providers 40 \
  --strict
```

Cache/ETag behavior:

- stores metadata + payload in `~/.cache/artificial-analysis` (or `--cache-dir`)
- sends `If-None-Match` when ETag exists
- on `304`, reuses cached payload
- if fresh parse fails sanity and not `--strict`, falls back to last-good snapshot

## Stats

```bash
uv run artificial-analysis stats
uv run artificial-analysis stats artifacts/artificial-analysis/full-data.json --top 20
```

Returns counts + top providers by endpoint count.

## Diff

```bash
uv run artificial-analysis diff old.json new.json
```

Returns:

- added endpoint slugs
- removed endpoint slugs
- provider endpoint deltas

## Query (model/provider benchmark questions)

```bash
# model across providers
uv run artificial-analysis query --model claude-opus-4-7 --sort-by price_blended --order asc --limit 10

# provider view
uv run artificial-analysis query --provider deepinfra --sort-by intelligence --order desc --limit 20
```

Returns endpoint rows with pricing, speed/latency, and benchmark metrics.

## QA (minimum natural-language command)

```bash
# model + metric inferred from question
uv run artificial-analysis qa "best provider for claude opus 4.7 by speed top 3"

# provider + cheapest inferred
uv run artificial-analysis qa "cheapest deepinfra top 5"
```

It returns parsed intent + delegated `query` result in one JSON object.

## Schema

```bash
uv run artificial-analysis schema
```

Returns machine-readable capability schema JSON.

## RPC mode (JSONL)

Start loop:

```bash
uv run artificial-analysis --mode rpc
```

### Request format

```json
{"id":"1","type":"fetch","args":{"strict":false}}
```

`type` supports:

- `ping`
- `get_schema` (alias: `schema`)
- `fetch`
- `stats`
- `diff`
- `query`
- `qa`

### Response format

Success:

```json
{"id":"1","type":"response","command":"fetch","success":true,"data":{...}}
```

Error:

```json
{"id":"1","type":"response","command":"fetch","success":false,"error":{"code":"...","message":"..."}}
```

### RPC example

```bash
printf '%s\n' \
  '{"id":"1","type":"ping"}' \
  '{"id":"2","type":"fetch","args":{"min_endpoints":700,"min_providers":40}}' \
  '{"id":"3","type":"stats","args":{"top":5}}' \
  '{"id":"4","type":"query","args":{"model":"claude-opus-4-7","sort_by":"price_blended","order":"asc","limit":5}}' \
  '{"id":"5","type":"qa","args":{"question":"best provider for claude opus 4.7 by speed top 3"}}' \
  | uv run artificial-analysis --mode rpc
```

## Contracts and recovery

- `references/output-contract.md`
- `references/troubleshooting.md`

## Lightweight tests

```bash
uv run python -m unittest discover -s tests -q
```
