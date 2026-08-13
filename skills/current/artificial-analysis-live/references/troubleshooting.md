# artificial-analysis troubleshooting

Use when credentials, extraction, freshness, caching, or upstream requests fail.

## Fresh fetch or capability command failure after upstream change

Signals: `extraction_error` with missing sections; capability command returns no rows after page change.

Built-ins: key alias matching `hostsModels`, `host_models`, `endpoints`; structural heuristics for list detection; refresh default policy `error` (`--strict` compatibility alias); explicit last-good fallback only with `--allow-stale` or `--stale-policy allow-last-good`, marked `stale-last-good`.

Actions:
1. For current-data questions, keep the default policy; NEVER silently answer with a stale last-good artifact.
2. Inspect `schema` and `diagnose --snapshot <path> --cache-dir <dir>`.
3. For `coding`, follow `capability-schema-drift.md` before changing extraction.
4. Inspect the current public RSC payload; add the smallest alias/structural repair.
5. Add offline legacy, current, and negative fixtures; after credential rotation, validate one gated live command only.

## 304, validator, or artifact-integrity failure

Signals: `Upstream returned 304 but no cached payload is available`; validator does not match cached bytes; immutable artifact or manifest missing or tampered.

Fix: use a clean cache directory and retry a fresh fetch; run `diagnose --cache-dir <dir>` to inspect redacted hashes, sidecars, manifests, and validator state. NEVER edit content-addressed `.raw`, sidecar, or manifest files in place. A failed integrity check MUST fail closed.

## Inconsistent provider counts

Cause: endpoint slug prefixes may differ from canonical host slugs.
Use `meta.counts.providers_by_prefix` and `meta.counts.providers`.

## Excessive null metrics

Cause: some endpoints/models do not publish all benchmarks.
Sort/filter by metrics known to exist for that family; use multiple queries: quality, then price, then speed.

## Deterministic agent usage

Use RPC mode for pipelines: `--mode rpc`. Pin snapshot path when comparing runs. Use `diff` for change detection. Keep `min-endpoints` and `min-providers` thresholds enabled.

## Freshness, diagnostics, security

Statuses: `fresh` successful current response; `cache-revalidated` validated 304 reuse; `stale-last-good` requires explicit stale policy; `snapshot` explicit local or historical input.

Use `diff --schema-aware` for additive model, metric, evidence, status, schema, and duplicate changes; default diff keys remain stable. Use `--json-errors` for one compact redacted CLI error object, or `--legacy-errors` during migration. RPC keeps one response per request.

Pass `ARTIFICIAL_ANALYSIS_API_KEY` through the process environment, or set `ARTIFICIAL_ANALYSIS_ENV_FILE` to a permissions-restricted file outside the skill tree; NEVER pass either via CLI/RPC. Older installations may discover a skill-root or ancestor `.env`; that lookup is transitional compatibility only, not supported setup.

The asset-sync owner MUST exclude `.env` and other secret files from generated homes. `.gitignore` controls Git tracking only; it cannot enforce sync exclusion.

`evaluation` requires HTTPS; use `--input` for local replay. NEVER retain authorization or cookie headers, or raw dotenv values, in artifacts.
