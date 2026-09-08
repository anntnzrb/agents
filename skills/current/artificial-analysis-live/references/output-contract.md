# artificial-analysis output contract

All CLI and RPC commands output JSON.

## CLI

```json
{"ok":true,"version":"1","command":"fetch|stats|diff|diagnose|evaluation|compare|query|qa|schema","data":{...}}
```

The CLI provides a single entry point. An omitted command defaults to `fetch`. Supported commands are `fetch`, `stats`, `diff`, `diagnose`, `evaluation`, `compare`, `query`, `qa`, and `schema`. Successful execution MUST return `ok: true`, string `version: "1"`, `command`, and `data`.

Default artifacts write to `<temp-dir>/artifacts/artificial-analysis/{full-data.json,endpoints.txt,full-url.txt}` unless an explicit output path is specified.

Snapshot v2 sets `meta.schema_version: 2` and exposes top-level `models`, `hosts`, and `hosts_models`. The `hosts_models` table joins canonical models by `model_slug`.

Model and API scopes record `price_1m_blended_3_to_1`. Endpoint and RSC scopes record `price_1m_blended_7_to_2_to_1`. Keep these pricing fields separate.

Reject malformed source envelopes and rows. Running `fetch --strict` disables fallbacks. Schema reconciliation MUST be versioned and additive.

### Freshness

Every refresh and reader result reports one of four freshness modes:

- `fresh`: successful current source response with `stale: false` and `historical: false`.
- `cache-revalidated`: validated HTTP 304 or body reuse with `stale: false`.
- `stale-last-good`: fallback activated by `--allow-stale` or `--stale-policy allow-last-good`, setting `stale: true` and `fallback: true`.
- `snapshot`: explicit local file input with `historical: true` and `stale: false`.

The default refresh policy is `error`, with `--strict` as a compatibility alias. Default output snapshots apply a 24-hour reader guard. Stale fallbacks MUST NOT overwrite current cache bytes. Historical input files operate in `snapshot` mode.

## RPC

Success response:

```json
{"id":"...","type":"response","command":"...","success":true,"data":{...}}
```

Error response:

```json
{
  "id": "...",
  "type": "response",
  "command": "...",
  "success": false,
  "error": { "code": "...", "message": "..." }
}
```

## Fetch credentials and secrets

Only `fetch` requires `ARTIFICIAL_ANALYSIS_API_KEY`. Supply the key through process environment variables or through `ARTIFICIAL_ANALYSIS_ENV_FILE` pointing to a file with restricted permissions (such as mode `0600`) outside the skill directory. NEVER pass API keys as CLI or RPC arguments.

Do not copy `.env.example` into the skill tree or generated tool homes. Store active credentials in external environment files. Credential resolution checks process environment variables first, then the explicit file in `ARTIFICIAL_ANALYSIS_ENV_FILE`.

Asset synchronization MUST exclude `.env` and other secret files from generated tool homes. Configure sync exclusion rules in addition to `.gitignore`.

## Snapshot JSON v2

Snapshot JSON v2 structures data under four top-level keys: `meta`, `models`, `hosts`, and `hosts_models`.

`meta` contains `schema_version: 2`, `counts`, and `sources`. Fields under `sources.rsc` and `sources.official_api` record the source URL, HTTP status code, fetch timestamp, ETag, and optional `reused_cached_payload`. Exclude credentials and raw response bodies from metadata. `counts` records totals for unique canonical `models`, `hosts`, `hosts_models`, and provider sanity checks.

`models` contains canonical model rows indexed by `slug`. This table records official API identity, benchmark evaluations, and API pricing.

`hosts_models` is a provider-endpoint table. Each row includes `model_slug` to join the canonical model and contains endpoint pricing, speed, latency, context size, features, and classifications. Rows in `hosts_models` MUST NOT embed full `model` objects.

Model pricing uses `price_1m_blended_3_to_1` for API scopes. Provider endpoint pricing uses `price_1m_blended_7_to_2_to_1` for RSC scopes.

## Evidence, statuses, eligibility

Named scalar fields preserve stable keys. The additive `metric_evidence.<metric>` object records metadata for each metric:
- `raw_value` and `normalized_value`
- `unit` and `normalization`
- `source_path` and `source_field`
- `value_status`: `published`, `derived`, `missing`, or `unparsed`
- `metric_semantics_status`: `known`, `unknown`, or `ambiguous`
- `comparison_eligibility`: `eligible` or `blocked`
- `blocked_reasons`
- `parser` and `parser_version`
- `artifact_id` and `sha256` when available

Missing, boolean, placeholder, malformed, out-of-range, and ambiguous metric values MUST retain blocked status with explicit entries in `blocked_reasons`. They MUST NOT convert into zero values or eligible comparisons. Derived fields preserve formulas and input paths alongside published values. Preserve unmapped source attributes under `raw_fields` and `raw_metadata`.

## Diagnostics, diff, errors

The `diagnose` command evaluates local snapshot and cache paths. It MUST NOT make network requests. Output reports redacted schema integrity, parser status, cache health, and artifact diagnostics.

Running `diff --schema-aware` or passing RPC `schema_aware: true` adds `schema_diff` to the output while preserving existing endpoint and provider keys. Stable identifiers match first. Suggested renames set `merge: false`.

The CLI returns JSON version 1 responses on success. RPC emits one JSON response per non-empty input line. When migrating error handlers, `--json-errors` outputs a single redacted JSON error object to stdout, and `--legacy-errors` writes text errors to stderr. Exclude credentials from error output.

## Immutable artifacts and URL policy

Store raw source bytes in content-addressed files under `<cache>/artifacts/` alongside redacted metadata sidecars. Write immutable manifests atomically under `<cache>/manifests/`. Unverified cache inputs receive the `legacy_unverified` label.

The `evaluation <url>` command requires HTTPS URLs and redacts query parameters containing credentials. Use `evaluation --input <file>` for local replay and deterministic evaluation.

## Model comparison

The `compare` command selects canonical models using release and effort metadata independent of provider endpoints. Specify selections with repeated `--select release[:effort,effort]` arguments.

Matching rules for `compare`:
- A release identifier without an effort suffix selects all observed effort variants for that release.
- Resolution matches normalized exact release names or slugs first, then unique token substrings. Ambiguous identifiers, missing releases, and unavailable requested efforts raise errors.
- Effort slug, label, and level populate directly from source objects. Non-reasoning models require an explicit false reasoning flag.
- Source model records and unmapped fields remain intact. Preserved unknown metrics keep their original status without inferred units or comparison eligibility.
- Output reports resolved selections, available effort levels, source freshness metadata, and model rows from the fetched catalog.
- Canonical model pricing retains model and API scope. Keep pricing distinct from task evaluation costs unless published task-level evidence is available.

## QA and query

The `qa` command returns `question`, `parsed_intent` (`model`, `provider`, `sort_by`, `order`, `limit`), and the matching `query` payload. The `qa` command rejects comparative queries containing versus or against tokens. Use `compare` for multi-model comparisons.

Query rows MAY return null for metrics omitted by upstream sources. High-signal fields include:
- Identity: `endpoint_slug`, `model_slug`, `provider_slug`
- Quality: `intelligence`, `coding`, `agentic`, `math`, `gpqa`, `mmlu_pro`, `ifbench`, `scicode`, `tau2`
- Economics: `price_input`, `price_output`, `price_blended`
- Speed and latency: `speed`, `ttfc`, `e2e`
- Context: `context_window_tokens`, `host_api_id`

## Dedicated evaluation

The `evaluation` command reads a public dedicated evaluation page or saved HTML and RSC response and returns:
- `source`: URL or path, HTTP status, fetch timestamp, content type
- `filters_applied`: minimum rows, sort path and order, limit
- `counts`: parsed frames, matched rows, returned rows
- `rows`: structured model identity and numeric score rows

Generic evaluation extraction is schema-dependent and cannot guarantee parsing every benchmark page layout or frontend revision.

Live evaluation responses include `population_source` and `coverage` when a public manifest supplies the full catalog. The ciphertext SHA-256 identifies the source of decoded row values, and the page retains its own source hash. Offline HTML replay reports `initial_models_only` when a manifest is present but not fetched.

Rows preserve source fields and use `value_status: "published"`. Sorting, limiting, and post-extraction calculations are marked as derived. Preserve unmapped fields without benchmark-specific normalization.
