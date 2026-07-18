# Checkout Verification

Read this before claiming retailer availability, regional activation, fees, taxes, or a final total. Verification is read-only.

## Hard stop

NEVER buy, create an account, sign in, accept a subscription, enter payment data, submit an order, or bypass access controls. Do not ask the user for payment credentials. Stop when verification would require an account, identity data, or irreversible action; report `blocked` and the exact missing fact.

## Candidate order

1. Start with CLI `verification_queue`, which contains the strict-cheapest candidates.
2. Open the direct retailer URL; avoid search snippets and redirectors when possible.
3. Verify product identity before price: exact title, edition, platform, base/DLC status, and included components.
4. Verify acquisition: key, direct entitlement, gift, subscription, account, bundle, or unknown.
5. Verify country availability and activation language for the requested country.
6. Verify displayed currency, subtotal, mandatory fees, discount conditions, tax treatment, and total.
7. Record URL and observation time. Return to the next candidate only after the current one is classified.

## Safe browser behavior

- Public product, terms, region, FAQ, and cart-preview pages are allowed.
- Use a public cart or checkout estimator only when it requires no account, personal data, or payment data and creates no order.
- Do not use VPNs or spoof location to manufacture regional availability.
- Do not bypass CAPTCHA, rate limits, age gates requiring false information, or anti-bot controls.
- Do not infer hidden checkout terms from a browser’s locale or IP alone.

## Product and edition

Verify all of these when relevant:

- exact base game or DLC identity
- PC platform and DRM launcher
- edition name and current components
- whether a bundle includes the base game
- whether “complete,” “ultimate,” or “deluxe” omits requested DLC
- whether an upgrade pack requires prior ownership
- whether dynamic bundle pricing depends on products already owned

Historical bundle pages and edition names are not sufficient. Use the current retailer component list.

## Region and activation

- Verify the requested country, not merely “ROW,” “Global,” or a broad continent.
- “Global” is a seller claim until supported by an activation-country list or platform restriction evidence.
- Distinguish store browsing availability, purchase eligibility, key activation, and post-activation playability.
- Record exclusions, billing-country requirements, region locks, gifting restrictions, and required platform account region.
- A US proxy price for an unsupported provider country is not Ecuador or other-country verification.

## Fees, tax, and currency

Break the total into:

- listed subtotal
- mandatory service/payment/handling fees
- discount or coupon conditions
- tax shown or tax treatment stated
- currency conversion and card/issuer charges, when known
- final displayed total

Never substitute zero for an undisclosed amount. Mark it unknown.

### United States

A final US tax total requires the buyer’s state and ZIP and a checkout estimate using those values. Without both, report subtotal plus “tax unknown”; do not call it final. City/county rules may differ within a state.

### Other countries

Verify whether VAT/sales tax is included, added at checkout, reverse-charged, or not shown. A USD display in Ecuador does not prove Ecuador activation, payment acceptance, tax inclusion, or absence of issuer conversion fees.

## Evidence outcomes

- `verified`: direct current page evidence supports the facts being reported.
- `estimated`: provider/API data or a calculable subtotal without complete direct terms.
- `headline`: visible promotional/listing price lacks sufficient product or checkout terms.
- `blocked`: required evidence is behind account, location, CAPTCHA, unavailable checkout, or incompatible acquisition terms.
- `unknown`: the fact was not found or cannot be resolved.

Do not promote the whole offer because one field is verified. State field-level uncertainty in the answer.

## Disagreement

When aggregator and retailer disagree:

1. confirm exact product and region
2. compare observation timestamps and currency
3. check expired coupons, membership prices, dynamic bundles, and out-of-stock keys
4. prefer current direct retailer evidence for current availability and price
5. retain the provider observation as a discrepancy, not as a second live total

## Minimum evidence note

For each finalist, retain or report:

- source and direct URL
- observed timestamp
- exact product/components
- acquisition type
- requested country and activation result
- subtotal, fees, tax, and total status
- evidence status and unresolved blockers
