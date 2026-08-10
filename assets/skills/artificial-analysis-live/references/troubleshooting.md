# artificial-analysis troubleshooting

Read this when credentials, extraction, freshness, caching, or upstream requests fail.

## 1) Fresh fetch or capability command fails after upstream change

Symptoms:

- `extraction_error` with missing sections
- a capability command returns no rows after its page changed

Mitigations already built-in:

- key alias matching (`hostsModels`, `host_models`, `endpoints`);
- structural heuristics for list detection;
- refresh default policy `error`; `--strict` is its compatibility alias;
- explicit last-good fallback only with `--allow-stale` or
  `--stale-policy allow-last-good`, marked `stale-last-good`.

Actions:

1. keep the default policy for current-data questions; do not silently answer
   with a stale last-good artifact;
2. inspect `schema` and `diagnose --snapshot <path> --cache-dir <dir>`;
3. for `coding`, follow `capability-schema-drift.md` before changing extraction;
4. inspect the current public RSC payload and add the smallest alias/structural
   repair;
5. add offline legacy/current/negative fixtures and validate one gated live
   command only after credential rotation.

## 2) 304, validator, or artifact integrity failure

Symptoms:

- `Upstream returned 304 but no cached payload is available`;
- a validator does not match cached bytes;
- an immutable artifact or manifest is missing/tampered.

Fix:

- use a clean cache directory and retry a fresh fetch;
- run `diagnose --cache-dir <dir>` to inspect redacted hashes, sidecars,
  manifests, and validator state;
- never edit content-addressed `.raw`, sidecar, or manifest files in place.
  A failed integrity check must fail closed.

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

## 6) Freshness, diagnostics, and security checklist

- `fresh` is a successful current response; `cache-revalidated` is validated
  304 reuse; `stale-last-good` requires explicit stale policy; `snapshot` is an
  explicit local/historical input.
- Use `diff --schema-aware` for additive model/metric/evidence/status/schema and
  duplicate changes; default diff keys remain stable.
- Use `--json-errors` for one compact redacted CLI error object, or
  `--legacy-errors` during migration. RPC keeps one response per request.
- Pass `ARTIFICIAL_ANALYSIS_API_KEY` through the process environment, or set
  `ARTIFICIAL_ANALYSIS_ENV_FILE` to a permissions-restricted file outside the
  skill tree, never CLI/RPC. Older installations may discover a skill-root or
  ancestor `.env`; that lookup is transitional compatibility only, not supported
  setup.
- The asset-sync owner MUST exclude `.env` and other secret files from generated
  homes. `.gitignore` only controls Git tracking; it cannot enforce sync
  exclusion.
- `evaluation` requires HTTPS; use `--input` for local replay. Never retain
  authorization/cookie headers or raw dotenv values in artifacts.
