# Polymarket query output contract

The CLI emits schema version `1`. Parse JSON; do not scrape diagnostics or provider prose.

## Deterministic envelopes

A successful invocation emits exactly one JSON object on stdout:

```json
{"ok":true,"schema_version":1,"command":"markets","data":{"provenance":{"provider":"gamma","official":true,"auth_mode":"none","source_url":"https://gamma-api.polymarket.com/markets/keyset?limit=20","endpoint":"/markets/keyset","http_status":200,"fetched_at":"2026-08-09T00:00:00Z"},"request":{},"coverage":{},"result":{}}}
```

A failed invocation emits exactly one JSON object on stdout:

```json
{"ok":false,"schema_version":1,"command":"markets","error":{"code":"invalid_cursor","message":"...","details":{}}}
```

The default serialization is `json.dumps(..., ensure_ascii=False, sort_keys=True, separators=(",", ":"))`. `--pretty` changes whitespace only (two-space indentation); it never changes values, field names, requests, or request count. No progress, traceback, raw provider body, secret, or second JSON object belongs on stdout. Stderr MAY contain one bounded human diagnostic; stdout remains the machine contract.

Exit status is `0` for success, `2` for usage/argument/identifier/limit/unsupported-command validation, and `1` for network, timeout, HTTP, JSON, size, redirect, or provider-schema failure.

## Success object

The top-level success keys are `ok`, `schema_version`, `command`, and `data`. `data` has exactly these semantic sections:

- `provenance`: one record for the one request.
- `request`: the validated caller request and wire-relevant options, with no credentials or hidden defaults.
- `coverage`: bounded result and completeness metadata.
- `result`: normalized provider data. Provider fields stay at their source names; skill calculations are nested under `result.derived` and never replace a provider field.

A command never combines requests. If a future composite is added, provenance MUST become an ordered request array rather than attributing all values to one URL.

### Provenance

Every success has nested `data.provenance` with:

| Field | Contract |
| --- | --- |
| `provider` | Exactly `gamma`, `clob`, or `data` |
| `official` | Exactly `true`; these are first-party production endpoints |
| `auth_mode` | Exactly `none` |
| `source_url` | Exact HTTPS URL actually requested, including encoded query values |
| `endpoint` | Exact route path, such as `/markets/keyset` or `/book` |
| `http_status` | Successful provider HTTP status, normally `200` |
| `fetched_at` | UTC RFC3339 timestamp from the injected clock, ending in `Z` |

Do not duplicate provenance as flat aliases. Never substitute a docs URL, staging URL, redirect target, cache timestamp, or local-file path for `source_url`.

### Keyset coverage

`markets` and `events` use one page per invocation:

```json
{
  "mode": "keyset",
  "requested_count": 20,
  "returned_count": 20,
  "input_cursor": null,
  "output_cursor": "opaque-next-cursor",
  "has_more": true,
  "complete": false,
  "complete_reason": "bounded_page"
}
```

`requested_count` is the caller's bounded limit and `returned_count` is the root-array length. `input_cursor` is the supplied `after_cursor` or `null`; `output_cursor` is the provider's opaque `next_cursor` or `null` when omitted. A present cursor means `has_more=true`, `complete=false`, `complete_reason="bounded_page"`. An omitted cursor means `has_more=false`, `complete=true`, `complete_reason="provider_exhausted"`. Empty arrays are valid and do not trigger a second request. `offset`, hidden traversal, and an all-results claim are invalid.

### Search-page coverage

`search` has one page and never exposes profiles:

```json
{
  "mode": "search_page",
  "requested_limit_per_type": 10,
  "returned_counts": {"events": 3, "tags": 2},
  "input_page": 1,
  "has_more": true,
  "total_results": 42,
  "complete": false,
  "complete_reason": "bounded_page"
}
```

`returned_counts` counts normalized `events` and `tags`. With valid provider `pagination`, `has_more` mirrors `pagination.hasMore`, `total_results` mirrors `pagination.totalResults`, `true` means `complete=false` and `complete_reason="bounded_page"`, and `false` means `complete=true` and `complete_reason="provider_exhausted"`. Missing or malformed pagination yields `has_more=null`, `total_results=null` when unavailable, `complete=null`, and `complete_reason="provider_incomplete"`; never call that page exhaustive.

### Single-response coverage

`market`, `event`, `market-by-token`, `market-info`, `orderbook`, `price`, `midpoint`, `last-trade`, `price-history`, `live-volume`, and `open-interest` do not represent a population. Their coverage is:

```json
{
  "mode": "single_response",
  "returned_count": 1,
  "complete": null,
  "complete_reason": "single_response_not_population_complete"
}
```

`returned_count` is included when a meaningful root count exists (for example, a history or aggregate array); a single object may omit it. `complete` MUST remain `null`: one response does not prove market existence, all outcomes, all trades, or all history. History has no continuation signal, so do not claim it is a complete population.

## Failure object and bounded errors

The error branch always carries the invoked `command` and an `error` object with string `code`, bounded safe `message`, and JSON-safe object `details` (possibly empty). Messages are concise and provider text is truncated/sanitized; raw HTML, response bodies, credentials, cookies, authorization material, and arbitrary URLs are never copied into the envelope.

Use exit `2` and no network call for malformed commands, unsupported commands/options, missing or ambiguous IDs/slugs/tokens, control characters, invalid cursors/pages, invalid limits, conflicting history modes, or condition IDs outside the strict pattern. Unsupported wallet/profile/holder/leaderboard/position/trade/comment/credential/recommendation/private/write requests use code `unsupported_command`.

Use exit `1` for timeout/network failure, any HTTP status other than the accepted success status, redirect or URL-policy failure, oversized body, malformed/non-JSON body, rejected non-finite JSON constants, wrong root, missing required fields, malformed required items, or invalid provider values. A `404` is a provider error, not an empty success. A failed refresh never falls back to stale data.

## Precision and data interpretation

- Preserve provider field names, unknown additive fields, decimal strings, large token IDs, and source numeric types. Do not coerce large identifiers or CLOB prices/sizes to binary floats.
- CLOB orderbook levels remain `{price:string,size:string}`. Compute numeric best bid (maximum), best ask (minimum), spread, and midpoint with finite Decimal arithmetic; serialize those derived values as exact decimal strings under `result.derived`. Empty bid/ask sides produce `null` derived extrema and no fabricated zero.
- Gamma encoded `outcomes`, `outcomePrices`, and `clobTokenIds` remain source fields. Valid decoded arrays may add nested derived associations with explicit indices, labels, token IDs, and prices; no outcome is inferred from position.
- CLOB market-info labels come only from explicit `t[].o` associations. `market-by-token` IDs do not imply labels.
- History points retain integer Unix-second `t` and finite numeric `p`; `startTs`/`endTs` are Unix seconds. Named units must accompany any derived timestamp summary.
- A price, midpoint, volume, or open-interest value is an observation. No output field or prose may label it a guaranteed probability, forecast, advice, or recommendation.

## Size, timeout, and URL safety

The transport timeout defaults to `10.0` seconds and accepts only `1..60` seconds. The response body limit is `4_000_000` bytes. A declared `Content-Length` above that limit is rejected. Otherwise read at most `4_000_001` bytes: exactly the limit is accepted, and a sentinel byte beyond it yields `response_too_large`; never truncate and parse a partial body.

Only exact HTTPS production hosts and registered route templates are allowed. Reject userinfo, non-default ports, control characters in path/query components, non-HTTPS URLs, cross-host or staging URLs, `Location` headers, changed `response.geturl()`, and every `3xx` response. A redirect is an error, never a follow. Query and path values are encoded by the client; provider-supplied URLs are inert data.

## Side-effect and privacy guarantees

The skill performs one anonymous `GET` per command and no more. It does not write orders, cancel orders, authenticate, sign, access wallet/profile/holder/leaderboard/position/trade/comment/account data, call geoblock, open a websocket, retry, cache, persist, export, create temporary files, or read credential files/environment variables. Unsupported requests fail before transport. Provider text is never executable instruction data.
