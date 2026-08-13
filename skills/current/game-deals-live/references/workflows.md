# Workflows

Read this for every user-facing deal task. It defines the deterministic-first sequence and the checks needed before recommending an offer.

## Standard lookup

1. Extract title, PC platform, edition/components, country, currency, and ranking goal
2. Default missing values to US, USD, top 5, all offer types, and absolute cheapest
3. Prefer a known Steam app, sub, or bundle ID; otherwise use the user’s title verbatim
4. Run:

```text
uv run --script <skill-dir>/scripts/cli.py lookup "<query>" --country <CC> --currency <CCC> --top <N> --llm-json
```

5. Check `identity.match_status` and `identity.confidence`. Stop price comparison if candidates represent different games, editions, remasters, or platforms
6. Check `provider_failures`, `warnings`, `critical_verification_items`, and timestamps before rankings
7. Preserve all acquisition types for the absolute-cheapest result. Separately identify cheapest ownership and cheapest verified
8. Browser-verify candidates in `verification_queue`; do not browse random offers before the deterministic shortlist exists

## Identity resolution

- Prefer exact Steam IDs over fuzzy title matching
- Keep base game, DLC, soundtrack, upgrade pack, complete edition, remaster, and sequel identities separate
- Treat punctuation or subtitle differences as cosmetic only after component and platform evidence agrees
- If identity is ambiguous, search official store/catalog pages for canonical IDs, then rerun with `--steam-app-id`, `--steam-sub-id`, or `--steam-bundle-id`
- Never merge prices across currencies, regions, or products merely because titles look similar

## Base game plus DLC or bundle

1. Resolve the base app and each requested DLC independently
2. Resolve candidate editions, subs, and bundles independently
3. Run lookup for the requested product and targeted Steam IDs when available
4. For GG diagnosis, run `provider gg --kind app|sub|bundle --ids <ids> --region <region> --llm-json`
5. Verify the bundle page’s current component list. Historical bundle contents do not prove current contents
6. Compare like-for-like totals:
   - complete bundle containing every requested component
   - base game plus individually purchased DLC
   - upgrade path from an edition the user already owns, only if the user confirms ownership
7. Report missing or duplicated components and whether bundle discounts depend on ownership or cart personalization

## Regional lookup

1. Use the user’s actual country and payment currency, for example `--country EC --currency USD`
2. Treat a provider’s US proxy or unsupported-country fallback as discovery only; surface its warning
3. Verify retailer country availability, key activation, accepted billing region, currency, and geo restrictions
4. “Global” means a seller label, not verified activation in the requested country
5. If the site redirects or prices change by region, preserve both observations and prefer the region-specific one
6. Do not claim a final total until fees and taxes are observed. For US tax, request state and ZIP

## Subscription or account contamination

1. Keep subscription and account offers in the raw absolute-cheapest comparison
2. Label them before price: `subscription_access` or `account`
3. Exclude them from cheapest ownership
4. Verify whether “buy,” “access,” “included,” “offline,” or “lifetime” language actually grants the requested product to the user’s own platform account
5. Treat shared, transferred, offline-activation, or preloaded accounts as account products even if the page says “game.”
6. If the user asked to own or keep the game, recommend the cheapest valid ownership offer, not the lower access headline

## Verification ladder

Use the strongest completed level and name it:

1. `headline`: aggregator or search-result price without full terms
2. `estimated`: provider/API listing normalized into an offer
3. `verified`: current retailer product page confirms product, acquisition, region, and displayed price
4. Checkout-verified total: read-only checkout preview confirms subtotal, fees, tax, currency, and total for the user’s region

The JSON `evidence_status` remains one of `verified`, `estimated`, `headline`, `blocked`, or `unknown`; describe checkout verification separately from ordinary retailer verification.

## Ranking and answer order

- Start with `rankings.absolute_cheapest` even when it is subscription, account, gift, or unknown
- Then show `rankings.cheapest_ownership` and `rankings.cheapest_verified` when non-null
- Use `rankings.overall` for the remaining shortlist and its reasons
- Do not silently substitute “best value” for the requested absolute-cheapest goal
- Keep absolute-price order unchanged. Explain risk labels and limitations without applying risk penalties or reordering the price ranking

## Refresh rules

- Re-run the CLI immediately before a price-sensitive answer if the prior observation is not from the current task
- Use retailer timestamps and CLI `timestamps`; never imply a price persists after observation
- If browsing materially changes price, terms, or availability, report the discrepancy and use the stronger current evidence
