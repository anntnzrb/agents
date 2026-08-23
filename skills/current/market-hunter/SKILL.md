---
name: market-hunter
description: "Search, compare, verify, and score AI subscriptions, licenses, and digital accounts across deal marketplaces."
license: AGPL-3.0-or-later
metadata:
  author: anntnzrb

---

# Market Hunter

Scan, verify, and score software subscriptions, developer accounts, and digital licenses across secondary digital marketplaces.

## Activation Triggers

- User asks to search, find deals, compare prices, or purchase discounted accounts or subscriptions (ChatGPT Plus, Claude Pro, Gemini Advanced, GitHub Copilot, Cursor Pro, Perplexity Pro, Windows/Office, VPNs).
- User asks to check seller reliability, trust scores, or verify whether a digital marketplace listing is legitimate or a shared scam.
- Marketplaces covered: G2A, Kinguin, Plati.Market, Z2U, and FunPay.

## Marketplace Strengths and Priority Routing

- **Google Gemini Advanced 2TB (3M/6M)**: Prioritize **G2A** (promotional brand links) and **Kinguin**.
- **ChatGPT Plus (Dedicated Accounts)**: Prioritize **Plati.Market** (direct wholesale personal accounts) and **FunPay**.
- **GitHub Copilot (1-Year Packs)**: Prioritize **Plati.Market** (student and developer packs) and **Z2U**.
- **Claude Pro (Dedicated / Team)**: Prioritize **Z2U** (pre-activated dedicated logins) and **FunPay**.
- **Cursor Pro (Monthly)**: Prioritize **Z2U** and **FunPay**.
- **Perplexity Pro (1-Year Keys)**: Prioritize **Kinguin** (promotional voucher codes).
- **Bulk Google / Gmail Accounts (PVA/Aged)**: Prioritize **Z2U** and **Plati.Market**.
- **Discord Nitro & Telegram Premium**: Prioritize **FunPay** (P2P escrow) and **Plati.Market**.
- **Windows 11 & Office 2024 (OEM/Retail)**: Prioritize **Plati.Market** (lifetime retail keys) and **Kinguin**.

## Public CLI Entrypoint

Run via Bun runner:

```text
bun skills/current/market-hunter/scripts/cli.ts "<query>" [options]
```

## Common Command Recipes

Search for ChatGPT Plus deals with a budget ceiling:
```bash
bun skills/current/market-hunter/scripts/cli.ts "ChatGPT Plus" --budget 15
```

Search specifically for dedicated personal accounts:
```bash
bun skills/current/market-hunter/scripts/cli.ts "Claude Pro" --type account
```

Search across specific marketplaces and output JSON:
```bash
bun skills/current/market-hunter/scripts/cli.ts "Gemini Pro 6 Months" --markets g2a,kinguin,plati --json
```

Include all listings (including filtered low-trust offers) for debugging:
```bash
bun skills/current/market-hunter/scripts/cli.ts "GitHub Copilot 1 Year" --full
```

## Output Contract

The CLI outputs clean, human-readable terminal reports by default and structured JSON when `--json` is supplied:

```json
{
  "ok": true,
  "schema_version": 1,
  "command": "scan",
  "data": {
    "query": "ChatGPT Plus",
    "budget": 15,
    "total_scanned": 42,
    "valid_deals_count": 8,
    "filtered_scams_count": 34,
    "top_deals": [
      {
        "id": "plati-4313142",
        "marketplace": "plati",
        "title": "ChatGPT Plus Dedicated Personal Account",
        "url": "https://plati.market/itm/4313142",
        "priceUsd": 9.03,
        "trustScore": 92,
        "trustTier": "STRONG_BUY",
        "deliveryFormat": "DEDICATED_ACCOUNT",
        "seller": {
          "name": "DigitalKing",
          "positiveFeedbackPercent": 99.8,
          "totalSalesCount": 26240
        },
        "warrantyDays": 30,
        "discountVsMsrpPercent": 55,
        "recommendationSummary": "STRONG_BUY: Verified discount vs retail"
      }
    ],
    "markets_queried": ["g2a", "kinguin", "plati", "z2u", "funpay"],
    "degraded_markets": []
  }
}
```

## Exit Codes

- `0`: Successful scan and report emission.
- `2`: Invalid command arguments or configuration error.
- `124`: Scan execution timeout fired.

## Required Follow-Up Reads

| Need | Read | When |
|---|---|---|
| Scoring formulas, Bayesian math & red flags | `references/scoring.md` | Inspecting or tuning the 0-100 Trust and Deal Scoring Engine |
| Marketplace catalog profiles, routes & new adapters | `references/marketplaces.md` | Inspecting platform specialties or adding a new adapter |
