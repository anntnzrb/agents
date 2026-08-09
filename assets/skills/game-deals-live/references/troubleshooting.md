# Troubleshooting

Read this for any warning, provider failure, empty result, ambiguous identity, stale observation, or retailer conflict.

## First checks

1. Run `uv run --script <skill-dir>/scripts/cli.py --schema --json` to confirm the live contract
2. Run the failing command with `--json` when raw provider snapshots are needed
3. Inspect exit code, `provider_failures`, `warnings`, `critical_verification_items`, snapshot status, and timestamps
4. Preserve partial successful evidence; do not hide missing coverage

## Exit codes

- `2`: fix CLI usage, invalid IDs, configuration, country/currency syntax, or missing dependency
- `1`: provider/network failure prevented the requested result; inspect snapshot errors and `retry_after`
- `0`: parse the envelope anyway; partial-provider failures and verification warnings may remain

## Ambiguous or wrong identity

Symptoms: mixed base/DLC results, sequel/remaster collision, multiple candidates, implausible prices.

Recovery:

1. inspect `identity.candidates`
2. locate the canonical Steam app/sub/bundle ID from official catalog evidence
3. rerun `lookup --steam-app-id <id>` or the corresponding sub/bundle ID
4. compare components separately

Never fix identity by manually relabeling an offer.

## Empty or sparse offers

- Confirm the product exists on PC and the requested region is supported
- Retry exact canonical title or stable Steam ID
- Add `--include-itad` for broader aggregate coverage
- Inspect provider failures before saying no deal exists
- Distinguish no returned offers from no verified offers
- Do not widen to console, account, or subscription products unless the default all-types search legitimately found them and labels remain explicit

## GG region fallback

If the requested country is unsupported, GG may use the US proxy. The output should preserve the original request, proxy metadata, and warning.

- Use the result for discovery only
- Do not call it region-specific or activation-verified
- Verify the direct retailer for the user’s country
- If direct verification fails, mark region/activation blocked or unknown

## Provider throttling or network failure

- Honor `retry_after`; do not hammer the provider
- Retry once after correcting transient connectivity or waiting the stated interval
- Use other healthy providers and disclose reduced coverage
- Do not convert a failed provider into an empty-price claim
- A CAPTCHA or anti-bot block is a verification limit, not permission to bypass it

## Price disagreement

Check, in order:

1. exact product and edition
2. requested versus provider region
3. currency and FX timestamp
4. membership, coupon, or first-purchase condition
5. stock/expiry status
6. dynamic bundle ownership
7. retailer subtotal, fees, tax, and total

Prefer current direct retailer evidence for the current listing. Preserve aggregate data as timestamped contradictory evidence.

## Currency conversion

- Inspect `converted_from`, `fx_rate`, and `fx_as_of`
- Treat converted values as estimates
- Verify the charged/displayed currency at the retailer
- State that card issuer or payment-provider conversion fees remain unknown unless shown

## Region says Global

- Search the seller’s activation-country exclusions and the platform’s regional rules
- Verify the requested country explicitly
- If the country is absent from both supported and excluded lists, report unknown
- Never translate “Global” directly to verified

## Tax or total unavailable

- US: request state and ZIP; without them, report subtotal and tax unknown
- Other countries: verify whether VAT/sales tax is included or added
- If checkout requires sign-in, address, or payment data, stop and report blocked
- Never compute a “final” total from an assumed tax rate

## Account or subscription misclassified

Inspect delivery text, renewal terms, required launcher/account, and what credentials or entitlement the buyer receives. Reclassify only with evidence:

- credentials/preloaded/offline/shared access → `account`
- recurring catalog/tier/trial → `subscription_access`
- redeemable key to buyer’s account → `ownership_key`
- direct entitlement to buyer’s account → `direct_ownership`
- unclear → `unknown`

Do not let low price override acquisition evidence.

## Stale or historical data

- `historical_low` is context, never a live offer
- Re-run lookup in the current task
- Compare `observed_at`, `fetched_at`, and top-level timestamps
- If the direct page no longer matches, report the offer as expired/unavailable and continue verification queue order

## Configuration and environment

Use the tracked `.env.example` as the variable-name reference. Never print secret values. Environment discovery may use the explicit environment file, skill-root `.env`, `$SKILLS_DIR/game-deals-live/.env`, or `<ancestor>/skills/game-deals-live/.env`; it must not scan arbitrary unrelated files.

## Handoff when blocked

Return the best partial shortlist plus:

- exact blocked fact
- source/provider and timestamp
- consequence for ranking or recommendation
- safest user action, such as supplying state/ZIP or manually confirming a retailer total
