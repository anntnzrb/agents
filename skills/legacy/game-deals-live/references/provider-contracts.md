# Provider Contracts

Read before provider selection or confidence assignment. Provider output = discovery evidence, not checkout success.

## CLI commands

```text
uv run --script <skill-dir>/scripts/cli.py lookup "<query>" --country US --currency USD --top 5 --llm-json
uv run --script <skill-dir>/scripts/cli.py lookup --steam-app-id <id> --include-itad --llm-json
uv run --script <skill-dir>/scripts/cli.py provider gg --kind app --ids <id> --region us --prices-only --llm-json
uv run --script <skill-dir>/scripts/cli.py provider gg --kind bundle --ids <id> --region us --bundles-only --llm-json
uv run --script <skill-dir>/scripts/cli.py stores --llm-json
uv run --script <skill-dir>/scripts/cli.py --schema --json
```

`--type` = compatibility alias for GG `--kind`. GG IDs MUST be unique positive integers; request maximum 100 IDs.

## Source roles

### Steam direct

- Canonical app identity, direct-store pricing, package/edition context, and Steam-exposed platform/region signals.
- Steam API prices remain `estimated`, acquisition type `direct_ownership`; only browser-confirmed direct-retailer evidence can become `verified`.
- Steam display price does not prove third-party key activation, user-specific bundle price, or final tax.

### CheapShark aggregate

- Broad offer discovery, store mapping, discounts, historical-low context.
- API prices = `estimated`.
- A deal row alone does not establish edition components, regional activation, fees, tax, or checkout availability.

### GG aggregate

- Use explicit `app`, `sub`, or `bundle` IDs for current price headlines and bundle-history investigation.
- GG aggregate prices = `headline` until retailer-page verification.
- Unsupported country may map to US proxy: preserve request metadata and warning; NEVER present proxy as regional verification.
- `--prices-only` and `--bundles-only` narrow retrieval, not product semantics.

### IsThereAnyDeal

- Enable with `--include-itad` when extra official-store coverage or triangulation justifies another provider dependency.
- Aggregate API prices = `estimated`.
- Store authorization does not establish product identity, regional activation, or checkout total.

### Retailer page and checkout

- Live retailer product page can raise evidence to `verified` only when product, acquisition type, region/activation, currency, and price are visible.
- Checkout evidence is strongest for fees, tax, and total, but remains read-only and user-location-specific.
- Account gates, CAPTCHA, unavailable region selectors, or hidden taxes → `blocked` or `unknown`, not `verified`.

## Snapshot contract

Each `provider_snapshots[]` item contains `provider`, `status`, `fetched_at`, `request`, `data` or `error`, and optionally `retry_after`.

`--llm-json` preserves normalized output but drops raw snapshot `data`; `--json` retains full snapshots. NEVER infer missing output from omitted compact data.

## Partial failure

- Read `provider_failures` before trusting coverage.
- One healthy provider supports a partial shortlist, not “market-wide cheapest.”
- Name failed, blocked, stale, or excluded providers.
- Retry only when `retry_after` or troubleshooting guidance supports it.
- Preserve successful evidence when another provider fails; NEVER flatten partial success into total failure.
- GG prices and bundle history are independent stages; later bundle failure MUST NOT erase earlier price response.

## Store metadata

Use `stores` to resolve merchant names and provider identifiers. Store metadata does not prove seller authorization for the exact listing, activation in the requested country, product type (key, gift, direct entitlement, account, or subscription), fees, taxes, or final checkout total.

## Evidence discipline

- Preserve every `evidence[]` item as `{source, kind, value, observed_at}`.
- Keep engine `evidence_status`; do not promote `headline` or `estimated` based on store familiarity.
- Conflicting sources: report both observations, timestamps, and conflict.
- Use direct product URLs. Aggregator redirects are discovery links unless target and terms were verified.
- Historical lows are context only, not current offers.
