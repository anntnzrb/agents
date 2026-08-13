---
name: game-deals-live
description: Find and verify PC game prices, editions, bundles, regional access, fees, taxes, and checkout totals.
license: AGPL-3.0-or-later
compatibility: Requires `uv` and network access. Browser or web search is required for retailer and checkout verification.
metadata:
  author: anntnzrb

---

# game-deals-live

Read-only PC game deal discovery and verification. Run the bundled deterministic CLI before browsing or searching; never answer a live-price question from memory.

## Safety boundary

- NEVER buy, create an account, sign in, accept a subscription, submit personal data, or submit payment
- Keep browser verification read-only. Stop before any irreversible or account-gated step
- Treat account sales and subscription access as access products, not game ownership

## Defaults

Unless the user overrides them, use:

- country `US`
- currency `USD`
- top `5`
- all acquisition and offer types
- absolute cheapest ranking, even when it is not ownership; label the acquisition type prominently

“Global” is NEVER proof of activation in the requested country. A final US tax total requires the user’s state and ZIP plus checkout evidence.

## Entry point

```text
uv run --script <skill-dir>/scripts/cli.py lookup "<game or edition>" --country US --currency USD --top 5 --llm-json
```

Use stable Steam IDs when known:

```text
uv run --script <skill-dir>/scripts/cli.py lookup --steam-app-id <id> --country US --currency USD --top 5 --llm-json
```

Use `--include-itad` only when broader aggregation is useful. Use `provider gg --kind app|sub|bundle --ids <id> ...` for GG-specific diagnosis, `stores` for store metadata, and `--schema --json` before implementing an integration. Prefer `--llm-json`; use `--json` only when raw provider snapshots are required.

## Required follow-up reads

|Need|Read|When|
|---|---|---|
|Search, comparison, bundle, and regional procedures|`references/workflows.md`|Every user-facing deal task|
|Provider capabilities and evidence limits|`references/provider-contracts.md`|Selecting or interpreting providers|
|JSON fields, classifications, ranking, and answer shape|`references/output-contract.md`|Consuming CLI output or reporting results|
|Retailer, activation, fee, tax, and total verification|`references/checkout-verification.md`|Any finalist or “final price” claim|
|Ownership, key, gift, subscription, account, and bundle risk|`references/acquisition-risk.md`|Classifying or recommending an offer|
|Failures, ambiguity, stale data, and conflicting prices|`references/troubleshooting.md`|Any warning, provider failure, or verification block|

## Workflow

1. Normalize the request: title, platform, edition/components, country, currency, ranking goal, and any known Steam IDs
2. Run `lookup` with defaults or explicit user constraints. Do not filter out subscription, account, gift, or bundle offers before absolute-cheapest comparison
3. Inspect `identity`, `provider_failures`, `warnings`, `offers`, `bundle_history`, `rankings`, `verification_queue`, and `critical_verification_items`. Resolve ambiguous identity before comparing prices
4. Classify every contender by `acquisition_type`: `ownership_key`, `direct_ownership`, `gift`, `subscription_access`, `account`, `bundle`, or `unknown`
5. Preserve `evidence_status`: `verified`, `estimated`, `headline`, `blocked`, or `unknown`. Never promote aggregate data to `verified`
6. Verify the strict-cheapest candidates in `verification_queue` with retailer pages, search, and read-only checkout evidence. Verify bundle components and edition equivalence separately
7. Report the absolute cheapest first, then cheapest ownership and cheapest verified when available. Explain why they differ

## Reporting contract

Return a compact comparison containing store, exact product/edition, acquisition type, DRM/platform, listed price, fees/tax/total status, activation region, evidence status, timestamp, and direct URL. State:

Use the literal labels `Absolute cheapest`, `Cheapest permanent ownership`, and `Cheapest verified checkout`; write `unavailable` when no candidate qualifies.

- whether the offer includes the base game and each requested DLC/component
- whether access is permanent license-like access, subscription-only, gift, or transferred account
- whether country activation and checkout total are verified, estimated, blocked, or unknown
- provider disagreement, missing evidence, and the next safe verification step

Do not call a subtotal a final total. Do not call an edition equivalent until its components match the user’s request.
