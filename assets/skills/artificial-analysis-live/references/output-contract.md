# artificial-analysis output contract

All command outputs are JSON.

## CLI envelope

```json
{"ok":true,"version":"1","command":"fetch|stats|diff|query|qa|schema","data":{...}}
```

## RPC envelope

Success:

```json
{"id":"...","type":"response","command":"...","success":true,"data":{...}}
```

Error:

```json
{"id":"...","type":"response","command":"...","success":false,"error":{"code":"...","message":"..."}}
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
