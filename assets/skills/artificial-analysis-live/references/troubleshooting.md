# artificial-analysis troubleshooting

Read this when credentials, extraction, freshness, caching, or upstream requests fail.

## 1) Fresh fetch or capability command fails after upstream change

Symptoms:

- `extraction_error` with missing sections
- a capability command returns no rows after its page changed

Mitigations already built-in:

- key alias matching (`hostsModels`, `host_models`, `endpoints`)
- structural heuristics for list detection
- last-good snapshot fallback (unless `--strict`)

Actions:

1. run without `--strict` when the provider snapshot is affected;
2. inspect `schema` output for the public contract;
3. for `coding`, follow `capability-schema-drift.md` before changing extraction;
4. inspect the current public RSC payload and add the smallest alias/structural repair;
5. add offline legacy/current/negative fixtures and validate one live command

## 2) 304 but no cached payload

Symptom:

- `Upstream returned 304 but no cached payload is available`

Fix:

- run with a clean cache dir or remove broken cache files

## 3) Provider counts look inconsistent

Reason:

- endpoint slug prefixes and canonical host slugs may differ

Use:

- `meta.counts.providers_by_prefix`
- `meta.counts.providers`

## 4) Query returns too many null metrics

Reason:

- some endpoints/models do not publish all benchmarks

Fix:

- sort/filter by metrics known to exist for that family
- use multiple queries (quality, then price, then speed)

## 5) Deterministic agent usage checklist

- Use RPC mode for pipelines: `--mode rpc`
- Pin snapshot path when comparing runs
- Use `diff` for change detection
- Keep `min-endpoints`/`min-providers` thresholds enabled
