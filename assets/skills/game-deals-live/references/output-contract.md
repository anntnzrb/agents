# Output Contract

Read this before interpreting CLI JSON or writing the user-facing comparison. The live `--schema --json` output is authoritative if this document and the runtime differ.

## Envelope

Stable top-level keys:

- `schema_version`
- `command`
- `query`
- `request`
- `identity`
- `provider_snapshots`
- `provider_failures`
- `offers`
- `bundle_history`
- `verification_queue`
- `critical_verification_items`
- `rankings`
- `warnings`
- `timestamps`

`--llm-json` returns the same normalized contract but omits raw snapshot `data`. `--json` keeps full provider snapshots.

## Identity

`identity` contains:

- `canonical_title`
- `match_status`
- `confidence`
- `steam`
- `cheapshark_game_id`
- `itad_id`
- `candidates`

Do not compare prices until identity is exact enough to distinguish base game, DLC, edition, package, bundle, remaster, and platform. When uncertain, cite candidates and rerun with a stable Steam ID.

## Offers

Each `offers[]` item contains normalized discovery fields:

- `provider`, `provider_offer_id`, `store`, `seller`
- `title`, `url`
- `price`, `original_price`, `regular_price`, `discount_percent`, `price_comparable`
- `drm`, `official`, `historical_low`
- `claimed_region`, `exclusions`, `coupon`
- `mandatory_fees`, `tax`, `subscription_period`, `preselected_extras`
- `acquisition_type`, `evidence_status`, `evidence`
- `observed_at`

`price` is the current comparable amount in the requested currency. `original_price` preserves that same current price in the provider-native currency; `regular_price` is the provider's list/reference price. Price objects contain `amount` and `currency`, plus optional `converted_from`, `fx_rate`, and `fx_as_of`. Converted prices are estimates until the retailer displays or charges the requested currency. Offers with `price_comparable: false` are retained as evidence but excluded from winners and the verification queue.

`bundle_history[]` contains provider bundle observations. Use it to discover past or candidate bundles, never as proof of a current offer or current component list.

## Acquisition type

Use exactly one:

- `ownership_key`: key redeemed into the user’s own platform account
- `direct_ownership`: entitlement bought directly into the user’s own store account
- `gift`: gift or inventory transfer requiring eligibility checks
- `subscription_access`: access ends or changes with subscription terms
- `account`: shared, transferred, preloaded, offline, or seller-controlled account
- `bundle`: multi-product offer; inspect components and the underlying delivery method
- `unknown`: evidence cannot distinguish the mechanism

These are practical comparison labels, not legal claims of property ownership.

## Evidence status

Use exactly one:

- `verified`: current direct evidence confirms the relevant listing facts
- `estimated`: normalized API/provider price without direct retailer confirmation
- `headline`: aggregator or listing headline whose terms still need inspection
- `blocked`: acquisition terms or verification barriers prevent a valid comparison
- `unknown`: evidence is insufficient or missing

Provider observation belongs in `evidence[]`, not in the status name. Do not invent a checkout-specific enum.

## Rankings

`rankings` is an object:

- `overall`: rows with `rank`, `offer_index`, `score`, and `reasons`
- `absolute_cheapest`: `{offer_index, price}` or `null`
- `cheapest_ownership`: `{offer_index, price}` or `null`
- `cheapest_verified`: `{offer_index, price}` or `null`

Resolve each `offer_index` against `offers`. Absolute cheapest may be account, subscription, gift, bundle, or unknown. Cheapest ownership includes only valid ownership-like delivery. `cheapest_verified` remains null when no offer reaches verified evidence.

## Verification work

- `verification_queue` contains up to five strict-cheapest checkout candidates with merchant, URL, and fields to verify.
- `critical_verification_items` contains non-offer blockers such as identity, region, activation, edition, component, or tax uncertainty.
- `warnings[]` and verification items use `code`, `severity`, `message`, `provider`, and `details` when applicable.
- All country lookups may warn that activation/region is unverified. US lookups may warn that tax is unknown.

## User-facing answer

Lead with one sentence naming the absolute cheapest and what the buyer actually receives. Then use a compact table:

| Rank | Store / exact product | Acquisition | DRM | Listed | Fees + tax | Total | Region | Evidence |
| --- | --- | --- | --- | ---: | ---: | ---: | --- | --- |

After the table, state:

1. cheapest ownership and cheapest verified, if different or available
2. component coverage for editions/bundles
3. region/activation result and whether “Global” remains unverified
4. fee, tax, currency-conversion, and checkout-total status
5. source disagreement, failures, timestamps, and residual risk

Use `unknown`, `not shown`, or `blocked` instead of zero for missing fees or tax. A displayed subtotal is not a final total.

## Exit codes

- `0`: command completed, possibly with explicit partial-provider warnings
- `1`: provider or network failure prevented the requested result
- `2`: usage or configuration error

Inspect JSON warnings and failures even when the process exits successfully.
