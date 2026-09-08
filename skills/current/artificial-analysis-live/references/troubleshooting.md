# artificial-analysis troubleshooting

Use when credentials, extraction, freshness, caching, or upstream requests fail.

## Missing credentials or uncertain effort variants

- When an authorized API key is unavailable, use the public `evaluation` route if its scope answers the query. Snapshot readers require an existing snapshot file; label explicit historical input accordingly.
- For variant discovery, run `compare --select "<release>"` against a fresh snapshot. When release metadata is unavailable, inspect the official models catalog or model page. Associate release and effort records using containing objects or explicit identifiers. Do not associate records by text proximity.
- Treat catalog shapes and effort ladders as unversioned. Record the published model identifier, effort label, source URL, and retrieval date. Do not treat a bare slug as maximum or default effort.
- One discovered effort represents one observed entry. It does not establish that other efforts are absent. When the source cannot verify completeness or model identity, report the missing data. Do not synthesize a comparison.
- Keep catalog discovery separate from benchmark scores. Do not assume authenticated API equivalence, extract numbers from garbled text, or search unrelated files for credentials.
- Resolve ambiguous selectors with a more specific published release name or slug. Do not substitute an alternate effort when the requested effort is missing.
- A new field preserved in `raw_fields` indicates payload retention. It does not verify parsed units or equivalence to a metric on a dedicated benchmark page.

## Fresh fetch failure after upstream change

Signals: `extraction_error` with missing sections.

Built-ins: key alias matching for `hostsModels`, `host_models`, and `endpoints`; structural heuristics for list detection; default refresh policy `error` (`--strict` compatibility alias); explicit last-good fallback only with `--allow-stale` or `--stale-policy allow-last-good`, marked `stale-last-good`.

Actions:
1. Keep the default policy for current data queries. NEVER silently return a stale last-good artifact.
2. Run `schema` and `diagnose --snapshot <path> --cache-dir <dir>`.
3. Inspect the current public RSC payload and official API response.
4. Add offline legacy, current, and negative fixtures. After rotating credentials, validate one gated live command only.

## 304, validator, or artifact-integrity failure

Signals: `Upstream returned 304 but no cached payload is available`; validator mismatch against cached bytes; missing or tampered immutable artifact or manifest.

Fix: Use a clean cache directory and retry a fresh fetch. Run `diagnose --cache-dir <dir>` to inspect redacted hashes, sidecars, manifests, and validator state. NEVER edit content-addressed `.raw`, sidecar, or manifest files in place. A failed integrity check MUST fail closed.

## Inconsistent provider counts

Cause: Endpoint slug prefixes can differ from canonical host slugs.
Use `meta.counts.providers_by_prefix` and `meta.counts.providers` to verify counts.

## Excessive null metrics

Cause: Certain endpoints and models omit specific benchmarks.
Filter and sort by metrics published for that model family. Execute sequential queries in order: quality, price, then speed.

## Deterministic agent usage

Use RPC mode for pipelines by passing `--mode rpc`. Pin snapshot paths when comparing runs across workflows. Run `diff` to detect changes. Maintain active `min-endpoints` and `min-providers` thresholds.

## Freshness, diagnostics, security

Statuses: `fresh` indicates a successful current response; `cache-revalidated` indicates validated 304 reuse; `stale-last-good` indicates explicit stale policy fallback; `snapshot` indicates explicit local or historical input.

Run `diff --schema-aware` to inspect additive model, metric, evidence, status, schema, and duplicate changes while preserving default diff keys. Pass `--json-errors` to output a compact redacted CLI error object, or pass `--legacy-errors` during migration. RPC mode returns exactly one response per request.

Provide `ARTIFICIAL_ANALYSIS_API_KEY` through the process environment, or set `ARTIFICIAL_ANALYSIS_ENV_FILE` to a file with restricted permissions outside the skill tree. NEVER pass API keys or environment file paths through CLI or RPC arguments. Automatic discovery of `.env` in skill-root or ancestor directories serves legacy compatibility only.

The asset sync process MUST exclude `.env` and other secret files from generated home directories. A `.gitignore` file controls Git tracking only; it cannot enforce sync exclusion.

The `evaluation` command requires HTTPS URLs. Pass `--input` for local replay of saved artifacts. NEVER retain authorization headers, cookie headers, or raw environment values in artifacts.
