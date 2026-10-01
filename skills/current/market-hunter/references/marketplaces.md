# Marketplace navigation and markup

This page covers how each adapter reaches its marketplace, the markup each parser expects, and what listing wording means for buyer safety. It lists no products, category IDs, or prices. Find those live with the `parallel` and `firecrawl` skills.

## Navigation

| Market | Default target | Discovery when the default fails |
| --- | --- | --- |
| `plati` | `plati.io/api/search.ashx` JSON search | None needed |
| `g2a` | `g2a.com/search?query=`, scraped by Firecrawl | None needed |
| `kinguin` | `kinguin.net/listing?phrase=`, scraped by Firecrawl | None needed |
| `funpay` | `funpay.com/en/` home page, which has no offers | Pass category pages with `--url` |
| `z2u` | `z2u.com/search?q=`, which renders client-side | Pass category pages with `--url` |

To find FunPay or Z2U category pages, use either route:

- The `parallel` skill: search for the product with the domain restricted to `funpay.com` or `z2u.com`.
- The `firecrawl` skill: `map https://funpay.com --search <product>` or `map https://www.z2u.com --search <product>`.

Pass listing pages, not single offers. FunPay listing pages look like `/en/lots/<id>/`. Z2U listing pages look like `/<slug>/<category>-<n>-<id>`.

## Markup notes

These parser assumptions broke against live pages. Check them first when a market shows up in `degraded_markets`.

- FunPay serves complete offer HTML to a plain fetch. Offer anchors put `href` before `class="tc-item"`, so the parser matches either attribute order. Prices are in EUR unless the request sends the `cy=usd` cookie. `rating-mini-count` holds the seller review count.
- Z2U category pages serve product cards to a plain fetch: `productCardStyle` anchors that contain `title`, `fromAttr`, and `priceTxt` spans. The card price is the cheapest seller's price.
- Kinguin markdown from Firecrawl shows `From` and then `$X.XX`, with the symbol first. Detail pages often require login, so use list prices. Keys labeled "ONLY FOR NEW ACCOUNTS" need an eligibility check.
- G2A listings state an activation region even on GLOBAL versions. Read the region label before you recommend a listing.
- Adapters that cannot read seller ratings fill in a fixed default. Treat `positiveFeedbackPercent` from G2A, Kinguin, Z2U, and FunPay as unmeasured.

## Delivery wording

| Listing wording | Verdict | CLI format |
| --- | --- | --- |
| Manual Top Up, Login Top Up, By logging in, Put into my account | Credentials required. Never recommend. | `CREDENTIALS_REQUIRED` |
| Redeem Link, Self Redeem, Digital key, Activation Link, Activation Code, Without login | Buyer activates it. Safe default. | `PROMO_LINK_OR_CODE` |
| Invite, Family Invitation, Family Plan Member, Slot | Family or group. Conditional, with lockout risk. | `BUYER_EMAIL_UPGRADE` |

The CLI classifies from the title and any delivery label on the listing page. Confirm the delivery method on the product page, because sellers put carrier stock and login top-ups under self-redeem titles.

## Add a marketplace adapter

1. Create `lib/adapters/<name>.py` that implements the `MarketplaceAdapter` protocol in `lib/models.py`.
2. Register it in `register_builtin_adapters` in `lib/adapters/__init__.py`.
3. Make `<name>` appear as a label in the marketplace hostname, because `--url` routes each URL to the adapter whose `id` is one of the host's labels.
4. Add a parser test built from real page markup to `tests/test_market_hunter.py`.
