# artificial-analysis output contract

All command outputs: JSON.

## CLI

```json
{"ok":true,"version":"1","command":"fetch|stats|diff|diagnose|evaluation|query|qa|schema","data":{...}}
```

One documented CLI entry point; omitted command defaults to `fetch`. Retain `fetch`, `stats`, `diff`, `diagnose`, `evaluation`, `query`, `qa`, `schema`; never rename or remove the entry point or a command. Success MUST retain `ok: true`, string `version: "1"`, `command`, `data` and their types; additions MUST NOT rename, remove, or retype them.

Default artifacts: `<temp-dir>/artifacts/artificial-analysis/{full-data.json,endpoints.txt,full-url.txt}`. Preserve these paths; custom output paths opt-in.

Snapshot v2: `meta.schema_version: 2`; top-level `models`, `hosts`, `hosts_models`; `hosts_models` slim and joined by `model_slug`. Add fields/projections only; preserve v2 keys and join.

Pricing scopes stay distinct: model/API `price_1m_blended_3_to_1`; endpoint/RSC `price_1m_blended_7_to_2_to_1`. Never merge, rename, or reinterpret them.

Malformed source envelopes/rows remain rejected. `fetch --strict`: no-fallback mode. Preserve rejection/fallback semantics; reconciliation MUST be versioned and additive.

### Freshness

Every refresh/reader result distinguishes these modes:

- `fresh`: successful current source response; `stale:false`, `historical:false`.
- `cache-revalidated`: validated 304/body reuse; `stale:false`; never outage-stale.
- `stale-last-good`: explicit `--allow-stale` or `--stale-policy allow-last-good` fallback; `stale:true`, `fallback:true`.
- `snapshot`: explicit local input; `historical:true`, `stale:false`.

Default refresh policy: `error`; `--strict` remains its compatibility alias. Default output snapshot retains its 24-hour reader guard. Stale fallback NEVER overwrites current cache bytes. Explicitly named old paths are historical snapshots, not stale outage fallbacks.

## RPC

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

## Fetch credentials and secrets

Only `fetch` requires `ARTIFICIAL_ANALYSIS_API_KEY`. Prefer a process-injected key, or `ARTIFICIAL_ANALYSIS_ENV_FILE` pointing to a permissions-restricted dotenv file (e.g. mode `0600`) outside the skill tree. The key is never a CLI/RPC argument.

NEVER copy `.env.example` into the skill tree or generated tool home: it is a tracked template, not a secret store. Precedence: process values, then explicitly supplied external env file. Skill-root/ancestor `.env` discovery is transitional compatibility only and unsupported for new setups. This release has no `AA_LEGACY_DOTENV`; do not rely on it.

Asset-sync owner MUST exclude `.env` and other secret files from generated tool homes. `.gitignore` controls Git tracking only; it CANNOT enforce sync exclusion.

## Snapshot JSON v2

Top-level keys: `meta`, `models`, `hosts`, `hosts_models`.

`meta`: `schema_version: 2`, `counts`, `sources`. `sources.rsc` and `sources.official_api`: source URL, status code, fetched-at timestamp, supplied ETag, and applicable `reused_cached_payload`; never credentials or raw response bodies. `counts`: unique canonical `models`, `hosts`, endpoint `hosts_models`, plus available endpoint/provider sanity counts.

`models` is the only model projection: exactly one canonical row per `slug`; official API identity, evaluations, and API pricing belong here. `hosts_models` is a slim provider-endpoint table: each row has `model_slug` joining the canonical model and retains endpoint/provider pricing, speed, latency, context, features, and classifications; it MUST NOT embed a `model` object.

The model API's 3:1 blend and RSC endpoint's 7:2:1 blend intentionally coexist: model and provider-endpoint scopes, not duplicate prices.

## Evidence, statuses, eligibility

Named scalar fields remain stable. Additive `metric_evidence.<metric>` records: `raw_value`, `normalized_value`, `unit`, `normalization`, `source_path`, `source_field`, `value_status`, `metric_semantics_status`, `comparison_eligibility`, `blocked_reasons`, `parser`, `parser_version`, and available `artifact_id`/`sha256`.

`value_status`: `published|derived|missing|unparsed`. `metric_semantics_status`: `known|unknown|ambiguous`. `comparison_eligibility`: `eligible|blocked`.

Placeholders, booleans, non-finite/malformed/out-of-range values, unknown semantics, unit/scope/release mismatches, and conflicting duplicates remain visible with reasons; they MUST NOT become fake zeroes or eligible comparisons. Derived fields retain formulas and input paths and never replace published values. Unknown source keys survive under `raw_fields`/`raw_metadata`.

## Diagnostics, diff, errors

`diagnose`: explicit local snapshot/cache paths only; NEVER fetches. Report: redacted schema/parser/freshness/source/cache/artifact health and diagnostics.

`diff --schema-aware` or RPC `schema_aware:true`: add `schema_diff` while preserving every legacy endpoint/provider key. Stable IDs match first; possible rename suggestions carry `merge:false`.

CLI success remains protocol v1. RPC emits one response per non-empty input line with existing error codes. During staged migration, `--json-errors` emits one compact redacted CLI error object on stdout; `--legacy-errors` retains human-readable stderr. Neither form contains credentials.

## Immutable artifacts and URL policy

Raw source bytes: content-addressed under `<cache>/artifacts/`, with redacted metadata sidecars. Immutable manifests: atomically written under `<cache>/manifests/`. Legacy mutable cache inputs promoted as `legacy_unverified`.

`evaluation <url>`: HTTPS only; redact credential query parameters. Local/deterministic replay: `evaluation --input <file>`.

## QA and query

`qa` returns `question`, `parsed_intent` (`model`, `provider`, `sort_by`, `order`, `limit`), and full `query` payload.

Each `query` row MAY contain nulls for upstream-unprovided metrics. High-signal fields:

- identity: `endpoint_slug`, `model_slug`, `provider_slug`
- quality: `intelligence`, `coding`, `agentic`, `math`, `gpqa`, `mmlu_pro`, `ifbench`, `scicode`, `tau2`
- economics: `price_input`, `price_output`, `price_blended`
- speed/latency: `speed`, `ttfc`, `e2e`
- context: `context_window_tokens`, `host_api_id`

## Dedicated evaluation

`evaluation` reads a public dedicated evaluation page or saved HTML/RSC response and returns:

- `source`: URL/path, HTTP status, fetch timestamp, content type
- `filters_applied`: minimum rows, optional sort path/order, limit
- `counts`: parsed frames, matched rows, returned rows
- `rows`: largest recognizable list of model-identity + numeric-score rows

Generic evaluation extraction is schema-dependent and does not guarantee parsing every benchmark page layout or frontend revision.

Rows preserve source fields and use `value_status=published`. Sorting, limiting, and post-extraction arithmetic are derived. Preserve unknown fields; benchmark-specific normalization stays outside this generic extractor.
