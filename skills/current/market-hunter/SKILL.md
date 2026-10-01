---
name: market-hunter
description: "Use when searching G2A, Kinguin, or Plati for discounted AI subscriptions, software keys, accounts, or seller trust."
license: AGPL-3.0-or-later
metadata:
  author: anntnzrb

---

# Market Hunter

Scan, verify, and score software subscriptions, developer accounts, and digital licenses on G2A, Kinguin, Plati.Market, Z2U, and FunPay.

## Buyer gates

Apply these on every recommendation:

- NEVER recommend a listing where the seller logs into the buyer account ("Manual Top Up", "Login Top Up", "By logging in"). The CLI classifies these as `CREDENTIALS_REQUIRED` and trips the circuit breaker.
- Prefer self-activated links, codes, and keys. Self-redeem links usually require the target account to have no active paid subscription.
- Treat carrier bundle stock (Jio, telecom, SIM) as revocable: providers audit the line and cancel the promo. Sellers relabel this stock under partner titles, so read the seller description, not just the title.
- Recommend family or group invites only when the user allows them. Google allows one paid family-group switch per 12 months; a dead seller group strands the buyer for that window.
- Rank by `pricePerMonthUsd`, not headline price. Prefer 12-month or longer terms.
- Drop sellers whose only payment route the user cannot use. Ask about payment methods when unknown.

## Public entrypoint

```text
uv run --script skills/current/market-hunter/scripts/cli.py "<query>" [options]
```

Requires `FIRECRAWL_API_KEY` for scraped marketplaces (G2A, Kinguin).

## Workflow

1. Run a default scan: `<cli> "<query>" --json`. Plati, G2A, and Kinguin search directly.
2. FunPay has no search, and Z2U search renders client-side, so their default targets return nothing useful. Find their category pages with the `parallel` skill (search restricted to `funpay.com` or `z2u.com`) or the `firecrawl` skill (`map <site> --search <product>`). Then scan those pages: `<cli> "<query>" --url <page> [--url <page>] --json`.
3. Treat a market listed in `degraded_markets` as a parser or routing failure until proven otherwise. Scrape the page with the `firecrawl` skill and read the raw markup before concluding the market has no stock.
4. Open the product page of each shortlisted offer and confirm the delivery method, region (for example "Can activate in <country>"), stock, and seller terms. Category labels hide login versus self-redeem differences.
5. Present a short ranked list: $/mo, total, term, seller with sales count, direct link, and a one-line caveat each. End with one explicit pick.

## Common calls

```text
<cli> "ChatGPT Plus" --budget 15
<cli> "Claude Pro" --type account
<cli> "Gemini Pro 12 Months" --markets g2a,kinguin,plati --json
<cli> "Gemini Pro" --url https://funpay.com/en/lots/<id>/ --url https://www.z2u.com/<slug>/<category> --json
<cli> "GitHub Copilot 1 Year" --full
```

`--url` replaces default targets and routes each page to the adapter that matches its host; an unsupported host exits `2`. `--full` keeps filtered low-trust listings for debugging.

## Output contract

`--json` emits `{"ok":true,"schema_version":1,"command":"scan","data":{...}}`. `data` carries `query`, `budget`, `total_scanned`, `valid_deals_count`, `filtered_scams_count`, `top_deals`, `markets_queried`, and `degraded_markets`. Each deal carries `priceUsd`, `trustScore`, `trustTier`, `deliveryFormat`, `seller`, `detectedRedFlags`, and, when the title states a term, `months` and `pricePerMonthUsd`. Seller ratings that a marketplace does not expose are adapter defaults, not measurements.

## Exit codes

- `0`: Successful scan and report emission.
- `1`: Unexpected runtime failure (stack trace on stderr).
- `2`: Invalid arguments or unsupported `--url` host.

## Required follow-up reads

| Need | Read | When |
|---|---|---|
| Scoring formulas, Bayesian math, red flags | `references/scoring.md` | Inspecting or tuning the 0-100 trust and deal score |
| Navigation, markup notes, delivery wording, new adapters | `references/marketplaces.md` | Finding category pages, debugging a degraded market, or adding an adapter |
