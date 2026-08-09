# Provider Contracts

Read this before selecting providers or assigning confidence. Provider output is discovery evidence, not a promise that checkout will succeed.

## CLI commands

```text
uv run --script <skill-dir>/scripts/cli.py lookup "<query>" --country US --currency USD --top 5 --llm-json
uv run --script <skill-dir>/scripts/cli.py lookup --steam-app-id <id> --include-itad --llm-json
uv run --script <skill-dir>/scripts/cli.py provider gg --kind app --ids <id> --region us --prices-only --llm-json
uv run --script <skill-dir>/scripts/cli.py provider gg --kind bundle --ids <id> --region us --bundles-only --llm-json
uv run --script <skill-dir>/scripts/cli.py stores --llm-json
uv run --script <skill-dir>/scripts/cli.py --schema --json
```

`--type` is a compatibility alias for GG `--kind`. GG IDs must be unique positive integers; a request accepts at most 100.

## Source roles

### Steam direct

- Use for canonical app identity, direct store pricing, package/edition context, and platform/region signals exposed by Steam
- Steam API prices remain `estimated` with acquisition type `direct_ownership`; only browser-confirmed direct retailer evidence can become `verified`
- Steam display price does not prove third-party key activation, user-specific bundle price, or final tax

### CheapShark aggregate

- Use for broad offer discovery, store mapping, discounts, and historical-low context
- Treat API prices as `estimated`
- Do not infer edition components, regional activation, fees, tax, or checkout availability from a deal row alone

### GG aggregate

- Use explicit `app`, `sub`, or `bundle` IDs for current price headlines and bundle-history investigation
- Treat GG aggregate prices as `headline` until the retailer page is checked
- An unsupported country may map to the US proxy. Preserve the request metadata and warning; never present the proxy as regional verification
- `--prices-only` and `--bundles-only` narrow retrieval, not product semantics

### IsThereAnyDeal

- Enable with `--include-itad` when extra official-store coverage or triangulation is worth another provider dependency
- Treat aggregate API prices as `estimated`
- Do not equate store authorization with product identity, regional activation, or checkout total

### Retailer page and checkout

- A live retailer product page can raise evidence to `verified` only when product, acquisition type, region/activation, currency, and price are actually visible
- Checkout evidence is strongest for fees, tax, and total, but remains read-only and user-location-specific
- Account gates, CAPTCHA, unavailable region selectors, or hidden taxes mean `blocked` or `unknown`, not verified

## Snapshot contract

Each `provider_snapshots[]` item contains:

- `provider`
- `status`
- `fetched_at`
- `request`
- `data` or `error`
- optional `retry_after`

`--llm-json` preserves normalized output but drops raw snapshot `data`. `--json` retains full snapshots. Never infer missing output from omitted compact data.

## Partial failure

- Read `provider_failures` before trusting coverage
- One healthy provider can support a partial shortlist; it cannot support “market-wide cheapest.”
- Name failed, blocked, stale, or excluded providers
- Retry only when `retry_after` or troubleshooting guidance supports it
- Preserve successful evidence when another provider fails; do not flatten partial success into total failure
- GG prices and bundle history are independent stages; a later bundle failure must not erase an earlier price response

## Store metadata

Use `stores` to resolve merchant names and provider identifiers. Store metadata does not prove:

- the seller is authorized for this exact listing
- activation in the requested country
- whether the product is a key, gift, direct entitlement, account, or subscription
- fees, taxes, or final checkout total

## Evidence discipline

- Preserve every `evidence[]` item as `{source, kind, value, observed_at}`
- Keep the engine’s `evidence_status`; do not promote `headline` or `estimated` based on familiarity with a store
- When sources conflict, report both observations, their timestamps, and the conflict
- Use direct product URLs. Aggregator redirects are discovery links unless their target and terms were verified
- Historical lows are context only. They are not current offers
